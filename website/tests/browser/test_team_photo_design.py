"""Current managers can edit team pictures on phones and desktop in PT/EN."""
import os
import tempfile
from pathlib import Path
import pytest
from playwright.sync_api import expect
from test_member_journey import chromium,league_server,assert_fits_phone,PASSWORD
from test_team_photos import picture

pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Set RUN_BROWSER_TESTS=1 to require Chromium journeys.')


@pytest.mark.parametrize('width',[320,390,1440])
def test_team_picture_upload_and_removal(chromium,league_server,width):
    league=league_server
    with league.store.read_db() as db:
        team=db.execute("SELECT id FROM teams WHERE name='Teams'").fetchone()[0]
    context=chromium.new_context(viewport={'width':width,'height':900})
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(league.base+'/') else route.abort())
    page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto(league.base+'/login')
        page.locator('input[name=username]').fill('BrowserMember');page.locator('input[name=password]').fill(PASSWORD)
        page.locator('form.stack-form button[type=submit]').click();page.wait_for_url('**/users/BrowserMember/manager')
        page.goto(f'{league.base}/teams/{team}')
        expect(page.locator('.team-photo-editor h2')).to_have_text('Imagem de perfil da equipa')
        page.locator('#team-photo').set_input_files({'name':'team.png','mimeType':'image/png','buffer':picture()})
        page.locator('.photo-upload-form button').click()
        expect(page.locator('.team-profile-picture img')).to_be_visible()
        expect(page.locator('.photo-upload-form button')).to_have_text('Substituir fotografia')
        assert page.locator('.team-profile-picture img').evaluate('(img)=>img.complete && img.naturalWidth===512')
        assert_fits_phone(page)
        directory=(Path('/workspace/review-runtime') if Path('/workspace/review-runtime').exists() else Path(tempfile.gettempdir())) / 'v30-screenshots';directory.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(directory/f'team-{width}.png'),full_page=True)
        page.goto(league.base+'/teams')
        expect(page.locator(f'img[src="/teams/{team}/photo"]')).to_be_visible();assert_fits_phone(page)
        page.goto(f'{league.base}/teams/{team}')
        page.evaluate("localStorage.setItem('clubdraft.language','en')");page.reload()
        expect(page.locator('.team-photo-editor h2')).to_have_text('Team profile picture')
        page.on('dialog',lambda dialog:dialog.accept())
        page.locator(f'form[action="/teams/{team}/photo/remove"] button').click()
        expect(page.locator('.team-profile-picture img')).to_have_count(0)
        assert not errors,errors
    finally:context.close()
