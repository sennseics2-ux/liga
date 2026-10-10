"""Browser behavior checks: identity preservation, switching, and live translation."""
import html
import json
import os
import shutil
from pathlib import Path

import pytest
from test_league import client

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def page():
    required = os.environ.get("RUN_BROWSER_TESTS") == "1"
    if required:
        from playwright import sync_api as playwright
    else:
        playwright = pytest.importorskip("playwright.sync_api")
    executable = os.environ.get("LIGA_CHROMIUM_PATH") or shutil.which("chromium")
    with playwright.sync_playwright() as engine:
        options = {"headless": True, "args": ["--no-sandbox"]}
        if executable:
            options["executable_path"] = executable
        try:
            browser = engine.chromium.launch(**options)
        except playwright.Error as exc:
            if required:
                pytest.fail(f"Chromium browser is required for CI localization checks: {exc}")
            pytest.skip(f"Install a Chromium browser for localization checks: {exc}")
        page = browser.new_page()
        yield page
        browser.close()


def load(page, body, *, title="Players · Liga SX-AAC"):
    script = (ROOT / "static" / "i18n.js").read_text(encoding="utf-8")
    page.set_content(
        f"<!doctype html><html><head><title>{html.escape(title)}</title>"
        f"<script>{script}</script></head><body>{body}</body></html>"
    )


def test_names_and_metadata_survive_portuguese_and_repeated_switches(page):
    variables = html.escape(json.dumps({"name": "Players"}), quote=True)
    load(page, f'''
        <h1 id="heading" data-i18n="On the board.">On the board.</h1>
        <a id="players-nav">Players</a>
        <strong id="player" data-no-i18n>Players</strong>
        <a id="team" data-no-i18n>Teams</a>
        <span id="club" data-no-i18n>White</span>
        <p id="manager" data-i18n="Manager: {{name}}"
           data-i18n-vars="{variables}">Manager: Players</p>
        <pre id="pgn" data-no-i18n>[Event "Games"] 10... e5 *</pre>
    ''')
    assert page.locator("#heading").inner_text() == "No tabuleiro."
    assert page.locator("#players-nav").inner_text() == "Jogadores"
    assert page.locator("#manager").inner_text() == "Capitão: Players"
    for language in ("en", "pt-PT", "en", "pt-PT"):
        page.evaluate("lang => LigaI18n.setLanguage(lang)", language)
        assert page.locator("#player").inner_text() == "Players"
        assert page.locator("#team").inner_text() == "Teams"
        assert page.locator("#club").inner_text() == "White"
        assert page.locator("#pgn").inner_text() == '[Event "Games"] 10... e5 *'
        assert page.title() == "Players · Liga SX-AAC"
    assert page.locator("#heading").inner_text() == "No tabuleiro."


def test_interpolation_is_text_and_live_changes_keep_names(page):
    load(page, '<p id="manager" data-i18n="Current manager: {name}"></p>')
    page.evaluate('''() => {
        const node=document.querySelector('#manager');
        node.dataset.i18nVars=JSON.stringify({name:'<img src=x onerror=alert(1)>Teams'});
    }''')
    page.wait_for_function("document.querySelector('#manager').textContent.includes('Teams')")
    assert page.locator("#manager").inner_text() == "Capitão atual: <img src=x onerror=alert(1)>Teams"
    assert page.locator("#manager img").count() == 0
    page.evaluate("document.querySelector('#manager').dataset.i18nVars=JSON.stringify({name:'Players'})")
    page.wait_for_function("document.querySelector('#manager').textContent==='Capitão atual: Players'")
    page.evaluate("LigaI18n.setLanguage('en')")
    assert page.locator("#manager").inner_text() == "Current captain: Players"


def test_enum_variables_translate_only_when_explicitly_marked(page):
    variables = html.escape(json.dumps({"role": "manager"}), quote=True)
    load(page, f'''<p id="role" data-i18n="Your {{role}} role request has been sent to the administrator."
                 data-i18n-vars="{variables}" data-i18n-translated-vars="role"></p>
                 <p id="literal" data-i18n="Welcome back, {{name}}!"
                 data-i18n-vars="{html.escape(json.dumps({'name':'manager'}), quote=True)}"></p>''')
    assert page.locator("#role").inner_text() == "O teu pedido para ativar a função de capitão foi enviado ao administrador."
    assert page.locator("#literal").inner_text() == "Bem-vindo de volta, manager!"
    page.evaluate("LigaI18n.setLanguage('en')")
    assert page.locator("#role").inner_text() == "Your captain role request has been sent to the administrator."


def test_replay_copy_errors_and_table_attributes_use_the_selected_language(page):
    load(page, '''
        <div id="error" data-i18n="The minimum bid is 123 credits.">The minimum bid is 123 credits.</div>
        <table><tbody><tr><td id="column" data-label="PLAYER"><span data-no-i18n>Players</span></td>
        <td id="translated-column" data-label="POINTS">2300</td></tr></tbody></table>
        <button id="next" data-i18n-aria-label="Next move" aria-label="Next move">→</button>
    ''')
    assert page.locator("#error").inner_text() == "A licitação mínima é de 123 créditos."
    assert page.locator("#column").get_attribute("data-label") == "JOGADOR"
    assert page.locator("#column").inner_text() == "Players"
    assert page.locator("#translated-column").get_attribute("data-label") == "PONTOS"
    assert page.locator("#next").get_attribute("aria-label") == "Lance seguinte"
    assert page.evaluate("LigaI18n.t('Move {number}{suffix} {san} · {current} / {total} half-moves',{number:10,suffix:'…',san:'e5',current:1,total:2})") == "Lance 10… e5 · 1 / 2 meios-lances"
    page.evaluate("window.localeEvents=[];document.addEventListener('liga:languagechange',event=>localeEvents.push(event.detail.language));LigaI18n.setLanguage('en')")
    assert page.evaluate("localeEvents") == ["en"]
    assert page.locator("#error").inner_text() == "The minimum bid is 123 credits."
    assert page.locator("#next").get_attribute("aria-label") == "Next move"


def test_real_directories_and_auction_cards_keep_user_supplied_names(client, page):
    """Exercise the templates, not only the localization helper contract."""
    from urllib.parse import urlsplit
    import database as store

    player = store.create_player("Players", "White", 2100)
    auction = store.create_auction(player, 10, 12)
    team = store.create_team("Teams")

    def application(route):
        address = urlsplit(route.request.url)
        response = client.get(address.path + ("?" + address.query if address.query else ""))
        route.fulfill(status=response.status_code, body=response.content,
                      headers={"content-type": response.headers.get("content-type", "text/plain")})

    page.route("http://liga.test/**", application)
    page.goto("http://liga.test/players")
    assert page.locator("tbody tr").first.locator("td").nth(0).locator("[data-no-i18n]").inner_text() == "Players"
    assert page.locator("tbody tr").first.locator("td").nth(1).inner_text() == "White"
    assert page.locator('.nav-links a[href="/players"]').inner_text() == "Jogadores"
    page.goto("http://liga.test/teams")
    assert page.locator(".team-directory-copy h3").inner_text() == "Teams"
    page.goto(f"http://liga.test/teams/{team}")
    assert page.locator("h1").inner_text() == "Teams."
    assert page.title() == "Teams · Team"
    page.goto("http://liga.test/")
    assert page.locator(f'.market-card[href="/auctions/{auction}"] h3').inner_text() == "Players"
    page.evaluate("LigaI18n.setLanguage('en')")
    assert page.locator(f'.market-card[href="/auctions/{auction}"] h3').inner_text() == "Players"


def test_language_picker_keyboard_focus_and_escape(page):
    load(page, '''<div class="language-picker" data-no-i18n>
      <button id="language-toggle" aria-expanded="false">Language</button>
      <div id="language-menu" hidden>
        <button data-language="pt-PT">Português</button>
        <button data-language="en">English</button>
      </div></div>''')
    page.locator("#language-toggle").click()
    assert page.locator('[data-language="pt-PT"]').evaluate("node=>node===document.activeElement")
    page.keyboard.press("ArrowDown")
    assert page.locator('[data-language="en"]').evaluate("node=>node===document.activeElement")
    page.keyboard.press("Enter")
    assert page.evaluate("LigaI18n.language") == "en"
    assert page.locator("#language-toggle").evaluate("node=>node===document.activeElement")
    page.locator("#language-toggle").click()
    page.keyboard.press("Escape")
    assert page.locator("#language-menu").is_hidden()
    assert page.locator("#language-toggle").get_attribute("aria-expanded") == "false"
    assert page.locator("#language-toggle").evaluate("node=>node===document.activeElement")
