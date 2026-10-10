"""Profile role and team-history regression tests."""
import database as store
import re
from test_league import client, post, register, logout


def test_role_indicators_and_owner_only_controls(client):
    register(client, 'dual_account', 'player')
    with store.read_db() as db:
        uid=db.execute("SELECT id FROM users WHERE username='dual_account'").fetchone()[0]
    html=client.get(f'/users/{uid}').text
    assert 'Player · Active' in re.sub(r'<[^>]+>', '', html)
    assert 'Captain · Inactive' in re.sub(r'<[^>]+>', '', html)
    assert '<details class="role-settings"' in html
    assert 'Player role:' not in html
    assert 'Account &amp; role settings' in html
    assert 'Quit player role' in html
    logout(client)
    html=client.get(f'/users/{uid}/manager').text
    assert 'Quit player role' not in html
    assert 'Captain · Inactive' in re.sub(r'<[^>]+>', '', html)


def test_history_and_manager_first_in_squad(client):
    manager=store.create_account('chief_v11','VerySecurePassword1!','manager')
    other=store.create_account('teammate_v11','VerySecurePassword1!','player')
    team_id=store.create_team('The Knights')
    player_id=store.create_player('Veteran Player',user_id=other)
    store.assign_manager(team_id,manager)
    # Public identity + recorded manager/player memberships.
    profile=client.get(f'/users/{manager}').text
    assert 'Current &amp; former teams' in profile
    assert 'The Knights' in profile
    assert 'TEAM ROSTER' not in client.get(f'/users/{manager}/manager').text
    with store.read_db() as db:
        mgr_player=db.execute('SELECT id FROM players WHERE user_id=?',(manager,)).fetchone()[0]
        db.execute('UPDATE players SET points=1 WHERE id=?',(mgr_player,))
        db.execute('UPDATE players SET points=100 WHERE id=?',(player_id,))
    with store.transaction() as db:
        db.execute('UPDATE players SET owner_team_id=? WHERE id=?',(team_id,player_id))
    html=client.get(f'/teams/{team_id}').text
    squad=html.split('Current squad',1)[1].split('Squad by season',1)[0]
    assert squad.index('chief_v11') < squad.index('Veteran Player')


