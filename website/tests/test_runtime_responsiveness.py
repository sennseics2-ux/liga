"""Real contention and readiness checks against one running ASGI event loop."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import timedelta
import re
import sqlite3
import threading
import time

import pytest
from fastapi.testclient import TestClient

import database as store
from main import app


def csrf(client, path='/login'):
    response = client.get(path)
    assert response.status_code == 200, response.text
    token = re.search(r'name="csrf" value="([^"]+)"', response.text)
    assert token, path
    return token.group(1)


def test_blocked_real_bid_does_not_stall_concurrent_health_requests(tmp_path, monkeypatch):
    """A RESERVED SQLite lock blocks the bid, while reads and the loop stay free.

    Both requests use the same TestClient lifespan/BlockingPortal, hence the
    same event loop. Separate clients would accidentally hide the old blocking
    async-handler defect. A watchdog releases the real lock after three seconds
    so a regression fails a timing assertion instead of hanging the test run.
    """
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'contention.sqlite3')
    with TestClient(app) as client:
        manager = store.create_account('runtime-manager', 'RuntimePassphrase123!', 'manager')
        team = store.create_team('Runtime Knights')
        store.assign_manager(team, manager)
        player = store.create_player('Available Runtime Player')
        auction = store.create_auction(player, 10, 24)
        response = client.post('/login', data={'csrf': csrf(client), 'username': 'runtime-manager',
            'password': 'RuntimePassphrase123!'}, follow_redirects=False)
        assert response.status_code == 303
        token = csrf(client, f'/auctions/{auction}')

        writer = sqlite3.connect(store.DB_PATH, isolation_level=None, check_same_thread=False)
        writer.execute('BEGIN IMMEDIATE')
        release_guard = threading.Lock()

        def release_writer():
            with release_guard:
                if writer.in_transaction:
                    writer.rollback()

        watchdog = threading.Timer(3, release_writer)
        watchdog.daemon = True
        watchdog.start()
        with ThreadPoolExecutor(max_workers=1) as workers:
            started = threading.Event()

            def make_bid():
                started.set()
                return client.post(f'/auctions/{auction}/bid',
                                   data={'csrf': token, 'amount': '25'}, follow_redirects=False)

            bid = workers.submit(make_bid)
            assert started.wait(timeout=1)
            try:
                with pytest.raises(FutureTimeoutError):
                    bid.result(timeout=0.2)
                beginning = time.monotonic()
                live = client.get('/health/live')
                healthy = client.get('/health')
                elapsed = time.monotonic() - beginning
                assert live.status_code == 200 and live.json()['status'] == 'alive'
                assert healthy.status_code == 200 and healthy.json()['database'] == 'ready'
                assert elapsed < 1.0, f'Concurrent requests stalled for {elapsed:.2f}s behind a writer'
                assert not bid.done(), 'Writer must remain blocked while health responds'
            finally:
                release_writer()
                watchdog.cancel()
            response = bid.result(timeout=5)
        writer.close()
        assert response.status_code == 303
        with store.read_db() as db:
            row = db.execute('SELECT team_id,amount FROM bids WHERE auction_id=?', (auction,)).fetchone()
        assert (row['team_id'], row['amount']) == (team, 25)


def test_readiness_after_database_removal_returns_503_without_recreating_it(tmp_path, monkeypatch):
    path = tmp_path / 'mounted' / 'league.sqlite3'
    monkeypatch.setattr(store, 'DB_PATH', path)
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200
        path.unlink()
        response = client.get('/health')
        assert response.status_code == 503
        assert response.json()['status'] == 'unavailable'
        assert not path.exists(), 'Health probes must never replace a missing database'
        assert client.get('/health/live').status_code == 200


def test_readiness_rejects_empty_existing_database_without_migrating_it(tmp_path, monkeypatch):
    path = tmp_path / 'empty.sqlite3'
    with sqlite3.connect(path):
        pass
    monkeypatch.setattr(store, 'DB_PATH', path)
    # Do not run startup: readiness must inspect, not initialize, this file.
    client = TestClient(app)
    try:
        response = client.get('/health')
        assert response.status_code == 503
        assert response.json()['status'] == 'unavailable'
    finally:
        client.close()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0] == 0


def test_quarantined_auction_is_reported_without_blocking_other_settlement_or_startup(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'quarantine.sqlite3')
    with TestClient(app) as client:
        buyer = store.create_account('quarantine-manager', 'RuntimePassphrase123!', 'manager')
        team = store.create_team('Quarantine Knights')
        store.assign_manager(team, buyer)
        broken_player = store.create_player('Legacy Invalid Manager Player')
        healthy_player = store.create_player('Healthy Transfer Player')
        broken = store.create_auction(broken_player, 10, 24)
        healthy = store.create_auction(healthy_player, 10, 24)
        store.place_bid(healthy, team, 25)
        with store.transaction() as db:
            # Model existing corrupted/legacy data; normal manager activation
            # now prevents this state before it can be created.
            db.execute('UPDATE players SET is_manager_player=1 WHERE id=?', (broken_player,))
            db.execute('UPDATE auctions SET ends_at=? WHERE id IN (?,?)',
                       (store.iso(store.now_utc() - timedelta(seconds=1)), broken, healthy))
        assert store.settle_expired() == 1
        ready = client.get('/health')
        assert ready.status_code == 200
        assert ready.json()['failed_auctions'] == 1
        assert ready.json()['overdue_auctions'] == 0
        assert client.get('/').status_code == 200
        with store.read_db() as db:
            assert db.execute('SELECT status FROM auctions WHERE id=?', (broken,)).fetchone()[0] == 'failed'
            assert db.execute('SELECT status FROM auctions WHERE id=?', (healthy,)).fetchone()[0] == 'closed'
            assert db.execute('SELECT owner_team_id FROM players WHERE id=?', (healthy_player,)).fetchone()[0] == team
    # Reopening the same application runs migrations/settlement against that
    # quarantine again and must keep the league available.
    with TestClient(app) as restarted:
        response = restarted.get('/health')
        assert response.status_code == 200
        assert response.json()['failed_auctions'] == 1
        assert restarted.get('/').status_code == 200


def test_logout_revokes_browser_replay_access_and_invalid_csrf_keeps_session(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'logout-access.sqlite3')
    with TestClient(app) as client:
        white = store.create_player('White Replay Player')
        black = store.create_player('Black Replay Player')
        game = store.create_game(white, black, '2026-06-15T12:00')
        pgn = '[Event "Private Moves"]\n[Result "*"]\n\n1. e4 e5 2. Nf3 Nc6 *\n'
        store.attach_pgn(game, pgn)
        store.create_account('runtime-viewer', 'RuntimePassphrase123!', 'player')
        login = client.post('/login', data={'csrf': csrf(client), 'username': 'runtime-viewer',
            'password': 'RuntimePassphrase123!'}, follow_redirects=False)
        assert login.status_code == 303
        assert login.headers['cache-control'] == 'private, no-store'
        assert 'replay-data' in client.get(f'/games/{game}').text
        assert client.post('/logout', data={'csrf': 'invalid'}).status_code == 403
        assert client.get(f'/games/{game}/pgn').text == pgn
        token = csrf(client, f'/games/{game}')
        logged_out = client.post('/logout', data={'csrf': token}, follow_redirects=False)
        assert logged_out.status_code == 303
        assert logged_out.headers['cache-control'] == 'private, no-store'
        assert 'session' not in client.cookies
        summary = client.get(f'/games/{game}')
        assert 'Log in to replay this game' in summary.text
        assert 'replay-data' not in summary.text
        assert 'Private Moves' not in summary.text
        download = client.get(f'/games/{game}/pgn', follow_redirects=False)
        assert download.status_code == 401
        assert download.headers['cache-control'] == 'private, no-store'
        assert download.headers['vary'] == 'Cookie'
        assert download.text != pgn
