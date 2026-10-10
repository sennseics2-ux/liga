"""V20 brand, two-role homepage, guest sign-in and mobile-header regressions."""
import json
from pathlib import Path
from test_league import client, register, logout, seed_admin, post


ROOT = Path(__file__).resolve().parents[1]


def test_home_is_split_player_left_manager_right_with_accurate_content(client):
    response = client.get('/')
    assert response.status_code == 200
    html = response.text
    assert html.index('role-card-player') < html.index('role-card-manager')
    assert 'FOR PLAYERS' in html and 'FOR CAPTAINS' in html
    assert 'Play. Compete.' in html and 'Lead your team.' in html
    assert 'replay recorded PGN games' in html
    assert 'Bid for players using your transfer budget' in html
    assert 'Build your team.' not in html and 'Own the board.' not in html
    assert 'CHESS LEAGUE</small>' in html
    assert 'FANTASY CHESS LEAGUE</small>' not in html


def test_guest_primary_ctas_use_login_and_registration_remains_accessible(client):
    html = client.get('/').text
    # Cards do not route first-time visitors straight to registration.
    hero = html.split('<section class="role-hero"', 1)[1].split('</section>', 1)[0]
    assert hero.count('href="/login"') == 2
    assert 'href="/register"' not in hero
    assert 'class="btn btn-primary btn-small" href="/login"' in html
    assert 'class="login-link" href="/register">Create account</a>' in html
    assert client.get('/login').status_code == 200
    assert client.get('/register').status_code == 200
    assert 'href="/login">Log in ↗</a>' in client.get('/standings').text


def test_logged_in_roles_have_appropriate_hero_links(client):
    register(client, 'playerhero', 'player')
    player_html = client.get('/').text
    hero = player_html.split('<section class="role-hero"', 1)[1].split('</section>', 1)[0]
    assert 'href="/users/playerhero"' in hero
    assert 'href="/users/playerhero/manager"' in hero
    logout(client)
    seed_admin()
    post(client, '/login', username='commissioner', password='adminpass123!')
    admin_html = client.get('/').text
    hero = admin_html.split('<section class="role-hero"', 1)[1].split('</section>', 1)[0]
    assert 'href="/account/profile"' in hero
    assert 'href="/admin"' in hero


def test_pt_portugal_translations_and_mobile_brand_rules(client):
    catalogue = json.loads((ROOT/'static/pt-PT.json').read_text())
    assert catalogue['CHESS LEAGUE'] == 'LIGA DE XADREZ'
    assert catalogue['FOR PLAYERS'] == 'PARA JOGADORES'
    assert catalogue['FOR CAPTAINS'] == 'PARA CAPITÃES'
    assert catalogue['Create account'] == 'Criar conta'
    for label in ['Play. Compete.', 'Make your mark.', 'Lead your team.', 'Build your squad.', 'Explore teams']:
        assert label in catalogue and catalogue[label]
    css = (ROOT/'static/style.css').read_text()
    assert "grid-template-areas:'brand toggle' 'actions actions'" in css
    assert 'grid-template-columns:repeat(2,minmax(0,1fr))' in css
    assert '.role-hero-grid{grid-template-columns:minmax(0,1fr)' in css
