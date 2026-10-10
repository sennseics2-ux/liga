"""Round and season selectors work on phones and desktop, with season league points."""
import os
import tempfile
from pathlib import Path
import pytest
from playwright.sync_api import expect
from test_member_journey import chromium,league_server,assert_fits_phone
from test_team_honours import seed_podium
from test_v32_dark_mode import CONTRAST

pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Set RUN_BROWSER_TESTS=1 for Chromium.')

@pytest.mark.parametrize('width',[320,390,1440])
def test_round_filter_and_season_match_standings(chromium,league_server,width):
    league=league_server;season,_,_,_=seed_podium()
    context=chromium.new_context(viewport={'width':width,'height':900},color_scheme='dark')
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(league.base+'/') else route.abort())
    page=context.new_page()
    try:
        page.goto(f'{league.base}/seasons?season={season}')
        expect(page.locator('.fixture-card')).to_have_count(6)
        page.locator('#round-select').select_option('2')
        page.wait_for_url(f'**/seasons?season={season}&round=2')
        expect(page.locator('.fixture-card')).to_have_count(2)
        expect(page.locator('.fixture-match-label').first).to_have_text('Podium Team 1 vs Podium Team 3')
        assert_fits_phone(page);assert not page.evaluate(CONTRAST)
        page.locator('#round-select').select_option('all');expect(page.locator('.fixture-card')).to_have_count(6)
        page.locator('#round-select').select_option('2');expect(page.locator('.fixture-card')).to_have_count(2)
        page.locator('#season-select').select_option('current')
        page.wait_for_url('**/seasons?season=current&round=all')
        expect(page.locator('#round-select')).to_have_value('all')
        page.goto(f'{league.base}/standings?season={season}')
        expect(page.locator('.standings-table .score')).to_have_text(['9','6','3','0'])
        assert_fits_phone(page);assert not page.evaluate(CONTRAST)
        directory=(Path('/workspace/review-runtime') if Path('/workspace/review-runtime').exists() else Path(tempfile.gettempdir()))/'v35-screenshots';directory.mkdir(exist_ok=True)
        page.screenshot(path=str(directory/f'standings-dark-{width}.png'),full_page=True)
        page.locator('#standings-season').select_option('current')
        expect(page.locator('.standings-table .score')).to_have_text(['0','0','0','0','0','0'])
        assert_fits_phone(page)
    finally:context.close()
