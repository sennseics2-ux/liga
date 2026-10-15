"""Standings retains grey accents on the shared blue dark-mode surfaces."""
import os
from urllib.parse import urlsplit
import pytest
from playwright.sync_api import expect
import database as store
from test_league import client
from test_v31_manager_and_lineup_privacy import arranged_match
from test_member_journey import chromium,assert_fits_phone
from test_v32_dark_mode import CONTRAST
from test_seasons_neutral_theme import assert_grey

pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Enable Chromium checks.')


@pytest.mark.parametrize('width,theme',[(320,'light'),(320,'dark'),(1440,'light'),(1440,'dark')])
def test_standings_grey_palette_retains_banner_and_round_filter(chromium,client,width,theme):
    admin,season,_,match,teams,_,_=arranged_match()
    with store.transaction() as db:
        db.execute("UPDATE team_matches SET scheduled_at='2026-06-01T12:00:00+00:00' WHERE id=?",(match,))
        games=[row[0] for row in db.execute('SELECT game_id FROM match_games WHERE match_id=? ORDER BY board',(match,))]
    for game,result in zip(games,['1-0','0-1','1/2-1/2','1-0']):
        store.update_game_result(game,result,actor_id=admin,reason='Completed match')
    context=chromium.new_context(viewport={'width':width,'height':1000},color_scheme=theme)
    context.add_init_script("localStorage.setItem('clubdraft.language','en')")
    def local_application(route):
        url=urlsplit(route.request.url)
        if url.netloc!='liga.test':route.abort();return
        response=client.get(url.path+('?' + url.query if url.query else ''))
        route.fulfill(status=response.status_code,body=response.content,headers={'content-type':response.headers.get('content-type','text/plain')})
    context.route('**/*',local_application)
    page=context.new_page()
    try:
        page.goto('http://liga.test/teams')
        shared_banner=page.locator('.page-banner').evaluate('(el)=>({bg:getComputedStyle(el).backgroundColor,color:getComputedStyle(el).color})')
        page.goto(f'http://liga.test/standings?season={season}')
        banner=page.locator('.page-banner').evaluate('(el)=>({bg:getComputedStyle(el).backgroundColor,color:getComputedStyle(el).color})')
        assert banner==shared_banner
        for selector in ['.standings-table .score']:
            assert_grey(page.locator(selector).first,'backgroundColor')
        if theme=='dark':
            for selector,expected_background in [('body','rgb(16, 21, 29)'),('.table-scroll','rgb(32, 44, 59)'),('.standings-table th','rgb(44, 60, 80)'),('.tiny-avatar','rgb(44, 60, 80)'),('.season-picker select','rgb(32, 44, 59)')]:
                assert page.locator(selector).first.evaluate('(el)=>getComputedStyle(el).backgroundColor')==expected_background
        else:
            for selector in ['.season-picker','.season-picker select','.standings-table th','.tiny-avatar']:
                assert_grey(page.locator(selector).first,'backgroundColor')
        expected='rgb(44, 60, 80)' if theme=='dark' else 'rgb(237, 237, 237)'
        assert page.locator('.season-picker').evaluate('(el)=>getComputedStyle(el).backgroundColor')==expected
        expect(page.locator('.standings-table .score')).to_have_text(['3','0'])
        assert_fits_phone(page)
        assert page.evaluate(CONTRAST.replace('document.body,NodeFilter','document.querySelector("main"),NodeFilter'))==[]
        page.locator('#standings-round').focus();assert_grey(page.locator('#standings-round'),'outlineColor')
        page.locator('#standings-round').select_option('1')
        page.wait_for_url('**/standings?season=*&round=1')
        expect(page.locator('.standings-round-note')).to_contain_text('Includes results from rounds 1–1.')
        expect(page.locator('.standings-table .score')).to_have_text(['3','0'])
        page.locator(f'.standings-table a[href="/teams/{teams[0]}"]').click()
        page.wait_for_url(f'**/teams/{teams[0]}')
    finally:context.close()
