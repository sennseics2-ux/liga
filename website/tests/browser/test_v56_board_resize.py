"""Desktop resizing stays square, preserves annotations and avoids horizontal overflow."""
import os
import pytest
from playwright.sync_api import expect
from test_member_journey import chromium,league_server,assert_fits_phone
from test_v52_replay_annotations import circle,arrow

pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Chromium required')


def test_resize_drag_keyboard_persistence_and_mobile(chromium,league_server):
    context=chromium.new_context(viewport={'width':1366,'height':768})
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(league_server.base+'/') else route.abort())
    page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto(f'{league_server.base}/games/{league_server.game}')
        expect(page.locator('[data-board] img')).to_have_count(32)
        handle=page.locator('[data-board-resize]');expect(handle).to_be_visible()
        circle(page,'e4');arrow(page,'b1','c3')
        before=page.locator('[data-board]').bounding_box()
        grip=handle.bounding_box()
        page.mouse.move(grip['x']+grip['width']/2,grip['y']+grip['height']/2)
        page.mouse.down();page.mouse.move(grip['x']+grip['width']/2+100,grip['y']+grip['height']/2+100,steps=8);page.mouse.up()
        after=page.locator('[data-board]').bounding_box()
        assert after['width']>=before['width']+95
        assert abs(after['width']-after['height'])<1
        assert abs(after['x']-before['x'])<2
        assert abs(after['y']-before['y'])<2
        expect(page.locator('[data-circle=e4]')).to_have_count(1)
        expect(page.locator('.replay-annotation-arrow[data-from=b1][data-to=c3]')).to_have_count(1)
        assert_fits_phone(page)
        handle.focus();page.keyboard.press('ArrowLeft')
        smaller=page.locator('[data-board]').bounding_box()['width']
        assert smaller<after['width']
        # The handle's arrows resize; they must not advance the game.
        expect(page.locator('[data-action=prev]')).to_be_disabled()
        handle.focus();page.keyboard.press('End');assert_fits_phone(page)
        handle.focus();page.keyboard.press('Home')
        expect(handle).to_have_attribute('aria-valuenow','320')
        page.reload();expect(page.locator('[data-board] img')).to_have_count(32)
        expect(handle).to_have_attribute('aria-valuenow','320')
        page.set_viewport_size({'width':390,'height':844})
        expect(handle).not_to_be_visible();assert_fits_phone(page)
        assert page.locator('[data-board]').bounding_box()['width']>=320
        page.set_viewport_size({'width':1366,'height':768})
        expect(handle).to_be_visible();expect(handle).to_have_attribute('aria-valuenow','320')
        assert not errors,errors
    finally:context.close()
