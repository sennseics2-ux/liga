"""Web permissions, form validation, and audited accounting integration."""
import re

import database as store
from test_league import client, seed_admin, login_admin, post, register, token


def test_signed_adjustment_and_result_correction_preserve_independent_awards(client):
    seed_admin()
    login_admin(client)
    white=store.create_player('Awarded Player')
    black=store.create_player('Opponent Player')
    game=store.create_game(white,black,'2026-02-10T12:00')
    assert post(client,f'/admin/games/{game}/result',result='1-0',reason='Confirmed club result').status_code==200
    assert post(client,f'/admin/players/{white}/points',adjustment='5',reason='Club attendance award').status_code==200
    assert post(client,f'/admin/games/{game}/result',result='1/2-1/2',reason='Corrected signed scoresheet').status_code==200
    with store.read_db() as db:
        assert db.execute('SELECT points FROM players WHERE id=?',(white,)).fetchone()[0]==6
        assert db.execute('SELECT points FROM players WHERE id=?',(black,)).fetchone()[0]==1
        adjustment=db.execute("SELECT * FROM audit_log WHERE event='points_adjusted'").fetchone()
        admin=db.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
        assert adjustment['actor_id']==admin and adjustment['reason']=='Club attendance award'
        assert db.execute("SELECT COUNT(*) FROM audit_log WHERE event='game_result_updated' AND actor_id=?",(admin,)).fetchone()[0]==2
    assert 'Club attendance award' in client.get('/admin').text


def test_total_overwrite_is_rejected_and_adjustment_requires_reason(client):
    seed_admin();login_admin(client)
    player=store.create_player('Protected Points')
    response=client.post(f'/admin/players/{player}/points',data={'csrf':token(client,'/'),'points':'999'})
    assert response.status_code==400
    assert 'reason' in post(client,f'/admin/players/{player}/points',adjustment='10',reason='').text
    with store.read_db() as db:
        assert db.execute('SELECT points FROM players WHERE id=?',(player,)).fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM points_ledger WHERE source='manual_adjustment'").fetchone()[0]==0


def test_regular_member_cannot_adjust_points_or_cancel_or_retry_auctions(client):
    register(client,'member_restrictions','player')
    player=store.create_player('Restricted Player')
    auction=store.create_auction(player,10,1)
    for url,data in (
        (f'/admin/players/{player}/points',{'adjustment':'50','reason':'Unauthorized adjustment'}),
        (f'/admin/auctions/{auction}/cancel',{'reason':'Unauthorized cancellation'}),
        (f'/admin/auctions/{auction}/retry',{'reason':'Unauthorized retry'}),
    ):
        assert post(client,url,**data).status_code==403
    with store.read_db() as db:
        assert db.execute('SELECT points FROM players WHERE id=?',(player,)).fetchone()[0]==0
        assert db.execute('SELECT status FROM auctions WHERE id=?',(auction,)).fetchone()[0]=='open'


def test_admin_can_select_an_active_linked_player_for_an_auction(client):
    uid=store.create_account('linked_member','LinkedMember123!','player')
    player=store.create_player('Linked Club Player',user_id=uid)
    seed_admin();login_admin(client)
    html=client.get('/admin/players').text
    select=re.search(r'<select[^>]*name="player_id"[^>]*>(.*?)</select>',html,re.S).group(1)
    assert f'value="{player}"' in select and 'Linked Club Player' in select
    assert post(client,'/admin/auctions',player_id=str(player),starting_price='10',duration_hours='1').status_code==200
    with store.read_db() as db:
        assert db.execute("SELECT count(*) FROM auctions WHERE player_id=? AND status='open'",(player,)).fetchone()[0]==1
