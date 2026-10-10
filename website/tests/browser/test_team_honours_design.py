"""Readable engraved season medals and navigation in both languages."""
import os
from pathlib import Path
import pytest
from playwright.sync_api import expect
from test_member_journey import chromium,league_server,assert_fits_phone
from test_team_honours import seed_podium

pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Set RUN_BROWSER_TESTS=1 to require Chromium journeys.')


@pytest.mark.parametrize('width',[320,390,1440])
def test_team_medal_colours_year_and_season_navigation(chromium,league_server,width):
    league=league_server
    season,teams,fixtures,players=seed_podium()
    context=chromium.new_context(viewport={'width':width,'height':900})
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(league.base+'/') else route.abort())
    page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        for team,medal,label in zip(teams,['gold','silver','bronze'],['Medalha de ouro','Medalha de prata','Medalha de bronze']):
            page.goto(league.base+f'/teams/{team}')
            expect(page.locator(f'.medal-{medal} .medal-season')).to_have_text('2024-2025')
            expect(page.locator('.season-honour-copy')).to_contain_text(label)
            expect(page.locator('#team-honours-title')).to_have_text('Conquistas por época')
            assert_fits_phone(page)
            directory=Path('/workspace/review-runtime/v28-screenshots')
            if directory.parent.exists():
                directory.mkdir(exist_ok=True)
                page.locator('.team-honours').screenshot(path=str(directory/f'{medal}-{width}.png'))
        page.evaluate("localStorage.setItem('clubdraft.language','en')")
        page.reload()
        expect(page.locator('#team-honours-title')).to_have_text('Season honours')
        expect(page.locator('.season-honour-copy')).to_contain_text('Bronze medal')
        page.locator('.season-honour-card').click()
        page.wait_for_url(league.base+f'/seasons?season={season}')
        expect(page.locator('h1')).to_have_text('2024-2025')
        page.goto(league.base+f'/teams/{teams[3]}')
        expect(page.locator('.team-honours')).to_have_count(0)
        assert not errors,errors
    finally:context.close()
