import os
from pathlib import Path
import pytest
from playwright.sync_api import expect
from test_member_journey import chromium,league_server,assert_fits_phone,PASSWORD
import account_service as accounts

pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Set RUN_BROWSER_TESTS=1 for Chromium journeys.')

@pytest.mark.parametrize('width',[320,390,1280])
def test_recovery_design_fields_language_and_deactivated_login(chromium,league_server,width):
    league=league_server
    context=chromium.new_context(viewport={'width':width,'height':900})
    page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto(league.base+'/forgot-password')
        assert page.locator('input[name=username]').get_attribute('required') is not None
        page.locator('input[name=username]').fill('BrowserMember')
        page.locator('input[name=email]').fill('member@example.com')
        expect(page.locator('.recovery-footer a [data-i18n]')).to_have_text('Voltar ao início de sessão')
        assert_fits_phone(page)
        if width==390:
            directory=Path('/workspace/review-runtime/v26-screenshots')
            if directory.parent.exists():
                directory.mkdir(exist_ok=True)
                page.screenshot(path=str(directory/'recovery-mobile.png'),full_page=True)
        page.locator('form.stack-form button').click()
        page.wait_for_selector('.recovery-success')
        expect(page.locator('.recovery-success')).to_contain_text('nome de utilizador e o email')
        assert_fits_phone(page)
        page.locator('.recovery-footer a').click()
        with league.store.read_db() as db:
            uid=db.execute("SELECT id FROM users WHERE username='BrowserMember'").fetchone()[0]
            admin=db.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
        accounts.set_account_active(uid,False,actor_id=admin)
        page.locator('input[name=username]').fill('BrowserMember')
        page.locator('input[name=password]').fill(PASSWORD)
        page.locator('form.stack-form button').click()
        page.wait_for_selector('.notice-error')
        expect(page.locator('.notice-error')).to_have_text('A conta foi desativada. Contacta o administrador para a reativar.')
        page.evaluate("localStorage.setItem('clubdraft.language','en')")
        page.reload()
        page.locator('input[name=username]').fill('BrowserMember')
        page.locator('input[name=password]').fill(PASSWORD)
        page.locator('form.stack-form button').click()
        page.wait_for_selector('.notice-error')
        expect(page.locator('.notice-error')).to_have_text('The account has been deactivated. Please contact the administrator to reactivate it.')
        page.goto(league.base+'/register')
        expect(page.locator('form.stack-form button')).to_contain_text('Create account')
        page.evaluate("localStorage.setItem('clubdraft.language','pt-PT')")
        page.reload()
        expect(page.locator('form.stack-form button')).to_contain_text('Criar conta')
        assert not errors,errors
    finally:
        context.close()
