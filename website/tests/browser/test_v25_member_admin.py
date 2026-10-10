"""Real mobile registration, profile locking, recovery, and manager lineups."""
import os
import pytest
from test_member_journey import chromium,league_server,assert_fits_phone,PASSWORD
from test_v25_seasons import setup as seed_season
import account_service as accounts

pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Set RUN_BROWSER_TESTS=1 to require Chromium journeys.')


@pytest.mark.parametrize('width',[320,390])
def test_registration_settings_recovery_and_admin_lock(chromium,league_server,width):
    league=league_server
    context=chromium.new_context(viewport={'width':width,'height':850})
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(league.base+'/') else route.abort())
    page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto(league.base+'/register')
        assert 'Criar conta' in page.locator('form.stack-form button[type=submit]').inner_text()
        username=f'NewProfile{width}';email=f'profile{width}@example.com'
        page.locator('input[name=username]').fill(username)
        page.locator('input[name=email]').fill(email)
        page.locator('select[name=role]').select_option('manager')
        page.locator('input[name=password]').fill(PASSWORD)
        page.locator('form.stack-form button[type=submit]').click()
        page.wait_for_url(league.base+f'/users/{username}/manager')
        page.goto(league.base+'/account/settings')
        page.locator('input[name=name]').fill('Maria Silva')
        page.locator('input[name=country]').fill('Portugal')
        page.locator('input[name=fide_id]').fill('12345')
        assert not page.locator('input[name=fide_id]').evaluate('(el)=>el.checkValidity()')
        page.locator('input[name=fide_id]').fill('123456')
        page.locator('form[action="/account/settings"] button').click()
        page.wait_for_url(league.base+'/account/settings')
        assert page.locator('input[name=name]').input_value()=='Maria Silva'
        assert_fits_phone(page)
        with league.store.read_db() as db:
            uid=db.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone()[0]
        copied=context.cookies()[0]['value']
        page.locator('#account-toggle').click()
        page.locator('form[action="/logout"] button').click()
        page.wait_for_url(league.base+'/')
        result=context.request.get(league.base+'/account/settings',headers={'Cookie':'session='+copied,'Accept':'application/json'})
        assert result.status==401
        raw=accounts.issue_reset(username,email)
        page.goto(league.base+'/reset-password#token='+raw)
        page.wait_for_function("location.hash === ''")
        assert page.locator('input[name=token]').input_value()==raw
        page.locator('input[name=password]').fill('RecoveredPassword123!')
        page.locator('input[name=confirm_password]').fill('RecoveredPassword123!')
        page.locator('form.stack-form button').click()
        page.wait_for_url(league.base+'/login')
        page.locator('input[name=username]').fill('BrowserAdmin')
        page.locator('input[name=password]').fill(PASSWORD)
        page.locator('form.stack-form button[type=submit]').click()
        page.wait_for_url(league.base+'/admin')
        page.locator('[data-page-navigation]').select_option('/admin/accounts')
        page.wait_for_url(league.base+'/admin/accounts')
        form=page.locator(f'form[action="/admin/users/{uid}/profile"]')
        form.locator('input[name=fide_id_locked]').check()
        form.locator('button').click()
        assert_fits_phone(page)
        assert accounts.account(uid)['fide_id_locked']==1
        assert not errors,errors
    finally:
        context.close()


def test_manager_four_board_submission_on_mobile(chromium,league_server):
    league=league_server
    admin,season,rounds,match,teams,managers,rosters=seed_season()
    context=chromium.new_context(viewport={'width':320,'height':850})
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(league.base+'/') else route.abort())
    page=context.new_page()
    try:
        page.goto(league.base+'/login')
        page.locator('input[name=username]').fill('manager_home')
        page.locator('input[name=password]').fill('PlayerPassword123!')
        page.locator('form.stack-form button[type=submit]').click()
        page.wait_for_url(league.base+'/users/manager_home/manager')
        page.goto(league.base+f'/matches/{match}')
        for board,player in enumerate(rosters[0],1):
            page.locator(f'select[name=player_{board}]').select_option(str(player))
        page.locator(f'form[action="/matches/{match}/lineup"] button').click()
        page.wait_for_url(league.base+f'/matches/{match}')
        assert page.locator('li').filter(has_text='manager_home').count()==1
        assert_fits_phone(page)
    finally:
        context.close()
