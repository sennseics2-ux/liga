"""Exercise member journeys against a real local HTTP server and Chromium.

Set RUN_BROWSER_TESTS=1 to require the browser dependency in CI. Each test uses
its own database, cookies, server and port; external requests are intercepted.
"""
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError
from urllib.request import urlopen

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    os.environ.get('RUN_BROWSER_TESTS') != '1',
    reason='Set RUN_BROWSER_TESTS=1 for the real HTTP member journey.',
)
PASSWORD = 'MemberPass123!'
PGN = '''[Event "Browser member journey"]
[Site "Local test"]
[Date "2026.10.09"]
[Round "1"]
[White "Players"]
[Black "Games"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 *
'''


@pytest.fixture(scope='module')
def chromium():
    # Unlike an optional developer smoke check, a required CI run must fail
    # loudly if its browser installation is missing.
    from playwright.sync_api import sync_playwright
    executable = os.environ.get('LIGA_CHROMIUM_PATH') or shutil.which('chromium')
    with sync_playwright() as engine:
        options = {'headless': True, 'args': ['--no-sandbox']}
        if executable:
            options['executable_path'] = executable
        browser = engine.chromium.launch(**options)
        yield browser
        browser.close()


@pytest.fixture
def league_server(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT))
    import database as store
    database_path = tmp_path / 'browser.sqlite3'
    monkeypatch.setattr(store, 'DB_PATH', database_path)
    store.init_db()
    member = store.create_account('BrowserMember', PASSWORD, 'manager')
    opponent = store.create_account('OtherManager', PASSWORD, 'manager')
    team = store.create_team('Teams')
    other_team = store.create_team('Standings')
    store.assign_manager(team, member)
    store.assign_manager(other_team, opponent)
    with store.transaction() as db:
        admin = db.execute('''INSERT INTO users(username,password_hash,role,created_at,
            player_active,manager_active) VALUES(?,?,?,?,0,0)''',
            ('BrowserAdmin', store.hash_password(PASSWORD), 'admin',
             store.iso(store.now_utc()))).lastrowid
        white = db.execute('SELECT id FROM players WHERE user_id=?', (member,)).fetchone()['id']
        db.execute("UPDATE players SET name='Players',club='Teams' WHERE id=?", (white,))
    black = store.create_player('Games', 'Players', 1800)
    game = store.create_game(white, black, '2026-10-09T18:00:00+00:00', 'Browser fixture', '1')
    store.attach_pgn(game, PGN, actor_id=admin, reason='Seed browser replay fixture')
    auction = store.create_auction(black, 50, 24)
    store.place_bid(auction, team, 50)

    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        port = reserve.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    env = {key: value for key, value in os.environ.items() if not key.startswith('CHESS_')}
    env.update(CHESS_DB_PATH=str(database_path),
               CHESS_SESSION_SECRET='browser-session-secret-for-v24-members-123456789',
               CHESS_AUTO_BACKUP='0', PYTHONDONTWRITEBYTECODE='1')
    log_path = tmp_path / 'server.log'
    with log_path.open('w') as log:
        server = subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1',
             '--port', str(port), '--log-level', 'warning'],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    pytest.fail(f'Browser server exited: {log_path.read_text()}')
                try:
                    with urlopen(base + '/health', timeout=0.3) as response:
                        if response.status == 200:
                            break
                except (URLError, TimeoutError):
                    pass
                time.sleep(0.05)
            else:
                pytest.fail(f'Browser server did not become ready: {log_path.read_text()}')
            yield SimpleNamespace(base=base, game=game, auction=auction,
                                  other_team=other_team, store=store)
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


def assert_fits_phone(page):
    overflow = page.evaluate('''() => [...document.querySelectorAll('body *')]
        .filter(el => el.getBoundingClientRect().right > innerWidth + 1)
        .map(el => ({tag:el.tagName, classes:el.className,
                    right:Math.round(el.getBoundingClientRect().right)})).slice(0,12)''')
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), (page.url, overflow)


@pytest.mark.parametrize('width', [320, 390])
def test_member_replay_auction_and_recovery_journey(chromium, league_server, width):
    league = league_server
    context = chromium.new_context(viewport={'width': width, 'height': 850})
    context.route('**/*', lambda route: route.continue_()
                  if route.request.url.startswith(league.base + '/') else route.abort())
    page = context.new_page()
    script_errors = []
    page.on('pageerror', lambda error: script_errors.append(str(error)))
    try:
        for path in ('/', '/teams', '/players', '/games', f'/games/{league.game}', '/register'):
            response = page.goto(league.base + path)
            assert response.status == 200
            assert_fits_phone(page)
        assert page.locator('.form-card').bounding_box()['y'] < page.locator('.auth-pitch').bounding_box()['y']

        page.goto(f'{league.base}/games/{league.game}')
        assert page.locator('#replay-data').count() == 0
        assert page.locator('[data-board]').count() == 0
        assert '1. e4 e5' not in page.content()
        assert page.locator('a[href^="/login?next=/games/"]').count() == 1
        denied = context.request.get(f'{league.base}/games/{league.game}/pgn',
                                     headers={'Accept': 'application/json'})
        assert denied.status == 401

        page.locator('a[href^="/login?next=/games/"]').click()
        assert page.locator('input[name=next]').input_value() == f'/games/{league.game}'
        page.locator('input[name=username]').fill('BrowserMember')
        page.locator('input[name=password]').fill(PASSWORD)
        page.locator('form.stack-form button[type=submit]').click()
        page.wait_for_url(f'{league.base}/games/{league.game}')
        assert page.locator('#replay-data').count() == 1
        assert page.locator('[data-board] [role=gridcell]').count() == 64
        page.locator('.replay-layout').focus()
        page.keyboard.press('ArrowRight')
        assert page.locator('.replay-move.selected').count() == 1
        assert_fits_phone(page)
        download = context.request.get(f'{league.base}/games/{league.game}/pgn',
                                       headers={'Accept': 'application/json'})
        assert download.status == 200
        assert download.text() == PGN
        assert 'no-store' in download.headers['cache-control']

        page.locator('#language-toggle').focus()
        page.keyboard.press('Enter')
        assert page.locator('#language-toggle').get_attribute('aria-expanded') == 'true'
        page.keyboard.press('End')
        page.keyboard.press('Enter')
        assert page.locator('html').get_attribute('lang') == 'en'
        assert page.locator('#language-toggle').evaluate('(el)=>el===document.activeElement')
        page.keyboard.press('Enter')
        page.keyboard.press('Home')
        page.keyboard.press('Enter')
        assert page.locator('html').get_attribute('lang') == 'pt-PT'
        assert page.locator('.game-side strong').all_inner_texts() == ['Players', 'Games']

        snapshot = lambda response: '/api/auctions/snapshot?' in response.url
        with page.expect_response(snapshot):
            page.goto(league.base + '/users/BrowserMember/manager')
        page.wait_for_function("document.querySelector('[data-live-position]').dataset.i18n==='Leading'")
        assert page.locator('[data-live-total-available]').inner_text() == '950'
        assert page.locator('a[data-i18n="Recruit players"]').count() == 1
        league.store.place_bid(league.auction, league.other_team, 60)
        with page.expect_response(snapshot):
            page.evaluate("window.dispatchEvent(new Event('online'))")
        page.wait_for_function("document.querySelector('[data-live-position]').dataset.i18n==='Outbid'")
        assert page.locator('[data-live-total-available]').inner_text() == '1000'
        assert_fits_phone(page)

        with page.expect_response(snapshot):
            page.goto(f'{league.base}/auctions/{league.auction}')
        page.wait_for_function("document.querySelector('[data-live-high-bid]').textContent==='60'")
        page.locator('input[name=amount]').fill('777')
        league.store.place_bid(league.auction, league.other_team, 70)
        with page.expect_response(snapshot):
            page.evaluate("window.dispatchEvent(new Event('online'))")
        page.wait_for_function("document.querySelector('[data-live-high-bid]').textContent==='70'")
        assert page.locator('input[name=amount]').input_value() == '777'
        assert page.locator('input[name=amount]').get_attribute('min') == '71'
        assert_fits_phone(page)

        page.locator('#account-toggle').click()
        page.locator('#account-menu form[action="/logout"] button').click()
        page.goto(f'{league.base}/games/{league.game}')
        assert page.locator('#replay-data').count() == 0
        assert context.request.get(f'{league.base}/games/{league.game}/pgn',
                                   headers={'Accept': 'application/json'}).status == 401
        page.locator('a[href^="/login?next=/games/"]').click()
        page.locator('input[name=username]').fill('BrowserMember')
        page.locator('input[name=password]').fill(PASSWORD)
        page.locator('input[name=csrf]').evaluate("el=>el.value='expired-form-token'")
        with page.expect_response(lambda response: response.request.method == 'POST' and '/login' in response.url) as failed:
            page.locator('form.stack-form button[type=submit]').click()
        assert failed.value.status == 403
        assert 'text/html' in failed.value.headers['content-type']
        page.locator('a[data-i18n="Try again"]').wait_for(state='visible')
        assert page.locator('a[data-i18n="Try again"]').count() == 1
        assert_fits_phone(page)
        page.locator('a[data-i18n="Try again"]').click()
        assert page.locator('input[name=csrf]').input_value() != 'expired-form-token'
        assert page.locator('input[name=next]').input_value() == f'/games/{league.game}'

        page.goto(league.base + '/register')
        username = f'NewMember{width}'
        page.locator('input[name=username]').fill(username)
        page.locator('input[name=email]').fill(username+'@example.com')
        page.locator('select[name=role]').select_option('manager')
        page.locator('input[name=password]').fill(PASSWORD)
        page.locator('form.stack-form button[type=submit]').click()
        page.wait_for_url(f'{league.base}/users/{username}/manager')
        assert page.locator('.account-username').inner_text() == username
        assert page.locator('form[action="/my/manager/availability"]').count() == 2
        assert_fits_phone(page)
        assert not script_errors, script_errors
    finally:
        context.close()
