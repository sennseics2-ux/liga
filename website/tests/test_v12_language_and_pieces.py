"""Regression tests for V12 language UI and piece rendering options."""
from pathlib import Path
import json
from test_league import client

ROOT = Path(__file__).resolve().parents[1]


def test_language_switch_is_in_global_nav_and_portuguese_is_default(client):
    for route in ('/', '/players', '/teams', '/games', '/login'):
        response = client.get(route)
        assert response.status_code == 200
        html = response.text
        assert '<html lang="pt-PT">' in html
        assert 'src="/static/i18n.js?v=44"' in html
        assert 'id="language-toggle"' in html
        assert 'id="language-flag"' in html
        assert 'src="/static/flags/pt.svg"' in html and 'Português (Portugal)' in html
        assert 'src="/static/flags/gb.svg"' in html and 'English' in html


def test_portuguese_catalogue_uses_european_spelling():
    strings=json.loads((ROOT/'static/pt-PT.json').read_text())
    assert strings['Teams']=='Equipas'
    assert strings['Team Manager']=='Capitão da equipa'
    assert strings['Transfer market']=='Mercado de transferências'
    assert strings['Log in']=='Iniciar sessão'
    assert strings['Pieces']=='Peças'
    assert strings['board.']=='no tabuleiro.'
    assert len(strings)>=700


def test_manager_squad_tag_has_only_requested_label(client):
    html=(ROOT/'templates/team_detail.html').read_text()
    assert '>Team Captain</span>' in html
    assert 'Team captain · non-transferable' not in html


def test_language_works_on_dynamically_updated_pages():
    script=(ROOT/'static/i18n.js').read_text()
    assert 'MutationObserver' in script
    assert 'localStorage.setItem(KEY,lang)' in script
    assert "document.documentElement.lang=language" in script
    assert 'originalDocumentTitle' in script
