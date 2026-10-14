"""Inline rename controls support keyboard use and mobile layouts."""
import os
import pytest
from playwright.sync_api import expect
from test_member_journey import chromium,league_server,assert_fits_phone,PASSWORD

pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Set RUN_BROWSER_TESTS=1 to require Chromium journeys.')


@pytest.mark.parametrize('width,theme,language',[(320,'dark','pt-PT'),(1440,'light','en')])
def test_player_name_pencil_save_and_escape(chromium,league_server,width,theme,language):
    league=league_server
    player=league.store.create_player('Long unregistered player name Mário Martins Freitas')
    context=chromium.new_context(viewport={'width':width,'height':1000})
    context.add_init_script(f"localStorage.setItem('clubdraft.theme','{theme}');localStorage.setItem('clubdraft.language','{language}')")
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(league.base+'/') else route.abort())
    page=context.new_page()
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto(league.base+'/login?next=/admin/players')
        page.locator('input[name=username]').fill('BrowserAdmin')
        page.locator('input[name=password]').fill(PASSWORD)
        page.locator('form.stack-form button[type=submit]').click()
        page.wait_for_url('**/admin/players')
        editor=page.locator(f'form[action="/admin/players/{player}/name"]')
        name=editor.locator('[data-name-input]')
        edit=editor.locator('[data-name-edit]')
        save=editor.locator('[data-name-save]')
        expect(edit).to_be_visible();expect(save).to_be_hidden()
        edit.click();expect(name).to_be_focused();expect(save).to_be_visible()
        assert_fits_phone(page)
        name.fill('Discard this draft');name.press('Escape')
        expect(edit).to_be_focused();expect(name).to_be_hidden()
        edit.click();expect(name).to_have_value('Long unregistered player name Mário Martins Freitas')
        name.fill('Renamed Mário Martins');save.click()
        page.wait_for_url('**/admin/players#player-list')
        expect(editor.locator('[data-name-link]')).to_have_text('Renamed Mário Martins')
        assert_fits_phone(page)
        editor.locator('[data-name-link]').click();page.wait_for_url(f'**/players/{player}')
        expect(page.locator('.member-profile-identity')).to_contain_text('Renamed Mário Martins')
        assert not errors,errors
    finally:
        context.close()
