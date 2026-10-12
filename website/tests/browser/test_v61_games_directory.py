"""Game-card navigation, responsive filters, outcomes and readable contrast."""
import os
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from playwright.sync_api import expect
import database as store
import league_seasons as seasons
from test_league import client
from test_v25_seasons import setup
from test_member_journey import chromium, assert_fits_phone
from test_v32_dark_mode import CONTRAST
pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Enable Chromium checks.')

@pytest.mark.parametrize('width',[1280,390,320])
@pytest.mark.parametrize('theme',['light','dark'])
def test_game_directory(chromium,client,width,theme):
    admin,season,rounds,match,teams,captains,rosters=setup()
    for captain,roster in zip(captains,rosters):seasons.submit_lineup(match,captain,roster)
    with store.transaction() as db:
        db.execute("UPDATE seasons SET status='published' WHERE id=?",(season,))
        db.execute("UPDATE team_matches SET scheduled_at='2026-06-01T12:00:00+00:00' WHERE id=?",(match,))
        games=[r[0] for r in db.execute('SELECT game_id FROM match_games WHERE match_id=? ORDER BY board',(match,))]
        for game,result in zip(games,['1-0','0-1','1/2-1/2','*']):
            db.execute("UPDATE games SET result=?,scheduled_at='2026-06-01T12:00:00+00:00' WHERE id=?",(result,game))
        db.execute('UPDATE players SET name=? WHERE id=?',('Alexandra Long Player Name With Many Words',rosters[0][0]))
        db.executemany("INSERT INTO games (white_player_id,black_player_id,scheduled_at,result,created_at) VALUES(?,?,'2026-01-01T12:00:00+00:00','1-0','2026-01-01T00:00:00+00:00')",[(rosters[0][0],rosters[1][0])]*27)
    context=chromium.new_context(viewport={'width':width,'height':960},color_scheme=theme)
    context.add_init_script("localStorage.setItem('clubdraft.language','en')")
    def local_application(route):
        url=urlsplit(route.request.url)
        if url.netloc!='liga.test':route.abort();return
        response=client.get(url.path+('?' + url.query if url.query else ''))
        route.fulfill(status=response.status_code,body=response.content,headers={'content-type':response.headers.get('content-type','text/plain')})
    context.route('**/*',local_application)
    page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto('http://liga.test/games')
        expect(page.locator('.game-list-card')).to_have_count(25)
        expect(page.locator('.game-result-caption')).to_have_text(['Not played','Draw','Black wins','White wins']+['White wins']*21)
        assert page.locator('.game-list-card[data-result="1-0"] .game-player-white').first.get_attribute('class').endswith('game-player-winner')
        assert page.locator('.game-list-card[data-result="0-1"] .game-player-black').get_attribute('class').endswith('game-player-winner')
        assert page.locator('.game-list-card[data-result="1/2-1/2"] .game-player-winner').count()==0
        panel=page.locator('[data-games-filters]')
        assert panel.evaluate('(el)=>el.open')==(width>700)
        if width<=700:panel.locator('summary').click()
        expect(page.locator('select[name=white_player]')).to_be_visible()
        assert_fits_phone(page)
        if width<=700:panel.locator('summary').click()
        card=page.locator(f'.game-list-card[data-game-id="{games[0]}"]');card.scroll_into_view_if_needed()
        expect(card.locator('.game-player-white .game-team-venue')).to_have_text('(home)')
        expect(card.locator('.game-player-black .game-team-venue')).to_have_text('(away)')
        reversed_card=page.locator(f'.game-list-card[data-game-id="{games[1]}"]')
        expect(reversed_card.locator('.game-player-white .game-team-venue')).to_have_text('(away)')
        expect(reversed_card.locator('.game-player-black .game-team-venue')).to_have_text('(home)')
        assert page.locator('.game-team-venue').count()==8
        for selector in ['.game-player-identity strong','.game-player-identity small','.game-result-caption','.game-date time','.game-round-link']:
            box=card.locator(selector).first.bounding_box()
            href=page.evaluate('([x,y])=>document.elementFromPoint(x,y).closest("a")?.getAttribute("href")',[box['x']+box['width']/2,box['y']+box['height']/2])
            assert href==(f'/matches/{match}' if selector=='.game-round-link' else f'/games/{games[0]}')
        if width>700:
            white=card.locator('.game-player-white').bounding_box();score=card.locator('.game-result-summary').bounding_box();black=card.locator('.game-player-black').bounding_box()
            assert white['x']+white['width']<=score['x']<black['x']
        bad=page.evaluate(CONTRAST);assert not bad,bad
        page.mouse.move(0,0);assert not page.evaluate(CONTRAST)
        screenshots=Path('/workspace/review-runtime/v61-screenshots');screenshots.mkdir(parents=True,exist_ok=True)
        page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(screenshots/f'games-{width}-{theme}.png'))
        card.locator('.game-round-link').click();page.wait_for_url(f'**/matches/{match}')
        page.goto('http://liga.test/games');card=page.locator(f'.game-list-card[data-game-id="{games[0]}"]')
        card.locator('.game-card-link').click(position={'x':8,'y':8});page.wait_for_url(f'**/games/{games[0]}')
        page.goto('http://liga.test/games?status=finished&sort=soonest')
        page.locator('.games-page-numbers a').filter(has_text='2').click();page.wait_for_url('**/games?**page=2')
        assert 'status=finished' in page.url and 'sort=soonest' in page.url
        expect(page.locator('.games-page-numbers [aria-current=page]')).to_have_text('2')
        page.goto('http://liga.test/games')
        if width<=700:page.locator('[data-games-filters] summary').click()
        page.locator('select[name=white_player]').select_option(str(rosters[0][0]))
        page.locator('.directory-filters button[type=submit]').click();page.wait_for_url('**/games?**')
        assert f'white_player={rosters[0][0]}' in page.url
        assert page.locator('.game-player-white .game-player-identity strong').all_text_contents()==['Alexandra Long Player Name With Many Words']*25
        page.goto('http://liga.test/games')
        page.locator('#language-toggle').click();page.locator('button[data-language="pt-PT"]').click()
        if width<=700:expect(page.locator('.games-filter-panel summary')).to_contain_text('Filtros')
        expect(page.locator('.game-list-card[data-result="1-0"] .game-result-caption').first).to_have_text('Brancas vencem')
        expect(page.locator('.game-list-card[data-result="0-1"] .game-result-caption')).to_have_text('Pretas vencem')
        card=page.locator(f'.game-list-card[data-game-id="{games[0]}"]')
        expect(card.locator('.game-player-white .game-team-venue')).to_have_text('(casa)')
        expect(card.locator('.game-player-black .game-team-venue')).to_have_text('(fora)')
        assert not errors,errors
    finally:context.close()
