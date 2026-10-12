"""Real mouse gestures, per-position state, orientation and page lifecycle."""
import os
import pytest
from playwright.sync_api import expect
from test_member_journey import chromium, league_server, assert_fits_phone

pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Chromium required')


def center(page,square):
    box=page.locator(f'[data-board] .replay-square[data-square="{square}"]').bounding_box()
    return box['x']+box['width']/2,box['y']+box['height']/2


def arrow(page,start,end):
    page.mouse.move(*center(page,start));page.mouse.down(button='right')
    page.mouse.move(*center(page,end),steps=8)
    expect(page.locator('.replay-annotations [data-preview=true]')).to_have_count(1)
    page.mouse.up(button='right')
    expect(page.locator('.replay-annotations [data-preview=true]')).to_have_count(0)


def circle(page,square):
    page.locator(f'[data-board] .replay-square[data-square="{square}"]').click(button='right')


@pytest.mark.parametrize('width,height,theme',[(1280,720,'light'),(1440,900,'dark')])
def test_annotations_gestures_moves_flip_and_navigation(chromium,league_server,width,height,theme):
    league=league_server
    context=chromium.new_context(viewport={'width':width,'height':height},color_scheme=theme)
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(league.base+'/') else route.abort())
    page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto(f'{league.base}/games/{league.game}')
        expect(page.locator('[data-board] img')).to_have_count(32)
        page.evaluate("document.addEventListener('contextmenu',e=>window.contextSuppressed=e.defaultPrevented)")
        circle(page,'e4')
        expect(page.locator('[data-circle=e4]')).to_have_count(1)
        assert page.evaluate('window.contextSuppressed') is True
        circle(page,'e4');expect(page.locator('[data-circle=e4]')).to_have_count(0)
        circle(page,'e4')
        for start,end in [('e2','e4'),('a1','h1'),('c1','h6')]:
            arrow(page,start,end)
            mark=page.locator(f'.replay-annotation-arrow[data-from={start}][data-to={end}]')
            expect(mark).to_have_attribute('data-shape','straight')
            assert ' L ' in mark.get_attribute('d')
        arrow(page,'b1','c3')
        curved=page.locator('.replay-annotation-arrow[data-from=b1][data-to=c3]')
        expect(curved).to_have_attribute('data-shape','curved')
        assert ' Q ' in curved.get_attribute('d')
        arrow(page,'b1','c3');expect(curved).to_have_count(0)
        arrow(page,'b1','c3')
        expect(page.locator('.replay-annotation-arrow')).to_have_count(4)
        page.locator('[data-action=next]').click()
        expect(page.locator('.replay-annotation-circle,.replay-annotation-arrow')).to_have_count(0)
        circle(page,'d5')
        page.keyboard.press('ArrowRight')
        expect(page.locator('.replay-annotation-circle,.replay-annotation-arrow')).to_have_count(0)
        page.keyboard.press('ArrowLeft')
        expect(page.locator('[data-circle=d5]')).to_have_count(1)
        expect(page.locator('[data-circle=e4]')).to_have_count(0)
        page.locator('[data-action=first]').click()
        expect(page.locator('[data-circle=e4]')).to_have_count(1)
        expect(page.locator('.replay-annotation-arrow')).to_have_count(4)
        # Clearing one position must preserve annotations on other positions.
        page.locator('[data-board] .replay-square[data-square=h8]').click()
        expect(page.locator('.replay-annotation-circle,.replay-annotation-arrow')).to_have_count(0)
        page.locator('[data-action=next]').click()
        expect(page.locator('[data-circle=d5]')).to_have_count(1)
        page.locator('[data-action=first]').click()
        expect(page.locator('.replay-annotation-circle,.replay-annotation-arrow')).to_have_count(0)
        circle(page,'e4')
        for start,end in [('e2','e4'),('a1','h1'),('c1','h6'),('b1','c3')]:
            arrow(page,start,end)
        page.locator('[data-action=flip]').click()
        expect(page.locator('[data-circle=e4]')).to_have_attribute('cx','3.5')
        expect(page.locator('[data-circle=e4]')).to_have_attribute('cy','3.5')
        arrow(page,'b1','c3');expect(curved).to_have_count(0)
        circle(page,'e4');expect(page.locator('[data-circle=e4]')).to_have_count(0)
        circle(page,'e4')
        page.locator('#account-toggle').click()
        page.locator('[data-piece-style]').select_option('cburnett',force=True)
        page.locator('#account-toggle').click()
        page.evaluate("window.LigaI18n.setLanguage('en')")
        expect(page.locator('[data-circle=e4]')).to_have_count(1)
        expect(page.locator('.replay-annotation-arrow')).to_have_count(3)
        # Outside release and Escape cancel rather than commit a mark.
        page.mouse.move(*center(page,'a8'));page.mouse.down(button='right')
        page.mouse.move(2,2);page.mouse.up(button='right')
        expect(page.locator('.replay-annotation-arrow')).to_have_count(3)
        page.mouse.move(*center(page,'a8'));page.mouse.down(button='right')
        page.mouse.move(*center(page,'b6'));page.keyboard.press('Escape');page.mouse.up(button='right')
        expect(page.locator('.replay-annotation-arrow')).to_have_count(3)
        # A position change during a drag must not mark the new position.
        page.mouse.move(*center(page,'a8'));page.mouse.down(button='right')
        page.mouse.move(*center(page,'b6'));page.keyboard.press('ArrowRight');page.mouse.up(button='right')
        expect(page.locator('.replay-annotation-arrow')).to_have_count(0)
        expect(page.locator('[data-circle=d5]')).to_have_count(1)
        page.locator('[data-action=first]').click()
        assert_fits_phone(page)
        assert page.evaluate('document.documentElement.scrollHeight')<=height+2
        page.screenshot(path=f'/workspace/review-runtime/v52-annotations-{theme}.png',full_page=True)
        # Clear even when this exact document remains in the browser back cache.
        page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide',{persisted:true}));window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))")
        expect(page.locator('.replay-annotation-circle,.replay-annotation-arrow')).to_have_count(0)
        circle(page,'e4');page.goto(league.base+'/teams');page.go_back()
        expect(page.locator('[data-board] img')).to_have_count(32)
        expect(page.locator('.replay-annotation-circle,.replay-annotation-arrow')).to_have_count(0)
        circle(page,'e4');page.reload()
        expect(page.locator('.replay-annotation-circle,.replay-annotation-arrow')).to_have_count(0)
        assert not errors,errors
    finally:context.close()


def test_touch_board_keeps_normal_pointer_behavior(chromium,league_server):
    context=chromium.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(league_server.base+'/') else route.abort())
    page=context.new_page()
    try:
        page.goto(f'{league_server.base}/games/{league_server.game}')
        expect(page.locator('[data-board] img')).to_have_count(32)
        page.locator('[data-board] .replay-square[data-square=e4]').tap()
        circle(page,'e4')
        expect(page.locator('.replay-annotation-circle,.replay-annotation-arrow')).to_have_count(0)
        assert_fits_phone(page)
    finally:context.close()
