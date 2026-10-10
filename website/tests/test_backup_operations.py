"""Real restore drills, WAL snapshots and failure monitoring behavior."""
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import subprocess

import pytest

from deploy.backup_sqlite import backup, restore
from deploy.backup_service import healthy, run_once


def database(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE players (id INTEGER PRIMARY KEY, name TEXT)')
    db.execute("INSERT INTO players VALUES(1,'Fictional Player')")
    db.commit()
    return db


def test_online_backup_and_restore_with_uncheckpointed_wal(tmp_path):
    live = tmp_path / 'data' / 'live.sqlite3'
    connection = database(live)
    try:
        snapshot = backup(live, tmp_path / 'backups')
        restored = restore(snapshot, tmp_path / 'drill' / 'restored.sqlite3')
        with sqlite3.connect(restored) as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert db.execute('SELECT name FROM players').fetchone()[0] == 'Fictional Player'
        assert restored.stat().st_mode & 0o777 == 0o600
        with pytest.raises(FileExistsError):
            restore(snapshot, restored)
        with pytest.raises(ValueError, match='sidecars'):
            restore(snapshot, live, overwrite=True)
    finally:
        connection.close()


def test_restore_bad_snapshot_does_not_replace_existing_file(tmp_path):
    snapshot = tmp_path / 'invalid.sqlite3'
    snapshot.write_bytes(b'not a SQLite database')
    target = tmp_path / 'live.sqlite3'
    original = b'keep existing contents'
    target.write_bytes(original)
    with pytest.raises(sqlite3.DatabaseError):
        restore(snapshot, target, overwrite=True)
    assert target.read_bytes() == original
    assert not list(tmp_path.glob('.restore-*'))


def test_backup_and_restore_refuse_invalid_foreign_keys(tmp_path):
    source = tmp_path / 'invalid-relations.sqlite3'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE teams(id INTEGER PRIMARY KEY)')
        db.execute('CREATE TABLE players(id INTEGER PRIMARY KEY, team_id INTEGER REFERENCES teams(id))')
        db.execute('INSERT INTO players VALUES(1,999)')
    with pytest.raises(RuntimeError, match='foreign key'):
        backup(source, tmp_path / 'backups')
    with pytest.raises(RuntimeError, match='foreign key'):
        restore(source, tmp_path / 'drill.sqlite3')
    assert not (tmp_path / 'drill.sqlite3').exists()
    assert not list((tmp_path / 'backups').glob('league-*'))


def test_backup_service_reports_missing_database_then_success(tmp_path, monkeypatch):
    monkeypatch.delenv('RESTIC_REPOSITORY', raising=False)
    source = tmp_path / 'data' / 'live.sqlite3'
    directory = tmp_path / 'backups'
    with pytest.raises(FileNotFoundError):
        run_once(source, directory)
    assert not source.exists()
    assert not healthy(directory, 3600)
    connection = database(source)
    connection.close()
    snapshot = run_once(source, directory)
    assert snapshot.exists()
    assert healthy(directory, 3600)
    status = json.loads((directory / 'status.json').read_text())
    status['last_success'] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    (directory / 'status.json').write_text(json.dumps(status))
    assert not healthy(directory, 3600)


def test_offserver_failure_keeps_snapshot_and_is_unhealthy(tmp_path, monkeypatch, caplog):
    source = tmp_path / 'data' / 'live.sqlite3'
    connection = database(source)
    connection.close()
    directory = tmp_path / 'backups'
    monkeypatch.setenv('RESTIC_REPOSITORY', 's3:https://private-repository.example/backup')
    def fail(command, **kwargs):
        assert command[:3] == ['restic', 'backup', '--tag']
        return subprocess.CompletedProcess(command, 1, b'', b'contains confidential repository details')
    monkeypatch.setattr(subprocess, 'run', fail)
    with pytest.raises(RuntimeError, match='off-server'):
        run_once(source, directory)
    assert len(list(directory.glob('league-*.sqlite3'))) == 1
    assert not healthy(directory, 3600)
    assert 'private-repository' not in caplog.text
    assert 'confidential' not in caplog.text
