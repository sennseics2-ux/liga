"""V5 integrated public member profiles: navigation, sharing and access boundaries."""
from test_league import client, post, register, logout, seed_admin
import re
import database as store


def test_member_tabs_and_old_links(client):
    register(client, 'lina', 'player')
    with store.read_db() as db:
        uid = db.execute("SELECT id FROM users WHERE username='lina'").fetchone()[0]
    homepage = client.get('/').text
    nav = homepage.split('id="nav-links"', 1)[1].split('</div>', 1)[0]
    assert 'Player page' not in nav
    assert 'Manager page' not in nav
    assert '/members' not in nav
    assert '/players' in nav
    assert 'id="account-toggle"' in homepage
    assert 'href="/account/profile"' in homepage
    assert client.get('/account/profile', follow_redirects=False).headers['location'] == '/users/lina'
    assert client.get('/dashboard', follow_redirects=False).headers['location'] == '/users/lina'
    assert client.get('/my/player', follow_redirects=False).headers['location'] == '/users/lina'
    assert client.get('/my/manager', follow_redirects=False).headers['location'] == '/users/lina/manager'
    page = client.get(f'/users/{uid}').text
    assert 'Player profile' in page and 'Manager profile' in page
    assert 'Quit player role' in page
    assert 'href="/users/lina/manager"' in page
    assert 'You have never managed a team' in client.get(f'/users/{uid}/manager').text
    assert 'Request manager activation' in client.get(f'/users/{uid}/manager').text
    assert client.get('/members', follow_redirects=False).headers['location']=='/players'
    assert 'All players' in client.get(f'/users/{uid}').text


def test_public_profiles_without_private_actions_or_invitations(client):
    register(client, 'managerjoe', 'manager')
    with store.read_db() as db:
        mid = db.execute("SELECT id FROM users WHERE username='managerjoe'").fetchone()[0]
    tid = store.create_team('Bishops Club')
    store.assign_manager(tid, mid)
    logout(client)
    register(client, 'visitor', 'player')
    public = client.get(f'/users/{mid}/manager').text
    assert 'Bishops Club' in public
    assert 'Manager · Active' in re.sub(r'<[^>]+>', '', public)
    assert 'Management history' in public
    assert 'Resign from team' not in public
    assert 'Quit manager role' not in public
    assert 'Kick player' not in public
    assert 'Your active bids' not in public
    assert 'PRIVATE TRANSFER ACTIVITY' not in public
    assert 'Mark available' not in public
    assert 'Accept invitation' not in public
    assert 'Request manager activation' not in public
    player_page = client.get(f'/users/{mid}').text
    assert 'Quit player role' not in player_page
    assert 'Request player activation' not in player_page
    assert 'href="/users/managerjoe"' in client.get('/players').text
    assert 'href="/users/managerjoe/manager"' in client.get('/standings').text
    logout(client)
    assert client.get(f'/users/{mid}/manager').status_code == 200
    anon = client.get(f'/users/{mid}/manager').text
    assert 'Bishops Club' in anon
    assert 'Resign from team' not in anon
    assert client.get('/users/987654').status_code == 404


def test_past_team_visible_to_visitors_and_private_invitations(client):
    register(client, 'formerboss', 'manager')
    with store.read_db() as db:
        mid = db.execute("SELECT id FROM users WHERE username='formerboss'").fetchone()[0]
    tid = store.create_team('Old Rooks')
    store.assign_manager(tid, mid)
    assert 'Old Rooks' in post(client, '/my/manager/resign', confirmation='RESIGN').text
    logout(client)
    register(client, 'observer', 'player')
    past = client.get(f'/users/{mid}/manager').text
    assert 'Old Rooks' in past
    assert 'resigned' in past
    assert 'Management history' in past
    assert 'fantasy pts' in past
    assert 'never managed a team' not in past

    logout(client)
    seed_admin()
    post(client, '/login', username='commissioner', password='adminpass123!')
    assert client.get('/users/3').status_code == 404  # administrator has no member page
