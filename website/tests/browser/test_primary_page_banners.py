"""Primary page banners stay consistent without clipping translated mobile text."""
import os
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from test_league import client, seed_admin, login_admin
from test_member_journey import chromium
from test_v32_dark_mode import CONTRAST
import database as store
import league_seasons as seasons

pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Enable Chromium checks.')
CASES=[(320,'light','en'),(320,'dark','pt-PT'),(390,'dark','en'),(390,'light','pt-PT'),
       (768,'light','en'),(768,'dark','pt-PT'),(1440,'light','en'),(1440,'dark','pt-PT')]


@pytest.mark.parametrize('width,theme,language',CASES)
def test_compact_primary_banners(chromium,client,width,theme,language):
    seed_admin()
    with store.read_db() as db:admin=db.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
    year=store.now_utc().year
    season=seasons.save_season(year,f'{year}-01-01',f'{year+1}-12-31',2,admin)
    login_admin(client)
    context=chromium.new_context(viewport={'width':width,'height':1000},color_scheme=theme)
    context.add_init_script(f"localStorage.setItem('clubdraft.language','{language}')")
    def application(route):
        url=urlsplit(route.request.url)
        if url.netloc!='liga.test':route.abort();return
        response=client.get(url.path+('?' + url.query if url.query else ''))
        route.fulfill(status=response.status_code,body=response.content,
                      headers={'content-type':response.headers.get('content-type','text/plain')})
    context.route('**/*',application)
    page=context.new_page()
    reference=None
    try:
        for path in ['/teams','/players',f'/seasons?season={season}','/games','/standings','/admin']:
            page.goto('http://liga.test'+path)
            banner=page.locator('.page-banner.section-banner')
            assert banner.count()==1,path
            assert banner.locator('.eyebrow,.competition-eyebrow').count()==0
            style=banner.evaluate('''el=>{
                const s=getComputedStyle(el),h=getComputedStyle(el.querySelector('h1'));
                return {height:el.getBoundingClientRect().height,paddingTop:s.paddingTop,paddingBottom:s.paddingBottom,
                    background:s.backgroundColor,color:h.color,fontSize:h.fontSize,fontFamily:h.fontFamily,
                    lineHeight:h.lineHeight,letterSpacing:h.letterSpacing,border:s.borderBottom};
            }''')
            if reference is None:reference=style
            assert style==reference,(path,style,reference)
            assert style['height']==(200 if width<=640 else 176)
            box=banner.bounding_box()
            for item in banner.locator('h1,p,.competition-status').all():
                bounds=item.bounding_box()
                assert bounds['y']>=box['y']+19,(path,bounds,box)
                assert bounds['y']+bounds['height']<=box['y']+box['height']-19,(path,bounds,box)
                assert bounds['x']>=box['x'] and bounds['x']+bounds['width']<=box['x']+box['width'],path
            description=banner.locator('p').first
            assert description.evaluate('(el)=>getComputedStyle(el).fontSize')=='14px'
            assert description.evaluate('(el)=>getComputedStyle(el).color')==('rgb(203, 216, 233)' if theme=='dark' else 'rgb(210, 210, 210)')
            assert not page.evaluate(CONTRAST.replace('document.body,NodeFilter','document.querySelector(".section-banner"),NodeFilter')),path
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),path
            if path=='/admin' and width==320:
                directory=Path('/workspace/review-runtime/v148-screenshots');directory.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(directory/f'admin-{theme}-{language}.png'))
    finally:context.close()
