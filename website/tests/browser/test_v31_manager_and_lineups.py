"""Accessible admin actions and visible pre-match privacy on narrow screens."""
import os
import tempfile
from pathlib import Path
import pytest
from playwright.sync_api import expect
from test_member_journey import chromium,league_server,assert_fits_phone,PASSWORD
from test_v31_manager_and_lineup_privacy import arranged_match

pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Set RUN_BROWSER_TESTS=1 to require Chromium journeys.')


def sign_in(page,base,username,password=PASSWORD):
    page.context.clear_cookies()
    page.goto(base+'/login');page.locator('input[name=username]').fill(username)
    page.locator('input[name=password]').fill(password);page.locator('form.stack-form button[type=submit]').click()
    page.wait_for_url('**/admin' if username=='BrowserAdmin' else '**/users/'+username+'/manager')


@pytest.mark.parametrize('width',[320,390,1440])
def test_admin_cancel_and_reinvite_and_private_lineups(chromium,league_server,width):
    league=league_server;_,_,_,match,_,_,_=arranged_match()
    with league.store.read_db() as db:
        team=db.execute("SELECT id FROM teams WHERE name='Teams'").fetchone()[0]
        manager=db.execute("SELECT id FROM users WHERE username='BrowserMember'").fetchone()[0]
    context=chromium.new_context(viewport={'width':width,'height':900})
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(league.base+'/') else route.abort())
    page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    directory=(Path('/workspace/review-runtime') if Path('/workspace/review-runtime').exists() else Path(tempfile.gettempdir())) / 'v31-screenshots';directory.mkdir(parents=True,exist_ok=True)
    try:
        page.on('dialog',lambda dialog:dialog.accept())
        sign_in(page,league.base,'BrowserAdmin');page.goto(league.base+'/admin/teams')
        remove=page.locator(f'form[action="/admin/teams/{team}/remove-manager"] button')
        expect(remove).to_have_attribute('aria-label','Remover capitão');expect(remove.locator('svg')).to_have_count(1)
        assert remove.evaluate('(el)=>getComputedStyle(el).color')=='rgb(180, 35, 24)'
        assert_fits_phone(page);page.screenshot(path=str(directory/f'admin-teams-{width}.png'),full_page=True)
        remove.click();page.wait_for_url(league.base+'/admin/teams')
        invite=page.locator(f'form[action="/admin/teams/{team}/manager"]')
        invite.locator('select').select_option(str(manager));invite.locator('button').click()
        pending=page.locator('.team-management-table .team-invitation-status').filter(has_text='BrowserMember')
        expect(pending.get_by_role('button',name='Cancelar convite')).to_be_visible()
        assert_fits_phone(page);page.screenshot(path=str(directory/f'invitation-{width}.png'),full_page=True)
        pending.get_by_role('button',name='Cancelar convite').click()
        expect(page.locator(f'form[action="/admin/teams/{team}/manager"]')).to_be_visible()
        page.goto(league.base+f'/matches/{match}')
        expect(page.locator('.lineup-private')).to_have_count(2)
        expect(page.locator('.match-lineup-player')).to_have_count(0)
        expect(page.locator('.match-board-row')).to_have_count(4)
        assert_fits_phone(page);page.screenshot(path=str(directory/f'private-match-{width}.png'),full_page=True)
        sign_in(page,league.base,'manager_home','PlayerPassword123!');page.goto(league.base+f'/matches/{match}')
        expect(page.locator('.lineup-private')).to_have_count(1)
        expect(page.locator('.match-lineup-player')).to_have_count(4)
        assert 'away Player 1' not in page.content()
        assert_fits_phone(page);page.screenshot(path=str(directory/f'own-lineup-{width}.png'),full_page=True)
        page.evaluate("localStorage.setItem('clubdraft.language','en')");page.reload()
        expect(page.locator('.lineup-private p').first).to_have_text('This lineup is private until the match starts.')
        assert not errors,errors
    finally:context.close()
