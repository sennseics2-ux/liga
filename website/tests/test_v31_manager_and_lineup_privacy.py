"""Appointment lifecycle and server-side embargo of pre-match selections."""
from datetime import timedelta
import pytest
import re
import database as store
import league_seasons as seasons
from test_league import client,post,token
from test_v25_seasons import setup,PASSWORD


def login(client,name):
    post(client,'/login',username=name,password=PASSWORD if name!='commissioner' else 'adminpass123!')


def arranged_match():
    fixture=setup()
    admin,season,rounds,match,teams,managers,rosters=fixture
    seasons.submit_lineup(match,managers[0],rosters[0])
    seasons.submit_lineup(match,managers[1],rosters[1])
    with store.transaction() as db:
        db.execute("UPDATE seasons SET status='published' WHERE id=?",(season,))
    return fixture


def test_remove_keeps_role_active_and_can_invite_back_to_same_team(client):
    _,_,_,_,teams,managers,_=setup();team=teams[0];manager=managers[0]
    login(client,'commissioner')
    html=client.get('/admin/teams').text
    form=re.search(r'<form[^>]*action="/admin/teams/'+str(team)+r'/remove-manager".*?</form>',html,re.S).group(0)
    assert 'aria-label="Remove captain"' in form and '<svg' in form
    assert 'class="manager-remove-button"' in form
    assert client.post(f'/admin/teams/{team}/remove-manager',data={'confirmation':'REMOVE'}).status_code==403
    assert 'Captain removed' in post(client,f'/admin/teams/{team}/remove-manager',confirmation='REMOVE').text
    with store.read_db() as db:
        user=db.execute('SELECT * FROM users WHERE id=?',(manager,)).fetchone()
        assert user['manager_active']==1 and user['manager_available']==1
        assert db.execute('SELECT owner_team_id FROM players WHERE user_id=?',(manager,)).fetchone()[0] is None
        assert db.execute('SELECT ended_at FROM manager_terms WHERE manager_id=?',(manager,)).fetchone()[0]
    assert f'<option value="{manager}"' in client.get('/admin/teams').text
    assert 'Captain invitation sent' in post(client,f'/admin/teams/{team}/manager',manager_id=str(manager)).text
    with store.read_db() as db:
        invitation=db.execute("SELECT id FROM manager_invitations WHERE team_id=? AND status='pending'",(team,)).fetchone()[0]
    login(client,'manager_home')
    assert 'Invitation accepted' in post(client,f'/my/manager/invitations/{invitation}/respond',decision='accept').text
    with store.read_db() as db:
        assert db.execute('SELECT manager_id FROM teams WHERE id=?',(team,)).fetchone()[0]==manager
        assert db.execute('SELECT COUNT(*) FROM manager_terms WHERE manager_id=?',(manager,)).fetchone()[0]==2
        assert db.execute('SELECT owner_team_id FROM players WHERE user_id=?',(manager,)).fetchone()[0]==team


def test_pending_invitation_can_be_cancelled_in_table_and_sent_again(client):
    _,_,_,_,teams,managers,_=setup();team=teams[0];manager=managers[0]
    store.assign_manager(team,None)
    invitation=store.invite_manager(team,manager)
    login(client,'manager_home')
    assert post(client,f'/admin/invitations/{invitation}/cancel').status_code==403
    login(client,'commissioner')
    table=client.get('/admin/teams').text.split('team-management-table',1)[1].split('</table>',1)[0]
    assert f'action="/admin/invitations/{invitation}/cancel"' in table and 'Cancel invitation' in table
    assert client.post(f'/admin/invitations/{invitation}/cancel',data={}).status_code==403
    assert 'Pending invitation cancelled.' in post(client,f'/admin/invitations/{invitation}/cancel').text
    assert 'Invitation pending' not in client.get('/admin/teams').text
    login(client,'manager_home')
    assert 'no longer available' in post(client,f'/my/manager/invitations/{invitation}/respond',decision='accept').text
    assert 'no longer pending' in _cancel_again(invitation)
    new=store.invite_manager(team,manager)
    store.respond_invitation(manager,new,True)
    with store.read_db() as db:
        old=db.execute('SELECT * FROM manager_invitations WHERE id=?',(invitation,)).fetchone()
        assert old['status']=='cancelled' and old['responded_at']
        assert db.execute('SELECT manager_id FROM teams WHERE id=?',(team,)).fetchone()[0]==manager


def _cancel_again(invitation):
    with pytest.raises(ValueError) as error:
        store.cancel_invitation(invitation)
    return str(error.value)


@pytest.mark.parametrize('viewer,visible_side',[(None,None),('commissioner',None),('outsider',None),
    ('manager_home',0),('manager_away',1),('home_player_1',0),('away_player_1',1)])
def test_only_current_team_sees_own_lineup_before_kickoff(client,viewer,visible_side):
    _,_,_,match,teams,managers,rosters=arranged_match()
    if viewer=='outsider':store.create_account('outsider',PASSWORD,'player')
    if viewer:login(client,viewer)
    response=client.get(f'/matches/{match}')
    assert response.status_code==200
    assert response.headers['cache-control']=='private, no-store'
    assert response.text.count('class="lineup-private"')==(2 if visible_side is None else 1)
    for side in (0,1):
        for name in [f'{"home" if side==0 else "away"} Player {n}' for n in range(1,4)]:
            assert (name in response.text)==(side==visible_side)
    assert 'class="board-result-card"' not in response.text
    if viewer and viewer.startswith('manager_'):
        assert len(re.findall(r'<select name="player_[1-4]"',response.text))==4
        for board,player_id in enumerate(rosters[visible_side],1):
            select=re.search(r'<select name="player_'+str(board)+r'".*?</select>',response.text,re.S).group(0)
            assert f'<option value="{player_id}" selected' in select


def test_pairings_hidden_on_every_game_surface_including_direct_pgn(client,monkeypatch):
    admin,_,_,match,teams,_,_=arranged_match()
    with store.read_db() as db:
        games=[r[0] for r in db.execute('SELECT game_id FROM match_games WHERE match_id=?',(match,))]
        start=seasons._datetime(db.execute('SELECT scheduled_at FROM team_matches WHERE id=?',(match,)).fetchone()[0])
    pgn='[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 1-0'
    store.attach_pgn(games[0],pgn,actor_id=admin,reason='Early recorded game must remain private')
    for viewer in (None,'home_player_1','manager_away','commissioner'):
        if viewer:login(client,viewer)
        for game in games:
            assert client.get(f'/games/{game}').status_code==404
            assert client.get(f'/games/{game}/pgn').status_code==(404 if viewer else 401)
        for path in ['/games','/games?q=home','/games?status=finished','/games?status=scheduled',
                     '/users/home_player_1','/users/away_player_1',f'/teams/{teams[0]}',f'/teams/{teams[1]}']:
            html=client.get(path).text
            assert not any(f'href="/games/{game}"' in html for game in games),path
        if viewer=='commissioner':
            for path in ['/admin','/admin/games']:
                assert not any(f'href="/games/{game}"' in client.get(path).text for game in games)
    monkeypatch.setattr(store,'now_utc',lambda:start-timedelta(seconds=1))
    assert client.get(f'/matches/{match}').text.count('class="lineup-private"')==2
    monkeypatch.setattr(store,'now_utc',lambda:start)
    page=client.get(f'/matches/{match}').text
    assert page.count('class="lineup-board-number"')==8 and page.count('class="board-result-card"')==4
    assert 'class="lineup-private"' not in page
    for game in games:assert client.get(f'/games/{game}').status_code==200
    assert 'e4 e5' in client.get(f'/games/{games[0]}/pgn').text
    # A reschedule reinstates the embargo using the match time, even if copies differ.
    with store.transaction() as db:
        db.execute('UPDATE team_matches SET scheduled_at=? WHERE id=?',(store.iso(start+timedelta(hours=1)),match))
    assert client.get(f'/games/{games[0]}').status_code==404


def test_roster_changes_revoke_lineup_access_immediately(client):
    _,_,_,match,teams,_,_=arranged_match()
    login(client,'home_player_1')
    assert 'home Player 2' in client.get(f'/matches/{match}').text
    with store.transaction() as db:
        db.execute("UPDATE players SET owner_team_id=NULL WHERE user_id=(SELECT id FROM users WHERE username='home_player_1')")
    assert 'home Player 2' not in client.get(f'/matches/{match}').text
