"""Version 4 account role and team workflow regression scenarios."""
import re
import pytest
from test_league import client, post, register, logout, seed_admin, login_admin, new_team
import database as store


def account(name):
    with store.read_db() as db:
        return db.execute('SELECT * FROM users WHERE username=?',(name,)).fetchone()


def invite_and_accept(client, team_id, manager_id, username='managerx'):
    logout(client)
    login_admin(client)
    result=post(client,f'/admin/teams/{team_id}/manager', manager_id=str(manager_id))
    assert 'Manager invitation sent' in result.text
    with store.read_db() as db:
        iid=db.execute("SELECT id FROM manager_invitations WHERE team_id=? AND status='pending'",(team_id,)).fetchone()[0]
    logout(client)
    post(client,'/login',username=username,password='p4ssword!AB12')
    assert 'Invitation accepted' in post(client,f'/my/manager/invitations/{iid}/respond',decision='accept').text
    return iid


def test_profiles_are_separate_and_never_manager_history(client):
    register(client,'newbie','player')
    assert 'Waiting for your chess profile' in client.get('/my/player').text
    assert 'You have never managed a team' in client.get('/my/manager').text
    assert 'Request manager activation' in client.get('/my/manager').text
    assert 'Player profile' in client.get('/my/player').text
    assert 'Manager profile' in client.get('/my/manager').text


def test_role_request_review_and_cannot_self_approve(client):
    register(client,'newbie','player')
    assert 'request has been sent' in post(client,'/my/roles/manager/request').text
    assert 'already have a pending request' in post(client,'/my/roles/manager/request').text
    assert post(client,'/admin/role-requests/1/review',decision='approve').status_code==403
    with store.read_db() as db:
        r=db.execute("SELECT * FROM role_requests WHERE status='pending'").fetchone()
        assert r['role']=='manager'
    logout(client)
    seed_admin()
    login_admin(client)
    assert 'newbie' in client.get('/admin').text
    assert 'Role request reviewed' in post(client,f'/admin/role-requests/{r["id"]}/review',decision='reject').text
    with store.read_db() as db:
        assert db.execute('SELECT manager_active FROM users WHERE username=?',('newbie',)).fetchone()[0]==0
    logout(client)
    post(client,'/login',username='newbie',password='p4ssword!AB12')
    assert 'request has been sent' in post(client,'/my/roles/manager/request').text
    with store.read_db() as db:
        nextid=db.execute("SELECT id FROM role_requests WHERE status='pending'").fetchone()[0]
    logout(client)
    login_admin(client)
    post(client,f'/admin/role-requests/{nextid}/review',decision='approve')
    assert account('newbie')['manager_active']==1
    logout(client)
    post(client,'/login',username='newbie',password='p4ssword!AB12')
    assert 'Manager · Active' in re.sub(r'<[^>]+>', '', client.get('/my/manager').text)
    assert 'Mark available' in client.get('/my/manager').text


def test_invitation_requires_explicit_accept_and_decline(client):
    seed_admin()
    register(client,'managerx')
    manager_id=account('managerx')['id']
    team1=store.create_team('First Team')
    team2=store.create_team('Second Team')
    logout(client)
    login_admin(client)
    post(client,f'/admin/teams/{team1}/manager',manager_id=str(manager_id))
    with store.read_db() as db:
        inv1=db.execute("SELECT id FROM manager_invitations WHERE team_id=?",(team1,)).fetchone()[0]
        assert db.execute('SELECT manager_id FROM teams WHERE id=?',(team1,)).fetchone()[0] is None
    logout(client)
    post(client,'/login',username='managerx',password='p4ssword!AB12')
    assert 'Invitation declined.' in post(client,f'/my/manager/invitations/{inv1}/respond',decision='decline').text
    assert 'no longer available' in post(client,f'/my/manager/invitations/{inv1}/respond',decision='accept').text
    assert 'Mark unavailable' in client.get('/my/manager').text
    post(client,'/my/manager/availability',available='0')
    assert account('managerx')['manager_available']==0
    logout(client)
    login_admin(client)
    assert 'Choose an available manager' in client.get('/admin').text
    assert 'Choose an available manager' in post(client,f'/admin/teams/{team2}/manager',manager_id=str(manager_id)).text
    logout(client)
    post(client,'/login',username='managerx',password='p4ssword!AB12')
    post(client,'/my/manager/availability',available='1')
    invitation=invite_and_accept(client,team2,manager_id)
    with store.read_db() as db:
        assert db.execute('SELECT manager_id FROM teams WHERE id=?',(team2,)).fetchone()[0]==manager_id
        assert db.execute('SELECT COUNT(*) FROM manager_terms WHERE manager_id=? AND ended_at IS NULL',(manager_id,)).fetchone()[0]==1
        assert db.execute('SELECT is_manager_player FROM players WHERE user_id=?',(manager_id,)).fetchone()[0]==1
    assert account('managerx')['manager_available']==0
    assert post(client,'/my/manager/availability',available='1').status_code==200
    assert 'must resign' in post(client,'/my/manager/availability',available='1').text


def test_manager_resignation_keeps_history_and_snapshot(client):
    register(client,'managerx')
    uid=account('managerx')['id']
    tid=store.create_team('Resignation Rooks')
    store.assign_manager(tid,uid)
    with store.transaction() as db:
        db.execute('UPDATE players SET points=23 WHERE user_id=?',(uid,))
    assert 'Type RESIGN' in post(client,'/my/manager/resign',confirmation='no').text
    assert 'resigned from the team' in post(client,'/my/manager/resign',confirmation='RESIGN').text
    assert 'Resignation Rooks' in client.get('/my/manager').text
    assert '23 fantasy pts' in re.sub(r'<[^>]+>', '', client.get('/my/manager').text)
    with store.read_db() as db:
        term=db.execute('SELECT * FROM manager_terms WHERE manager_id=?',(uid,)).fetchone()
        assert term['ended_at'] and term['final_fantasy_points']==23
        assert term['end_reason']=='resigned'
        assert db.execute('SELECT manager_id FROM teams WHERE id=?',(tid,)).fetchone()[0] is None
        assert db.execute('SELECT owner_team_id FROM players WHERE user_id=?',(uid,)).fetchone()[0] is None
    assert account('managerx')['manager_available']==0
    assert 'Availability updated' in post(client,'/my/manager/availability',available='1').text


def test_manager_quits_role_becomes_transferable_player(client):
    register(client,'managerx')
    uid=account('managerx')['id']
    tid=store.create_team('Last Managers')
    store.assign_manager(tid,uid)
    pid=store.connect().execute('SELECT id FROM players WHERE user_id=?',(uid,)).fetchone()[0]
    with pytest.raises(ValueError,match='cannot be listed'):
        store.create_auction(pid,10,24)
    assert 'Manager role deactivated' in post(client,'/my/roles/manager/quit').text
    assert account('managerx')['manager_active']==0
    assert account('managerx')['player_active']==1
    with store.read_db() as db:
        assert db.execute('SELECT is_manager_player FROM players WHERE id=?',(pid,)).fetchone()[0]==0
        assert db.execute('SELECT owner_team_id FROM players WHERE id=?',(pid,)).fetchone()[0] is None
        assert db.execute('SELECT manager_id FROM teams WHERE id=?',(tid,)).fetchone()[0] is None
    assert store.create_auction(pid,10,24)>0
    assert 'Request manager activation' in client.get('/my/manager').text
    assert 'Last Managers' in client.get('/my/manager').text


def test_player_quits_role_leaves_no_active_roles_and_reactivates(client):
    seed_admin()
    register(client,'playerx','player')
    uid=account('playerx')['id']
    pid=store.create_player('Player X',user_id=uid)
    assert 'Player role' in post(client,'/my/roles/player/quit').text
    assert account('playerx')['player_active']==0
    assert account('playerx')['manager_active']==0
    assert 'Player X' not in client.get('/players').text
    with pytest.raises(ValueError,match='no active player'):
        store.create_auction(pid,10,24)
    assert 'request has been sent' in post(client,'/my/roles/player/request').text
    with store.read_db() as db:
        reqid=db.execute("SELECT id FROM role_requests WHERE role='player'").fetchone()[0]
    logout(client)
    login_admin(client)
    post(client,f'/admin/role-requests/{reqid}/review',decision='approve')
    assert account('playerx')['player_active']==1
    assert 'Player X' in client.get('/players').text


def test_manager_kicks_only_owned_ordinary_player(client):
    manager_id,team_id=new_team('bobby','Bobby Team')
    other_id,other_team=new_team('outsider','Other Team')
    regular=store.create_player('Regular Pawn')
    protected=store.connect().execute('SELECT id FROM players WHERE user_id=?',(manager_id,)).fetchone()[0]
    other=store.create_player('Other Player')
    with store.transaction() as db:
        db.execute('UPDATE players SET owner_team_id=? WHERE id=?',(team_id,regular))
        db.execute('UPDATE players SET owner_team_id=? WHERE id=?',(other_team,other))
    post(client,'/register',username='unused',password='p4ssword!AB12',role='player')
    logout(client)
    post(client,'/login',username='bobby',password='password123!')
    assert 'Type KICK' in post(client,f'/my/manager/players/{regular}/kick',confirmation='no').text
    assert 'Managers cannot be kicked' in post(client,f'/my/manager/players/{protected}/kick',confirmation='KICK').text
    assert 'not on your team' in post(client,f'/my/manager/players/{other}/kick',confirmation='KICK').text
    auction=store.create_auction(regular,10,24)
    assert 'active auction' in post(client,f'/my/manager/players/{regular}/kick',confirmation='KICK').text
    with store.transaction() as db:
        db.execute("UPDATE auctions SET status='closed' WHERE id=?",(auction,))
    assert 'now a free agent' in post(client,f'/my/manager/players/{regular}/kick',confirmation='KICK').text
    with store.read_db() as db:
        assert db.execute('SELECT owner_team_id FROM players WHERE id=?',(regular,)).fetchone()[0] is None
    assert 'not on your team' in post(client,f'/my/manager/players/{regular}/kick',confirmation='KICK').text


def test_role_quit_player_blocked_during_transfer(client):
    register(client,'playerx','player')
    uid=account('playerx')['id']
    pid=store.create_player('Auction Player',user_id=uid)
    store.create_auction(pid,10,24)
    assert 'open auction' in post(client,'/my/roles/player/quit').text
    assert account('playerx')['player_active']==1


def test_v4_schema_migration_is_idempotent_and_preserves_history(client):
    uid=store.create_account('oldman','password123!','manager')
    t=store.create_team('Migration Team')
    store.assign_manager(t,uid)
    store.init_db()
    store.init_db()
    with store.read_db() as db:
        assert db.execute('SELECT COUNT(*) FROM manager_terms WHERE manager_id=?',(uid,)).fetchone()[0]==1
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
    assert store.DB_PATH.with_name(store.DB_PATH.name+'.pre-v4.bak').exists() is False  # new databases are not migrated


def test_existing_player_can_be_approved_manager_and_accept_invitation(client):
    seed_admin()
    register(client,'convertme','player')
    uid=account('convertme')['id']
    assert 'request has been sent' in post(client,'/my/roles/manager/request').text
    with store.read_db() as db:
        request_id=db.execute("SELECT id FROM role_requests WHERE status='pending'").fetchone()[0]
    logout(client)
    login_admin(client)
    post(client,f'/admin/role-requests/{request_id}/review',decision='approve')
    team=store.create_team('New Role Team')
    logout(client)
    post(client,'/login',username='convertme',password='p4ssword!AB12')
    assert 'Availability updated' in post(client,'/my/manager/availability',available='1').text
    invite_and_accept(client,team,uid,username='convertme')
    with store.read_db() as db:
        assert db.execute('SELECT manager_id FROM teams WHERE id=?',(team,)).fetchone()[0]==uid
        assert db.execute('SELECT COUNT(*) FROM players WHERE user_id=? AND is_manager_player=1',(uid,)).fetchone()[0]==1


def test_player_role_reactivation_of_manager_only_restores_team_profile(client):
    seed_admin()
    register(client,'managerx')
    uid=account('managerx')['id']
    team=store.create_team('Only Manager Team')
    store.assign_manager(team,uid)
    assert 'Player role deactivated' in post(client,'/my/roles/player/quit').text
    with store.read_db() as db:
        assert db.execute('SELECT owner_team_id FROM players WHERE user_id=?',(uid,)).fetchone()[0] is None
    post(client,'/my/roles/player/request')
    with store.read_db() as db:
        req=db.execute("SELECT id FROM role_requests WHERE status='pending'").fetchone()[0]
    logout(client)
    login_admin(client)
    post(client,f'/admin/role-requests/{req}/review',decision='approve')
    with store.read_db() as db:
        p=db.execute('SELECT owner_team_id,is_manager_player FROM players WHERE user_id=?',(uid,)).fetchone()
        assert p['owner_team_id']==team and p['is_manager_player']==1


def test_real_v3_database_upgrade_preserves_records_and_backfills_history(monkeypatch, legacy_database_factory):
    dbpath=legacy_database_factory(3)
    monkeypatch.setattr(store,'DB_PATH',dbpath)
    store.init_db()
    store.init_db()
    with store.read_db() as db:
        u=db.execute("SELECT * FROM users WHERE username='pastmanager'").fetchone()
        t=db.execute("SELECT * FROM teams WHERE name='Historical Team'").fetchone()
        assert u['manager_active']==1 and u['player_active']==1
        assert t['manager_id']==u['id']
        assert db.execute('SELECT COUNT(*) FROM bids').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM auctions').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM manager_terms WHERE manager_id=?',(u['id'],)).fetchone()[0]==1
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
    assert dbpath.with_name(dbpath.name+'.pre-v4.bak').exists()


def test_player_cannot_bypass_no_self_resignation_rule_using_role_change(client):
    register(client,'playx','player')
    uid=account('playx')['id']
    pid=store.create_player('Player X',user_id=uid)
    team=store.create_team('Locked Roster')
    with store.transaction() as db:
        db.execute('UPDATE players SET owner_team_id=? WHERE id=?',(team,pid))
    assert 'team manager must remove you' in post(client,'/my/roles/player/quit').text
    assert account('playx')['player_active']==1
    with store.read_db() as db:
        assert db.execute('SELECT owner_team_id FROM players WHERE id=?',(pid,)).fetchone()[0]==team
