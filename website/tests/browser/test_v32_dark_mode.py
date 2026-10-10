"""Site-wide theme persistence, responsive layouts and measured text contrast."""
import os
import json
import tempfile
from pathlib import Path
import pytest
from playwright.sync_api import expect
from test_member_journey import chromium,league_server,assert_fits_phone,PASSWORD
from test_v31_manager_and_lineup_privacy import arranged_match
from test_v29_admin_and_results import seed_player_results

pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Set RUN_BROWSER_TESTS=1 to require Chromium journeys.')

CONTRAST=r'''() => {
  const rgb=s=>{const v=s.match(/[\d.]+/g);return v ? v.map(Number) : [0,0,0,0]};
  const lum=c=>{const p=c.slice(0,3).map(x=>{x/=255;return x<=.04045?x/12.92:Math.pow((x+.055)/1.055,2.4)});return .2126*p[0]+.7152*p[1]+.0722*p[2]};
  const background=el=>{
    let out=[0,0,0],remaining=1;
    for(let at=el;at && remaining>0;at=at.parentElement){
      const st=getComputedStyle(at);if(st.backgroundImage!=='none')return null;
      const c=rgb(st.backgroundColor),alpha=c.length>3?c[3]:1;
      out=out.map((x,i)=>x+c[i]*alpha*remaining);remaining*=1-alpha;
    }
    return out.map(x=>x+255*remaining);
  };
  const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT),bad=[];
  while(walker.nextNode()){
    const node=walker.currentNode,el=node.parentElement,text=node.textContent.trim();
    if(!el||!text||el.closest('script,style,svg,[aria-hidden="true"],:disabled,[aria-disabled="true"],.chess-board'))continue;
    const range=document.createRange();range.selectNodeContents(node);if(!range.getBoundingClientRect().height)continue;
    const st=getComputedStyle(el);if(st.visibility!=='visible'||Number(st.opacity)===0)continue;
    const bg=background(el);if(!bg)continue;
    const fg=rgb(st.color);if((fg[3]??1)<1)continue;
    const a=lum(fg),b=lum(bg),ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
    const size=parseFloat(st.fontSize),bold=Number(st.fontWeight)>=700;
    const minimum=size>=24||(bold&&size>=18.66)?3:4.5;
    if(ratio+0.02<minimum)bad.push({text:text.slice(0,80),selector:el.tagName+'.'+el.className,ratio:+ratio.toFixed(2),minimum,fg:st.color,bg});
  }
  return bad;
}'''


def sign_in(page,base,username):
    page.context.clear_cookies();page.goto(base+'/login')
    page.locator('input[name=username]').fill(username);page.locator('input[name=password]').fill(PASSWORD)
    page.locator('form.stack-form button[type=submit]').click()
    page.wait_for_url('**/admin' if username=='BrowserAdmin' else '**/users/BrowserMember/manager')


@pytest.mark.parametrize('width',[320,390,1440])
def test_theme_across_public_member_admin_and_replay_pages(chromium,league_server,width):
    league=league_server;_,_,_,match,teams,_,_=arranged_match();seed_player_results()
    context=chromium.new_context(viewport={'width':width,'height':900},color_scheme='dark')
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(league.base+'/') else route.abort())
    page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    directory=(Path('/workspace/review-runtime') if Path('/workspace/review-runtime').exists() else Path(tempfile.gettempdir())) / 'v32-screenshots';directory.mkdir(parents=True,exist_ok=True)
    try:
        page.goto(league.base+'/');expect(page.locator('html')).to_have_attribute('data-theme','dark')
        expect(page.locator('#theme-toggle')).to_have_attribute('aria-pressed','true')
        page.emulate_media(color_scheme='light');expect(page.locator('html')).to_have_attribute('data-theme','light')
        page.emulate_media(color_scheme='dark');expect(page.locator('html')).to_have_attribute('data-theme','dark')
        page.locator('#theme-toggle').click();expect(page.locator('html')).to_have_attribute('data-theme','light')
        page.goto(league.base+'/teams');expect(page.locator('html')).to_have_attribute('data-theme','light')
        page.locator('#theme-toggle').focus();page.keyboard.press('Enter')
        expect(page.locator('html')).to_have_attribute('data-theme','dark')
        assert page.evaluate("localStorage.getItem('clubdraft.theme')")=='dark'
        failures=[]
        def review(path):
            page.goto(league.base+path);expect(page.locator('html')).to_have_attribute('data-theme','dark')
            assert_fits_phone(page)
            failures.extend({'path':path,**item} for item in page.evaluate(CONTRAST))
            assert page.locator('body').evaluate('(el)=>getComputedStyle(el).backgroundColor')=='rgb(16, 21, 29)'
        for path in ['/','/teams','/players','/standings','/seasons','/games','/forgot-password','/register','/login',
                     '/users/WhiteResults',f'/teams/{teams[0]}',f'/matches/{match}',f'/auctions/{league.auction}']:
            review(path)
            if path in ['/','/users/WhiteResults','/forgot-password','/seasons',f'/teams/{teams[0]}']:
                name={'/':'home','/users/WhiteResults':'player','/forgot-password':'recovery','/seasons':'results'}.get(path,'team')
                page.screenshot(path=str(directory/f'dark-{name}-{width}.png'),full_page=True)
        sign_in(page,league.base,'BrowserMember')
        for path in ['/account/settings','/account/security','/users/BrowserMember/manager',f'/games/{league.game}']:
            review(path)
        expect(page.locator('[data-chess-replay]')).to_be_visible()
        expect(page.locator('[data-board] [role=gridcell]')).to_have_count(64)
        page.screenshot(path=str(directory/f'dark-replay-{width}.png'),full_page=True)
        sign_in(page,league.base,'BrowserAdmin')
        for path in ['/admin','/admin/teams','/admin/roles','/admin/players','/admin/games','/admin/seasons','/admin/accounts']:
            review(path)
            if path=='/admin':page.screenshot(path=str(directory/f'dark-admin-{width}.png'),full_page=True)
        (directory/f'contrast-{width}.json').write_text(json.dumps(failures,indent=2))
        assert not failures,failures[:40]
        page.evaluate("localStorage.setItem('clubdraft.language','en')");page.reload()
        expect(page.locator('#theme-toggle')).to_have_attribute('aria-label','Dark mode')
        page.locator('#theme-toggle').click();page.reload()
        expect(page.locator('html')).to_have_attribute('data-theme','light')
        expect(page.locator('#theme-toggle')).to_have_attribute('aria-pressed','false')
        assert not errors,errors
    finally:context.close()


def test_storage_unavailable_still_allows_theme_switch(chromium,league_server):
    context=chromium.new_context(color_scheme='light')
    context.add_init_script("Object.defineProperty(window, 'localStorage', {get(){throw new Error('Storage disabled')}})")
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(league_server.base+'/') else route.abort())
    page=context.new_page();page.goto(league_server.base+'/login')
    expect(page.locator('html')).to_have_attribute('data-theme','light')
    page.locator('#theme-toggle').click();expect(page.locator('html')).to_have_attribute('data-theme','dark')
    context.close()
