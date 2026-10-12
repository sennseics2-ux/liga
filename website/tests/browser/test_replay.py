"""Browser replay behavior against the real application without external requests.

Run with RUN_BROWSER_TESTS=1 after installing the development dependencies and
Chromium (system package or `python -m playwright install chromium`).
"""
import os
from pathlib import Path
import shutil

import pytest

import database as store
from test_league import client, post


pytestmark = pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS') != '1',
                                reason='Enable RUN_BROWSER_TESTS=1 for Chromium tests')

START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR'
PGN = f'''[SetUp "1"]
[FEN "{START} b KQkq - 0 10"]
[Result "*"]

10... e5 11. e4 Nc6 12. Nf3 Nf6 13. Bc4 Bc5 *
'''


def test_replay_black_start_keyboard_flip_playback_and_localized_accessibility(client):
    # Visitors can replay without a login; hidden fixtures stay protected.
    white = store.create_player('Players')
    black = store.create_player('Teams')
    game_id = store.create_game(white, black, '2026-06-15T12:00:00+00:00', 'Players')
    with store.transaction() as db:
        db.execute('UPDATE games SET pgn_text=? WHERE id=?', (PGN, game_id))

    from playwright.sync_api import sync_playwright, expect

    with sync_playwright() as playwright:
        executable = shutil.which('chromium') or shutil.which('chromium-browser')
        if not executable and not Path(playwright.chromium.executable_path).exists():
            pytest.fail('RUN_BROWSER_TESTS=1 requires Chromium; run playwright install chromium')
        browser = playwright.chromium.launch(executable_path=executable, headless=True)
        context = browser.new_context(viewport={'width':390, 'height':844})
        context.add_init_script("localStorage.setItem('clubdraft.language', 'en')")
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def local_application(route):
            from urllib.parse import urlsplit
            address = urlsplit(route.request.url)
            response = client.get(address.path + ('?' + address.query if address.query else ''))
            route.fulfill(status=response.status_code, body=response.content,
                          headers={'content-type':response.headers.get('content-type', 'text/plain')})

        # All requests, including JS/CSS, use the same isolated TestClient DB.
        page.route('http://liga.test/**', local_application)
        page.goto(f'http://liga.test/games/{game_id}')
        replay = page.locator('[data-chess-replay]')
        # Replay works as soon as the page opens, without clicking or focusing it.
        page.keyboard.press('ArrowRight')
        expect(page.locator('[data-progress]')).to_contain_text('Move 10… e5')
        page.keyboard.press('ArrowLeft')
        expect(page.locator('[data-progress]')).to_have_text('Starting position')
        expect(page.locator('.replay-sidebar-header span')).to_have_text('4 moves')
        assert page.locator('.replay-controls').locator('[data-action=flip]').count() == 1
        assert page.locator('.replay-sidebar').locator('[data-action=play]').count() == 1
        page.locator('#account-toggle').click()
        styles = page.locator('[data-piece-style]')
        expect(styles).to_have_value('cardinal')
        page.keyboard.press('ArrowRight')
        expect(page.locator('[data-progress]')).to_have_text('Starting position')
        styles.focus()
        page.keyboard.press('ArrowRight')
        expect(page.locator('[data-progress]')).to_have_text('Starting position')
        expect(styles).to_have_value('cburnett')
        styles.select_option('cardinal')
        expect(styles.locator('option')).to_have_count(43)
        expect(page.locator('[data-board] img.replay-piece')).to_have_count(32)
        for style in styles.locator('option').evaluate_all('(options)=>options.map(option=>option.value)'):
            styles.select_option(style)
            try:
                page.wait_for_function('''() => Array.from(document.querySelectorAll('[data-board] img')).every(img => img.complete && img.naturalWidth > 0)''', timeout=5000)
            except Exception:
                failures = page.locator('[data-board] img').evaluate_all('(images)=>images.filter(img=>!img.complete || !img.naturalWidth).map(img=>img.src)')
                pytest.fail(f'{style} artwork did not load: {failures}')
        styles.select_option('cburnett')
        page.reload()
        page.locator('#account-toggle').click()
        expect(page.locator('[data-piece-style]')).to_have_value('cburnett')
        page.locator('[data-piece-style]').select_option('cardinal')
        page.locator('#account-toggle').click()
        expect(page.locator('[data-board] [role="row"]')).to_have_count(8)
        expect(page.locator('[data-board] [role="gridcell"]')).to_have_count(64)
        expect(page.locator('[data-board] [role="gridcell"]').first).to_have_attribute('data-square', 'a8')
        expect(page.locator('[data-progress]')).to_have_text('Starting position')
        first_row = page.locator('[data-moves] > *')
        expect(first_row.nth(0)).to_have_text('10.')
        expect(first_row.nth(1)).to_have_class('replay-move-placeholder')
        expect(first_row.nth(2)).to_have_text('e5')
        expect(first_row.nth(3)).to_have_text('11.')
        expect(first_row.nth(4)).to_have_text('e4')

        replay.focus()
        page.keyboard.press('ArrowRight')
        expect(page.locator('[data-progress]')).to_contain_text('Move 10… e5')
        expect(page.locator('[data-position-description]')).to_contain_text('White to move')
        expect(page.locator('.replay-move[aria-current="step"]')).to_have_text('e5')
        page.keyboard.press('f')
        expect(page.locator('[data-action="flip"]')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('[data-board] [role="gridcell"]').first).to_have_attribute('data-square', 'h1')
        expect(page.locator('[data-file-coords] span').first).to_have_text('h')
        expect(page.locator('[data-rank-coords] span').first).to_have_text('1')
        page.keyboard.press('End')
        expect(page.locator('.replay-move[aria-current="step"]')).to_have_text('Bc5')
        page.keyboard.press('Home')
        expect(page.locator('[data-progress]')).to_have_text('Starting position')
        expect(page.locator('[data-action="prev"]')).to_be_disabled()

        page.locator('.replay-more summary').click()
        page.locator('[data-speed]').focus()
        page.keyboard.press('ArrowRight')
        expect(page.locator('[data-progress]')).to_have_text('Starting position')
        page.locator('[data-speed]').select_option('625')
        page.locator('.replay-more summary').click()
        page.locator('[data-action="play"]').click()
        expect(page.locator('[data-action="play"]')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('[data-action="play"]')).to_have_attribute('aria-label', 'Pause')
        expect(page.locator('[data-action="play"]')).to_have_attribute('aria-pressed', 'false', timeout=7000)
        expect(page.locator('[data-progress]')).to_contain_text('4 / 4 moves')
        expect(page.locator('[data-action="next"]')).to_be_disabled()

        page.evaluate("window.LigaI18n.setLanguage('pt-PT')")
        expect(page.locator('[data-progress]')).to_contain_text('Lance 13… Bc5')
        expect(page.locator('[data-action="play"]')).to_have_attribute('aria-label', 'Reproduzir')
        expect(page.locator('[data-position-description]')).to_contain_text('Brancas')
        expect(page.locator('[data-board] [data-square="a1"]')).to_have_attribute('aria-label', 'a1: torre branca')
        # Dynamic identities must stay exact even when they match UI labels.
        expect(page.locator('.game-side strong').first).to_have_text('Players')
        expect(page.locator('.game-side strong').last).to_have_text('Teams')
        page.evaluate("window.LigaI18n.setLanguage('en')")
        expect(page.locator('[data-action="play"]')).to_have_attribute('aria-label', 'Play')
        assert errors == []
        context.close()
        browser.close()
