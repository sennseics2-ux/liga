"""Season dropdown navigation and readable scoreboards on phones and desktops."""
import os
from pathlib import Path
import pytest
from playwright.sync_api import expect
from test_member_journey import chromium, league_server, assert_fits_phone
from test_v25_seasons import setup
from test_v32_dark_mode import CONTRAST
import league_seasons as seasons

pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Set RUN_BROWSER_TESTS=1 to require Chromium journeys.')


@pytest.mark.parametrize('width',[320,390,1440])
def test_current_season_dropdown_and_completed_match(chromium,league_server,width):
    league=league_server
    admin, season, rounds, match, teams, managers, rosters=setup()
    seasons.submit_lineup(match,managers[0],rosters[0])
    seasons.submit_lineup(match,managers[1],rosters[1])
    with league.store.transaction() as db:
        db.execute("UPDATE seasons SET name='2025-2026',start_year=2025,start_date='2025-09-01',end_date='2026-06-30',status='published' WHERE id=?",(season,))
        games=[r[0] for r in db.execute('SELECT game_id FROM match_games WHERE match_id=? ORDER BY board',(match,))]
        db.execute("UPDATE team_matches SET scheduled_at='2026-06-01T18:00:00+00:00' WHERE id=?",(match,))
        db.execute("UPDATE games SET scheduled_at='2026-06-01T18:00:00+00:00' WHERE id IN (SELECT game_id FROM match_games WHERE match_id=?)",(match,))
    for game,result in zip(games,['1-0','0-1','1/2-1/2','1-0']):
        league.store.update_game_result(game,result,actor_id=admin,reason='Synthetic browser fixture')
    context=chromium.new_context(viewport={'width':width,'height':900})
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(league.base+'/') else route.abort())
    page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto(league.base+'/seasons')
        expect(page.locator('h1')).to_have_text('2026-2027')
        expect(page.locator('.competition-empty h3')).to_have_text('Calendário em breve')
        assert_fits_phone(page)
        page.locator('#season-select').select_option(str(season))
        page.wait_for_url(league.base+f'/seasons?season={season}&round=all')
        expect(page.locator('h1')).to_have_text('2025-2026')
        expect(page.locator('.fixture-score').first).to_have_text('2½')
        expect(page.locator('.fixture-score').last).to_have_text('1½')
        expect(page.locator('.fixture-team-winner')).to_have_count(1)
        expect(page.locator('.season-picker button')).to_have_count(0)
        expect(page.locator('.season-metrics')).to_have_count(0)
        expect(page.locator('.schedule-round')).to_have_count(2)
        expect(page.locator('.schedule-round-complete')).to_have_count(1)
        assert_fits_phone(page)
        directory=Path('/workspace/review-runtime/v27-screenshots')
        if directory.parent.exists():
            directory.mkdir(exist_ok=True)
            page.screenshot(path=str(directory/f'season-{width}.png'),full_page=True)
        page.locator('.fixture-card').click()
        page.wait_for_url(league.base+f'/matches/{match}')
        expect(page.locator('.board-result-card')).to_have_count(4)
        expect(page.locator('.scoreboard-numbers')).to_contain_text('2½')
        assert_fits_phone(page)
        if directory.exists():
            page.screenshot(path=str(directory/f'match-{width}.png'),full_page=True)
        page.evaluate("localStorage.setItem('clubdraft.language','en')")
        page.reload()
        expect(page.locator('.competition-status')).to_have_text('Completed')
        page.locator('.match-back').click()
        page.wait_for_url(league.base+f'/seasons?season={season}')
        expect(page.locator('h1')).to_have_text('2025-2026')
        for game in games:
            league.store.update_game_result(game,'1/2-1/2',actor_id=admin,reason='Draw highlight check')
        page.reload()
        expect(page.locator('.fixture-team-draw')).to_have_count(2)
        expect(page.locator('.fixture-team-winner')).to_have_count(0)
        page.locator('#theme-toggle').click()
        expect(page.locator('html')).to_have_attribute('data-theme','dark')
        page.evaluate("() => Promise.all(document.getAnimations().filter(a=>a.effect.getComputedTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})))")
        assert not page.evaluate(CONTRAST)
        if width > 1020:
            assert page.locator('.nav-links').evaluate('(el)=>getComputedStyle(el).backgroundColor')=='rgba(0, 0, 0, 0)'
        else:
            page.locator('.mobile-toggle').click()
            expect(page.locator('.nav-links')).to_be_visible()
            assert page.locator('.nav-links').evaluate('(el)=>getComputedStyle(el).backgroundColor')!='rgba(0, 0, 0, 0)'
            page.locator('.mobile-toggle').click()
        assert_fits_phone(page)
        if directory.exists():
            page.screenshot(path=str(directory/f'draw-dark-{width}.png'),full_page=True)
        assert not errors,errors
        # Native GET navigation remains available without JavaScript.
        plain=chromium.new_context(java_script_enabled=False,viewport={'width':width,'height':900})
        plain_page=plain.new_page();plain_page.goto(league.base+'/seasons')
        plain_page.locator('#season-select').select_option(str(season))
        plain_page.locator(f'.season-fallback a[href="/seasons?season={season}"]').click()
        plain_page.wait_for_url(league.base+f'/seasons?season={season}')
        expect(plain_page.locator('h1')).to_have_text('2025-2026')
        plain.close()
    finally:
        context.close()
