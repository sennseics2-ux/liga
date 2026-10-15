"""Neutral Seasons panels and settings controls retain contrast and navigation."""
import os
import pytest
from urllib.parse import urlsplit
from playwright.sync_api import expect
import database as store
from test_league import client,login_admin
from test_v31_manager_and_lineup_privacy import arranged_match
from test_member_journey import chromium,assert_fits_phone
from test_v32_dark_mode import CONTRAST

pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Enable Chromium checks.')


def assert_grey(locator,prop):
    channels=locator.evaluate('(el,prop)=>getComputedStyle(el)[prop].match(/[\\d.]+/g).slice(0,3).map(Number)',prop)
    assert max(channels)-min(channels)<=1,(prop,channels)


@pytest.mark.parametrize('width,theme',[(320,'light'),(320,'dark'),(1440,'light'),(1440,'dark')])
def test_seasons_grey_panels_and_settings_states(chromium,client,width,theme):
    admin,season,_,match,_,_,_=arranged_match()
    with store.transaction() as db:
        db.execute("UPDATE team_matches SET scheduled_at='2026-06-01T12:00:00+00:00' WHERE id=?",(match,))
        games=[row[0] for row in db.execute('SELECT game_id FROM match_games WHERE match_id=? ORDER BY board',(match,))]
    for game,result in zip(games,['1-0','0-1','1/2-1/2','1-0']):
        store.update_game_result(game,result,actor_id=admin,reason='Completed match')
    login_admin(client)
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
        page.goto(f'http://liga.test/seasons?season={season}')
        expect(page.locator('body')).to_have_class('seasons-page')
        banner=page.locator('.seasons-banner').evaluate('(el)=>({bg:getComputedStyle(el).backgroundColor,color:getComputedStyle(el).color})')
        page.goto('http://liga.test/teams')
        shared_banner=page.locator('.page-banner').evaluate('(el)=>({bg:getComputedStyle(el).backgroundColor,color:getComputedStyle(el).color})')
        assert banner==shared_banner,(banner,shared_banner)
        page.goto(f'http://liga.test/seasons?season={season}')
        for selector in ['.season-picker','.season-schedule','.schedule-round:not(.schedule-round-complete)',
                         '.schedule-round-complete','.round-section','.round-number','.fixture-card','.fixture-bottom','.season-picker select']:
            assert_grey(page.locator(selector).first,'backgroundColor')
        expected_picker='rgb(222, 222, 222)' if theme=='dark' else 'rgb(237, 237, 237)'
        assert page.locator('.season-picker').evaluate('(el)=>getComputedStyle(el).backgroundColor')==expected_picker
        pending=page.locator('.schedule-round:not(.schedule-round-complete)').first.evaluate(r'(el)=>parseInt(getComputedStyle(el).backgroundColor.match(/\d+/)[0])')
        done=page.locator('.schedule-round-complete').first.evaluate(r'(el)=>parseInt(getComputedStyle(el).backgroundColor.match(/\d+/)[0])')
        assert done>pending
        assert_fits_phone(page)
        issues=page.evaluate(CONTRAST.replace('document.body,NodeFilter','document.querySelector("main"),NodeFilter'))
        assert issues==[],issues
        page.locator('#season-select').focus()
        assert_grey(page.locator('#season-select'),'outlineColor')
        for path in [f'/seasons?season={season}','/']:
            page.goto('http://liga.test'+path)
            settings=page.locator('#account-toggle')
            for state in ['normal','hover','open','focus']:
                if state=='hover':settings.hover()
                if state=='open':settings.click();expect(settings).to_have_attribute('aria-expanded','true')
                if state=='focus':page.keyboard.press('Escape');settings.focus()
                for prop in ['backgroundColor','color','borderTopColor']:
                    assert_grey(settings,prop)
                if state=='focus':assert_grey(settings,'outlineColor')
        for game in games:store.update_game_result(game,'1/2-1/2',actor_id=admin,reason='Drawn match')
        page.goto(f'http://liga.test/seasons?season={season}')
        expect(page.locator('.fixture-team-draw')).to_have_count(2)
        assert_grey(page.locator('.fixture-team-draw').first,'backgroundColor')
        assert_grey(page.locator('.fixture-team-draw .fixture-score').first,'backgroundColor')
        page.locator('.schedule-round-complete').click();page.wait_for_url(f'**/matches/{match}')
    finally:context.close()
