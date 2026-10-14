"""Team pencil/save controls match the player editor across mobile and desktop."""
import os
import pytest
from playwright.sync_api import expect
from test_member_journey import chromium,league_server,assert_fits_phone,PASSWORD

pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Set RUN_BROWSER_TESTS=1 to require Chromium journeys.')


@pytest.mark.parametrize('width,theme,language',[(320,'dark','pt-PT'),(1440,'light','en')])
def test_team_pencil_save_cancel_and_profile_link(chromium,league_server,width,theme,language):
    league=league_server
    with league.store.read_db() as db:team=db.execute("SELECT id FROM teams WHERE name='Teams'").fetchone()[0]
    context=chromium.new_context(viewport={'width':width,'height':1000})
    context.add_init_script(f"localStorage.setItem('clubdraft.theme','{theme}');localStorage.setItem('clubdraft.language','{language}')")
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(league.base+'/') else route.abort())
    page=context.new_page()
    try:
        page.goto(league.base+'/login?next=/admin/teams')
        page.locator('input[name=username]').fill('BrowserAdmin')
        page.locator('input[name=password]').fill(PASSWORD)
        page.locator('form.stack-form button[type=submit]').click()
        page.wait_for_url('**/admin/teams')
        editor=page.locator(f'form[action="/admin/teams/{team}/name"]')
        name=editor.locator('[data-name-input]');edit=editor.locator('[data-name-edit]');save=editor.locator('[data-name-save]')
        expect(edit).to_have_attribute('aria-label','Editar nome da equipa' if language=='pt-PT' else 'Edit team name')
        expect(save).to_be_hidden();edit.click();expect(name).to_be_focused();expect(save).to_be_visible()
        assert_fits_phone(page)
        name.fill('Discard draft');name.press('Escape');expect(edit).to_be_focused()
        edit.click();expect(name).to_have_value('Teams')
        name.fill('Renamed Team');save.click();page.wait_for_url('**/admin/teams#teams')
        expect(editor.locator('[data-name-link]')).to_have_text('Renamed Team')
        assert_fits_phone(page)
        editor.locator('[data-name-link]').click();page.wait_for_url(f'**/teams/{team}')
        expect(page.locator('h1')).to_contain_text('Renamed Team')
    finally:context.close()
