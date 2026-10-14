"""V21 homepage-only palette and friendly European Portuguese regression checks."""
import json
from pathlib import Path
from test_league import client

ROOT = Path(__file__).resolve().parents[1]

def test_homepage_monochrome_scoped_and_rest_is_unchanged(client):
    home = client.get('/')
    players = client.get('/players')
    assert home.status_code == players.status_code == 200
    assert '<body class="home-theme">' in home.text
    assert '<body class="home-theme">' not in players.text
    css = (ROOT/'static/style.css').read_text()
    assert 'body.home-theme .role-hero{background:#0d0e0f' in css
    assert 'body.home-theme .role-card-player{background:#f6f6f6' in css
    assert 'body.home-theme .role-card-manager{background:#232425' in css
    assert 'body.home-theme .stats-strip{background:#212223' in css
    assert 'body.home-theme .how-section{background:#f1f1f1' in css
    assert home.text.index('role-card-player') < home.text.index('role-card-manager')

def test_casual_portuguese_but_english_templates_unchanged(client):
    cat = json.loads((ROOT/'static/pt-PT.json').read_text())
    assert cat['Play. Compete.'] == 'Joga. Compete.'
    assert cat['Make your mark.'] == 'Deixa a tua marca.'
    assert cat['Lead your team.'] == 'Lidera a tua equipa.'
    assert cat['Build your squad.'] == 'Constrói o teu plantel.'
    assert cat['Represent your team on the chessboard and follow your achievements throughout the league.'].startswith('Representa a tua equipa')
    assert 'O administrador tem de' in cat['Your account is registered. The administrator must add a chess player and link it to your username before you appear in the player directory and can enter transfer auctions.']
    assert 'pelos seus jogadores' in next(v for k,v in cat.items() if k.startswith('Every point counts. The team with the most combined player fantasy points leads'))
    assert 'src="/static/i18n.js?v=100"' in client.get('/').text
    assert 'href="/static/style.css?v=100"' in client.get('/').text
    assert 'Play. Compete.' in client.get('/').text
    assert 'Lead your team.' in client.get('/').text
    js = (ROOT/'static/i18n.js').read_text()
    assert 'Joga. Compete.' in js and 'Deixa a tua marca.' in js
    assert "language = 'pt-PT'" in js
