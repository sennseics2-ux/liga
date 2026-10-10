"""Server hardening and persistent SQLite backup tests for V13."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from deploy.backup_sqlite import backup
from deploy.security import allowed

ROOT = Path(__file__).resolve().parents[1]


def test_sqlite_backup_snapshot_integrity_and_retention(tmp_path):
    live = tmp_path / 'data' / 'league.sqlite3'
    live.parent.mkdir()
    snapshots = tmp_path / 'backups'
    with sqlite3.connect(live) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE games (id INTEGER PRIMARY KEY, result TEXT)')
        db.execute("INSERT INTO games VALUES (1,'1-0')")
    for i in range(3):
        path = backup(live, snapshots, keep=2)
        with sqlite3.connect(path) as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert db.execute('SELECT result FROM games WHERE id=1').fetchone()[0] == ('1-0' if i < 2 else '1/2-1/2')
        if i == 1:
            with sqlite3.connect(live) as db:
                db.execute("UPDATE games SET result='1/2-1/2' WHERE id=1")
    assert len(list(snapshots.glob('league-*.sqlite3'))) == 2
    assert not list(snapshots.glob('.snapshot-*'))


def test_login_signup_basic_ratelimit():
    ip='unique-test-local-ip'
    assert all(allowed(ip, '/register') for _ in range(6))
    assert not allowed(ip, '/register')
    assert allowed(ip, '/dashboard')


def _separate_python(code, **extra_env):
    env = {**os.environ, 'CHESS_ENV': 'production',
           'CHESS_ALLOWED_HOSTS': 'club.test',
           'CHESS_SESSION_SECRET': 'a' * 64,
           'CHESS_HTTPS_ONLY': '1', **extra_env}
    return subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=30)


def test_production_rejects_insecure_env():
    missing = _separate_python('import main', CHESS_SESSION_SECRET='bad')
    assert missing.returncode != 0
    assert 'CHESS_SESSION_SECRET' in missing.stderr
    insecure = _separate_python('import main', CHESS_HTTPS_ONLY='0')
    assert insecure.returncode != 0
    assert 'CHESS_HTTPS_ONLY' in insecure.stderr
    placeholder = _separate_python('import main', CHESS_SESSION_SECRET='REPLACE_WITH_RANDOM_64_CHAR_SECRET')
    assert placeholder.returncode != 0


def test_production_headers_trusted_hosts_and_secure_login(tmp_path):
    code = '''
import re
from fastapi.testclient import TestClient
from main import app
with TestClient(app, base_url='https://club.test') as client:
    response = client.get('/')
    assert response.status_code == 200, response.text
    assert 'Content-Security-Policy' in response.headers
    assert 'max-age=' in response.headers['Strict-Transport-Security']
    assert client.get('/health').json()['status'] == 'ok'
    assert client.get('/docs').status_code == 404
    assert client.get('https://evil.test/').status_code == 400
    login = client.get('/login')
    token = re.search(r'name="csrf" value="([^"]+)"', login.text).group(1)
    post = client.post('/register', data={'csrf':token, 'role':'player',
         'username':'prodmgr', 'password':'StrongerPassword!23'}, follow_redirects=False)
    assert post.status_code == 303, post.text
    assert 'secure' in post.headers.get('set-cookie','').lower()
    assert client.get('/dashboard').status_code == 200
print('production checks passed')
'''
    result = _separate_python(code, CHESS_DB_PATH=str(tmp_path / 'prod.sqlite3'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'production checks passed' in result.stdout
