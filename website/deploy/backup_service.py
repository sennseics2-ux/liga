"""Scheduled online snapshots with optional encrypted off-server restic copies."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import subprocess
import tempfile
import time

from deploy.backup_sqlite import backup

LOG = logging.getLogger('league.backups')


def write_status(directory: Path, values: dict):
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.backup-status-', dir=directory)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(values, stream)
        os.chmod(name, 0o600)
        os.replace(name, directory / 'status.json')
    finally:
        if os.path.exists(name):
            os.unlink(name)


def offsite_environment():
    """Credential files use KEY=VALUE lines; they are never interpreted by a shell."""
    environment = dict(os.environ)
    credentials = environment.get('CHESS_OFFSITE_ENV_FILE')
    if credentials:
        for line in Path(credentials).read_text().splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            key, separator, value = line.partition('=')
            if not separator or key.strip() not in {'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'AWS_DEFAULT_REGION'}:
                raise ValueError('Off-server credential file contains an unsupported setting.')
            environment[key.strip()] = value.strip()
    return environment


def run_once(source: Path, directory: Path, keep: int = 30):
    stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    offsite = bool(os.environ.get('RESTIC_REPOSITORY'))
    try:
        snapshot = backup(source, directory, keep=keep)
        if offsite:
            # The repository must be initialized once by the operator. Do not
            # log subprocess output: repository/credential details may be present.
            result = subprocess.run(['restic', 'backup', '--tag', 'liga-sx-aac', str(snapshot)],
                                    env=offsite_environment(), capture_output=True, timeout=3600)
            if result.returncode:
                raise RuntimeError('Encrypted off-server backup failed; verify repository access and credentials.')
        write_status(directory, {'status': 'ok', 'last_success': stamp,
                                 'snapshot': snapshot.name, 'offsite_enabled': offsite})
        LOG.info('Validated backup completed%s', ' and copied off-server' if offsite else '')
        return snapshot
    except Exception as error:
        # Keep the previous successful time for monitoring, never report stale
        # success after an error. Logs avoid paths, repository URLs and credentials.
        try:
            previous = json.loads((directory / 'status.json').read_text())
        except (OSError, ValueError):
            previous = {}
        write_status(directory, {'status': 'error', 'last_attempt': stamp,
                                 'last_success': previous.get('last_success'),
                                 'offsite_enabled': offsite})
        LOG.error('Backup failed (%s); inspect storage and off-server configuration.', type(error).__name__)
        raise


def healthy(directory: Path, maximum_age: float):
    try:
        status = json.loads((directory / 'status.json').read_text())
        last = datetime.fromisoformat(status['last_success'])
        age = (datetime.now(timezone.utc) - last).total_seconds()
        return status['status'] == 'ok' and 0 <= age <= maximum_age
    except (OSError, ValueError, TypeError, KeyError):
        return False


def offsite_maintenance(initialize: bool = False):
    if not os.environ.get('RESTIC_REPOSITORY'):
        raise ValueError('Set RESTIC_REPOSITORY before using off-server backups.')
    command = ['restic', 'init'] if initialize else ['restic', 'check', '--read-data-subset=10%']
    result = subprocess.run(command, env=offsite_environment(), capture_output=True, timeout=3600)
    if result.returncode:
        raise RuntimeError('Off-server repository operation failed; verify access, credentials and repository state.')
    LOG.info('Off-server repository %s completed', 'initialization' if initialize else 'integrity check')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path(os.getenv('CHESS_DB_PATH', '/data/league.sqlite3')))
    parser.add_argument('--output-dir', type=Path, default=Path('/backups'))
    parser.add_argument('--interval', type=int, default=int(os.getenv('CHESS_BACKUP_INTERVAL', '86400')))
    parser.add_argument('--keep', type=int, default=30)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--healthcheck', action='store_true')
    maintenance = parser.add_mutually_exclusive_group()
    maintenance.add_argument('--initialize-offsite', action='store_true')
    maintenance.add_argument('--check-offsite', action='store_true')
    args = parser.parse_args()
    if args.interval < 60:
        parser.error('--interval must be at least 60 seconds')
    if args.healthcheck:
        raise SystemExit(0 if healthy(args.output_dir, args.interval * 1.25 + 300) else 1)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if args.initialize_offsite or args.check_offsite:
        offsite_maintenance(initialize=args.initialize_offsite)
        return
    if args.once:
        run_once(args.database, args.output_dir, args.keep)
        return
    while True:
        try:
            run_once(args.database, args.output_dir, args.keep)
            delay = args.interval
        except Exception:
            delay = min(300, args.interval)
        time.sleep(delay)


if __name__ == '__main__':
    main()
