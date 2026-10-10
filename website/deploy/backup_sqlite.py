"""Atomic, WAL-safe SQLite snapshot via the SQLite online backup API.

Run inside the deployment container with:
  python -m deploy.backup_sqlite
Files are kept in /backups, separate from the live /data volume.
"""
import argparse
from contextlib import closing
import sqlite3
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def readonly(path: Path):
    """Open an existing SQLite file without silently creating an empty database."""
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def validate(db):
    integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
    if integrity != 'ok':
        raise RuntimeError(f'Snapshot integrity check failed: {integrity}')
    if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
        raise RuntimeError('Snapshot has invalid foreign key references.')


def backup(source: Path, destination: Path, keep: int = 30):
    source = Path(source)
    destination = Path(destination)
    if not source.is_file():
        raise FileNotFoundError(f'No SQLite database exists at {source}')
    destination.mkdir(parents=True, exist_ok=True)
    if source.parent.resolve() == destination.resolve():
        raise ValueError('Backup folder must not be the live database folder.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    final = destination / f'league-{stamp}.sqlite3'
    handle, temp = tempfile.mkstemp(prefix='.snapshot-', suffix='.sqlite3', dir=destination)
    os.close(handle)
    try:
        # sqlite3's connection context manager commits but does NOT close;
        # explicit closing ensures WAL sidecars are checkpointed before rename.
        with closing(readonly(source)) as live:
            with closing(sqlite3.connect(temp)) as snapshot:
                live.backup(snapshot)
                validate(snapshot)
        os.chmod(temp, 0o600)
        os.replace(temp, final)
    finally:
        for suffix in ('', '-wal', '-shm'):
            if os.path.exists(temp + suffix):
                os.remove(temp + suffix)
    if keep > 0:
        stored = sorted(destination.glob('league-*.sqlite3'), reverse=True)
        for old in stored[keep:]:
            old.unlink()
    return final


def restore(snapshot: Path, target: Path, *, overwrite: bool = False):
    """Restore a validated snapshot atomically; the live service must be stopped.

    Fresh targets are the default for restore drills. Explicit overwrites refuse
    SQLite sidecars, since replacing a file in use can corrupt another connection.
    """
    snapshot, target = Path(snapshot).resolve(), Path(target).resolve()
    if not snapshot.is_file():
        raise FileNotFoundError(f'No snapshot exists at {snapshot}')
    if target == snapshot:
        raise ValueError('Restore target must differ from the snapshot.')
    if target.exists() and not overwrite:
        raise FileExistsError('Restore target exists; choose a fresh target or pass --overwrite with the service stopped.')
    if any(Path(str(target) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError('Restore target has SQLite sidecars; stop all database users before restoring.')
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.restore-', suffix='.sqlite3', dir=target.parent)
    os.close(handle)
    try:
        with closing(readonly(snapshot)) as original:
            validate(original)
            with closing(sqlite3.connect(temporary)) as recovered:
                original.backup(recovered)
                validate(recovered)
        os.chmod(temporary, 0o600)
        if overwrite:
            os.replace(temporary, target)
        else:
            # An atomic, non-overwriting install also handles a target race.
            os.link(temporary, target)
        return target
    finally:
        for suffix in ('', '-wal', '-shm'):
            candidate = temporary + suffix
            if os.path.exists(candidate):
                os.remove(candidate)


def main():
    parser = argparse.ArgumentParser(description='Consistent, validated SQLite backup')
    parser.add_argument('--database', default=os.getenv('CHESS_DB_PATH', '/data/league.sqlite3'))
    parser.add_argument('--output-dir', default='/backups')
    parser.add_argument('--keep', type=int, default=30)
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--restore', type=Path, help='Restore this snapshot instead of creating a backup')
    parser.add_argument('--target', type=Path, help='Fresh restored database path')
    parser.add_argument('--overwrite', action='store_true', help='Explicitly replace the target (stop the service first)')
    args = parser.parse_args()
    if args.restore:
        if not args.target:
            parser.error('--restore requires --target')
        file = restore(args.restore, args.target, overwrite=args.overwrite)
        action = 'Database restored'
    else:
        if args.target or args.overwrite:
            parser.error('--target and --overwrite require --restore')
        file = backup(Path(args.database), Path(args.output_dir), args.keep)
        action = 'Backup created'
    if not args.quiet:
        print(f'{action}: {file}')


if __name__ == '__main__':
    main()
