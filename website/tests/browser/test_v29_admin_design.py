"""Responsive admin navigation, king currency and outcome-coloured profiles."""
import os
from pathlib import Path
import pytest
from playwright.sync_api import expect
from test_member_journey import chromium,league_server,assert_fits_phone,PASSWORD
from test_v29_admin_and_results import seed_player_results

pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Set RUN_BROWSER_TESTS=1 to require Chromium journeys.')


@pytest.mark.parametrize('width',[320,390,1440])
def test_administration_workspaces_and_results(chromium,league_server,width):
    league=league_server;seed_player_results()
    context=chromium.new_context(viewport={'width':width,'height':900})
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(league.base+'/') else route.abort())
    page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto(league.base+'/login')
        page.locator('input[name=username]').fill('BrowserAdmin');page.locator('input[name=password]').fill(PASSWORD)
        page.locator('form.stack-form button[type=submit]').click();page.wait_for_url(league.base+'/admin')
        expect(page.locator('.admin-workspace-card')).to_have_count(5)
        expect(page.locator('.admin-summary-card')).to_have_count(4)
        expect(page.locator('.admin-attention h2')).to_have_text('A precisar de atenção')
        assert_fits_phone(page)
        directory=Path('/workspace/review-runtime/v29-screenshots')
        if directory.parent.exists():
            directory.mkdir(exist_ok=True)
            page.screenshot(path=str(directory/f'admin-{width}.png'),full_page=True)
        page.locator('.admin-workspace-card[href="/admin/teams"]').click();page.wait_for_url(league.base+'/admin/teams')
        form=page.locator('form[action="/admin/teams"]');form.locator('input[name=name]').fill('Dashboard Knights '+str(width));form.locator('button').click()
        page.wait_for_url(league.base+'/admin/teams')
        expect(page.locator('.credit-symbol').first).to_have_text('♔')
        assert_fits_phone(page)
        page.locator('[data-page-navigation]').select_option('/admin/players');page.wait_for_url(league.base+'/admin/players')
        assert_fits_phone(page)
        page.goto(league.base+'/users/WhiteResults')
        expect(page.locator('.player-result-win')).to_have_count(2)
        expect(page.locator('.player-result-loss')).to_have_count(2)
        expect(page.locator('.player-result-draw')).to_have_count(2)
        expect(page.locator('.player-result-upcoming')).to_have_count(2)
        expect(page.locator('.player-result-win').first).to_contain_text('Vitória')
        expect(page.locator('.player-result-loss').first).to_contain_text('Derrota')
        assert_fits_phone(page)
        if directory.exists():
            page.locator('.player-game-result').first.locator('xpath=ancestor::table').screenshot(path=str(directory/f'results-{width}.png'))
        page.evaluate("localStorage.setItem('clubdraft.language','en')");page.reload()
        expect(page.locator('.player-result-win').first).to_contain_text('Won')
        expect(page.locator('.player-result-loss').first).to_contain_text('Lost')
        assert not errors,errors
    finally:context.close()
