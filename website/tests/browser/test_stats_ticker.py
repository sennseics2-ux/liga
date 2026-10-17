"""Real animation geometry, pointer/keyboard pause, and reduced-motion layouts."""
import os
from urllib.parse import urlsplit
import pytest
from playwright.sync_api import expect
from test_league import client
from test_member_journey import chromium

pytestmark = pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS') != '1', reason='Enable Chromium checks.')
LAYOUTS = [(320,'light'), (390,'dark'), (768,'light'), (1440,'light'), (1440,'dark')]


def open_home(chromium, client, width, theme, motion='no-preference'):
    context = chromium.new_context(viewport={'width':width,'height':1000}, color_scheme=theme, reduced_motion=motion)
    context.add_init_script("localStorage.setItem('clubdraft.language','en')")
    def application(route):
        address = urlsplit(route.request.url)
        if address.netloc != 'liga.test':
            route.abort(); return
        response = client.get(address.path + ('?' + address.query if address.query else ''))
        route.fulfill(status=response.status_code, body=response.content,
                      headers={'content-type':response.headers.get('content-type','text/plain')})
    context.route('**/*', application)
    page = context.new_page()
    page.goto('http://liga.test/')
    page.mouse.move(0,0)
    return context, page


def position(track):
    return track.evaluate('(el)=>new DOMMatrixReadOnly(getComputedStyle(el).transform).m41')


@pytest.mark.parametrize('width,theme',LAYOUTS)
def test_continuous_ticker_and_input_pause(chromium,client,width,theme):
    context,page = open_home(chromium,client,width,theme)
    try:
        viewport = page.get_by_role('region',name='League statistics')
        track = page.locator('.stats-ticker-track')
        groups = page.locator('.stats-ticker-group')
        expect(groups).to_have_count(2)
        assert groups.nth(1).get_attribute('aria-hidden') == 'true'
        assert groups.nth(1).get_attribute('inert') is not None
        expect(viewport.get_by_role('listitem')).to_have_count(4)
        expect(viewport.get_by_role('button')).to_have_count(0)
        assert groups.nth(0).inner_html() == groups.nth(1).inner_html()
        expect(groups.first.locator('.stats-ticker-label')).to_have_text(['TEAMS','PLAYERS','GAMES PLAYED','POSSIBLE STRATEGIES'])
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')

        viewport.scroll_into_view_if_needed()
        viewport.hover()
        page.wait_for_function("getComputedStyle(document.querySelector('.stats-ticker-track')).animationPlayState==='paused'")
        track.evaluate("(el)=>el.getAnimations()[0].ready")
        before = position(track)
        page.wait_for_timeout(150)
        assert abs(position(track)-before) < .1
        page.mouse.move(0,0)
        page.wait_for_function("getComputedStyle(document.querySelector('.stats-ticker-track')).animationPlayState==='running'")
        page.wait_for_function("(before)=>Math.abs(new DOMMatrixReadOnly(getComputedStyle(document.querySelector('.stats-ticker-track')).transform).m41-before)>.5",arg=before)

        page.locator('.role-secondary-link[href="/players"]').focus()
        page.keyboard.press('Tab')
        expect(viewport).to_be_focused()
        assert track.evaluate('(el)=>getComputedStyle(el).animationPlayState') == 'paused'
        track.evaluate("(el)=>el.getAnimations()[0].ready")
        before = position(track)
        page.wait_for_timeout(150)
        assert abs(position(track)-before) < .1
        page.keyboard.press('Shift+Tab')
        expect(page.locator('.role-secondary-link[href="/players"]')).to_be_focused()
        assert track.evaluate('(el)=>getComputedStyle(el).animationPlayState') == 'running'
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        # Check the actual positions at quarter-cycle intervals and either side
        # of the wrap, as well as coverage at the widest viewport.
        result = track.evaluate('''el=>{
            const animation=el.getAnimations()[0]; animation.pause();
            const [a,b]=el.children;
            const groupWidth=a.getBoundingClientRect().width;
            const viewportWidth=el.parentElement.clientWidth;
            const duration=animation.effect.getTiming().duration;
            const easing=animation.effect.getTiming().easing;
            const positions=[0,7000,14000,21000].map(time=>{
                animation.currentTime=time;
                return new DOMMatrixReadOnly(getComputedStyle(el).transform).m41;
            });
            animation.currentTime=27999;
            const before=b.firstElementChild.getBoundingClientRect().left;
            animation.currentTime=28001;
            const after=a.firstElementChild.getBoundingClientRect().left;
            animation.currentTime=1000; animation.play();
            return {groupWidth,viewportWidth,duration,easing,positions,before,after,
                secondWidth:b.getBoundingClientRect().width,trackWidth:el.getBoundingClientRect().width};
        }''')
        assert result['groupWidth'] >= result['viewportWidth']
        assert abs(result['groupWidth']-result['secondWidth']) < .1
        assert abs(result['trackWidth']-2*result['groupWidth']) < .1
        assert result['duration'] == 28000 and result['easing'] == 'linear'
        for index,value in enumerate(result['positions']):
            assert abs(value+result['groupWidth']*index/4) < .1
        assert abs(result['before']-result['after']) < .2

    finally:
        context.close()


@pytest.mark.parametrize('width,theme',LAYOUTS)
def test_reduced_motion_static_grid(chromium,client,width,theme):
    context,page = open_home(chromium,client,width,theme,'reduce')
    try:
        track = page.locator('.stats-ticker-track')
        expect(page.locator('.stats-ticker-group[aria-hidden="true"]')).to_be_hidden()
        assert track.evaluate('(el)=>el.getAnimations().length') == 0
        assert track.evaluate('(el)=>getComputedStyle(el).transform') == 'none'
        metrics = page.locator('.stats-ticker-group').first.locator('.stats-ticker-metric')
        expect(metrics).to_have_count(4)
        boxes = [metric.bounding_box() for metric in metrics.all()]
        if width < 800:
            assert abs(boxes[0]['y']-boxes[1]['y']) < 1
            assert boxes[2]['y'] >= boxes[0]['y']+boxes[0]['height']
        else:
            assert max(box['y'] for box in boxes)-min(box['y'] for box in boxes) < 1
        for metric in metrics.all():
            assert metric.evaluate('(el)=>el.scrollWidth<=el.clientWidth')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.emulate_media(reduced_motion='no-preference')
        page.wait_for_function("document.querySelector('.stats-ticker-track').getAnimations().length===1")
        page.emulate_media(reduced_motion='reduce')
        page.wait_for_function("document.querySelector('.stats-ticker-track').getAnimations().length===0")
    finally:
        context.close()
