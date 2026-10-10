"""Browser auction polling preserves bids and responds to real server state."""
import os
import shutil
from urllib.parse import urlsplit

import pytest

import database as store
from test_league import client, post

pytestmark = pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS') != '1',
                                reason='Enable RUN_BROWSER_TESTS=1 for Chromium tests')


@pytest.fixture
def auction_page(client):
    from playwright.sync_api import sync_playwright
    manager = store.create_account('polling-viewer', 'BrowserPassphrase123!', 'manager')
    rival = store.create_account('polling-rival', 'BrowserPassphrase123!', 'manager')
    team, rival_team = store.create_team('Polling Viewers'), store.create_team('Polling Rivals')
    store.assign_manager(team, manager)
    store.assign_manager(rival_team, rival)
    auction = store.create_auction(store.create_player('Players'), 10, 24)
    store.place_bid(auction, team, 25)
    post(client, '/login', username='polling-viewer', password='BrowserPassphrase123!')
    state = {'offline': False, 'requests': 0}
    errors = []
    with sync_playwright() as engine:
        executable = os.environ.get('LIGA_CHROMIUM_PATH') or shutil.which('chromium')
        browser = engine.chromium.launch(executable_path=executable, headless=True,
                                         args=['--no-sandbox'])
        context = browser.new_context(viewport={'width':390, 'height':844})
        context.add_init_script("localStorage.setItem('clubdraft.language','en')")
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def local_application(route):
            address = urlsplit(route.request.url)
            if address.path == '/api/auctions/snapshot':
                state['requests'] += 1
                if state['offline']:
                    route.fulfill(status=503, body='{"detail":"Offline test"}',
                                  headers={'content-type':'application/json'})
                    return
            response = client.get(address.path + ('?' + address.query if address.query else ''))
            route.fulfill(status=response.status_code, body=response.content,
                          headers={'content-type':response.headers.get('content-type','text/plain')})

        page.route('http://liga.test/**', local_application)
        page.goto(f'http://liga.test/auctions/{auction}')
        page.wait_for_function("document.querySelector('[name=amount]').min==='26'")
        yield page, auction, rival_team, state, errors
        context.close()
        browser.close()


def force_refresh(page, event='online'):
    with page.expect_response(lambda response: '/api/auctions/snapshot?' in response.url) as pending:
        page.evaluate('event => window.dispatchEvent(new Event(event))', event)
    pending.value.finished()


def test_real_polling_preserves_edited_bid_reports_outbid_and_disables_closed_form(client, auction_page):
    from playwright.sync_api import expect
    page, auction, rival_team, state, errors = auction_page
    field = page.locator('[data-live-bid-form] [name="amount"]')
    submit = page.locator('[data-live-bid-form] button[type="submit"]')
    field.fill('99')
    store.place_bid(auction, rival_team, 30)
    force_refresh(page)
    expect(page.locator('[data-live-high-bid]')).to_have_text('30')
    expect(field).to_have_value('99')
    expect(field).to_have_attribute('min', '31')
    expect(field).to_have_attribute('max', '1000')
    expect(submit).to_be_enabled()
    expect(page.locator('[data-live-notice-text]')).to_have_text('You have been outbid.')
    expect(page.locator('[data-live-available]')).to_have_text('1000')

    state['offline'] = True
    force_refresh(page)
    expect(field).to_have_value('99')
    expect(submit).to_be_enabled()
    state['offline'] = False
    store.close_auction(auction, reason='Browser settlement check')
    force_refresh(page, 'pageshow')
    expect(field).to_have_value('99')
    expect(field).to_be_disabled()
    expect(submit).to_be_disabled()
    expect(page.locator('[data-live-notice-text]')).to_have_text('Auction closed')
    expect(page.locator('.bid-panel .countdown')).to_have_text('Closed')
    assert state['requests'] >= 4
    assert errors == []


def test_returning_logged_out_tab_disables_bid_and_removes_finance_display(client, auction_page):
    from playwright.sync_api import expect
    page, _, _, _, errors = auction_page
    field = page.locator('[data-live-bid-form] [name="amount"]')
    field.fill('99')
    client.cookies.clear()
    force_refresh(page, 'pageshow')
    expect(field).to_have_value('99')
    expect(field).to_be_disabled()
    expect(page.locator('[data-live-bid-form] button[type="submit"]')).to_be_disabled()
    expect(page.locator('[data-live-available]')).to_have_text('—')
    assert errors == []
