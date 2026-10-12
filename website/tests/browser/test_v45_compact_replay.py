"""Replay fits the viewport, notation scrolls, and appearance works for visitors."""
import os
import pytest
from playwright.sync_api import expect
from test_member_journey import chromium, league_server, assert_fits_phone
from test_v32_dark_mode import sign_in, CONTRAST

pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Chromium required')

@pytest.mark.parametrize('width,height',[(320,700),(390,844),(844,390),(1366,768)])
def test_compact_replay_and_appearance(chromium,league_server,width,height):
    league=league_server
    moves=' '.join(f'{i+1}. '+('Nf3 Nf6' if i%2==0 else 'Ng1 Ng8') for i in range(80))
    with league.store.transaction() as db:
        db.execute('UPDATE games SET pgn_text=? WHERE id=?',('[Result "*"]\n\n'+moves+' *',league.game))
    context=chromium.new_context(viewport={'width':width,'height':height},color_scheme='dark')
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(league.base+'/') else route.abort())
    page=context.new_page()
    try:
        page.goto(f'{league.base}/games/{league.game}')
        expect(page.locator('[data-board] img')).to_have_count(32)
        assert_fits_phone(page)
        assert page.locator('.replay-page-header a[href$="/pgn"]').count()==0
        assert page.locator('.replay-utilities a[href$="/pgn"]').count()==1
        tools=page.locator('.replay-utilities').bounding_box()
        download=page.locator('.replay-download').bounding_box()
        assert abs(download['y']-tools['y'])<=8
        board=page.locator('[data-board]').bounding_box()
        play=page.locator('[data-action=play]').bounding_box()
        if width<=900 and height<width:
            assert play['x']>board['x']+board['width']
        else:
            assert play['y']>board['y']+board['height']
        if width<=900:
            assert page.locator('.site-header').bounding_box()['height']<=64
            if height>=width:
                assert page.locator('[data-board]').bounding_box()['width']>=width-70
            else:
                assert page.locator('[data-board]').bounding_box()['height']>=height-190
            assert all(button.bounding_box()['height']>=44 for button in page.locator('.replay-controls button').all())
        with page.expect_download() as downloaded:
            page.locator('.replay-download').click()
        assert downloaded.value.suggested_filename.endswith('.pgn')
        assert downloaded.value.failure() is None
        page.screenshot(path=f'/workspace/review-runtime/v47-initial-{width}.png',full_page=True)
        assert page.locator('.replay-layout').bounding_box()['y']+page.locator('.replay-layout').bounding_box()['height']<=height+2, page.evaluate("() => Object.fromEntries(['.site-header','.replay-page-header','.game-matchup','.replay-board-panel','.replay-board-shell','.replay-controls','.replay-progress','.replay-utilities','.replay-sidebar'].map(s=>{const b=document.querySelector(s).getBoundingClientRect();return [s,{y:b.y,height:b.height}]}))")
        assert page.evaluate('document.documentElement.scrollHeight')<=height+2
        assert page.locator('[data-moves]').evaluate('(el)=>el.scrollHeight>el.clientHeight && getComputedStyle(el).overflowY==="scroll"')
        before=page.evaluate('window.scrollY')
        page.locator('[data-action=last]').click()
        assert page.locator('[data-moves]').evaluate('(el)=>el.scrollTop')>0
        assert page.evaluate('window.scrollY')==before
        assert page.locator('[data-chess-replay] [data-piece-style]').count()==0
        page.locator('#account-toggle').click()
        page.locator('[data-piece-style]').select_option('cburnett')
        page.locator('select[data-board-color]').select_option('blue')
        expect(page.locator('html')).to_have_attribute('data-board-color','blue')
        assert page.locator('.replay-square.light').first.evaluate('(el)=>getComputedStyle(el).backgroundColor')=='rgb(222, 227, 230)'
        page.reload()
        expect(page.locator('html')).to_have_attribute('data-board-color','blue')
        expect(page.locator('[data-board] img').first).to_have_attribute('src','/static/pieces/cburnett/bR.svg')
        page.locator('#account-toggle').click()
        assert not page.evaluate(CONTRAST)
        page.locator('#account-toggle').click()
        page.screenshot(path=f'/workspace/review-runtime/v47-replay-{width}.png',full_page=True)
        sign_in(page,league.base,'BrowserMember')
        page.locator('#account-toggle').click()
        page.locator('#account-menu a[href="/account/profile"]').hover()
        assert page.locator('#account-menu a[href="/account/profile"]').evaluate('(el)=>getComputedStyle(el).backgroundColor')=='rgb(33, 75, 52)'
        page.locator('#account-menu form button').hover()
        assert page.locator('#account-menu form button').evaluate('(el)=>getComputedStyle(el).backgroundColor')=='rgb(83, 43, 49)'
    finally:context.close()
