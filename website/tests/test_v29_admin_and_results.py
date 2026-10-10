"""Administrative workspaces and player-perspective game outcomes."""
from datetime import timedelta
import re
import database as store
from test_league import client,seed_admin,login_admin,post


def seed_player_results():
    with store.read_db() as db:admin=db.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
    white_user=store.create_account('WhiteResults','ResultsPassword123!','player')
    black_user=store.create_account('BlackResults','ResultsPassword123!','player')
    white=store.create_player('White Results Player',user_id=white_user)
    black=store.create_player('Black Results Player',user_id=black_user)
    games=[]
    for wp,bp in [(white,black),(black,white)]:
        for result in ['1-0','0-1','1/2-1/2','*']:
            game=store.create_game(wp,bp,store.iso(store.now_utc()+timedelta(days=len(games)+1)),'Player result fixture')
            if result!='*':store.update_game_result(game,result,actor_id=admin,reason='Seed perspective fixture')
            games.append(game)
    return white,black,games


def test_result_colours_and_labels_follow_player_for_either_piece_colour(client):
    seed_admin();seed_player_results()
    white=client.get('/users/WhiteResults').text
    black=client.get('/users/BlackResults').text
    pattern=r'<span class="player-game-result player-result-(\w+)">(?:<strong data-no-i18n>(.*?)</strong>)?<span data-i18n="([^\"]+)">'
    wr=re.findall(pattern,white);br=re.findall(pattern,black)
    assert [r[0] for r in wr]==['upcoming','draw','win','loss','upcoming','draw','loss','win']
    assert [r[0] for r in br]==['upcoming','draw','loss','win','upcoming','draw','win','loss']
    assert all(label=={'win':'Won','loss':'Lost','draw':'Draw','upcoming':'Upcoming'}[outcome] for outcome,result,label in wr+br)
    assert [r[1] for r in wr]==[r[1] for r in br] # recorded scores remain identical


def test_admin_overview_links_to_workspaces_and_actions_stay_in_context(client):
    seed_admin();login_admin(client)
    assert 'admin-dashboard-grid' in client.get('/admin').text
    for path in ['/admin/teams','/admin/roles','/admin/players','/admin/games','/admin/seasons','/admin/accounts']:
        assert f'href="{path}"' in client.get('/admin').text
        assert client.get(path).status_code==200
    response=post(client,'/admin/teams',name='New Dashboard Team')
    assert response.url.path=='/admin/teams'
    assert 'New Dashboard Team' in response.text
    assert 'class="credit-symbol"' in response.text
    assert 'admin-attention-total' in client.get('/admin').text
    overview=client.get('/admin').text
    assert 'Teams without a captain' in overview
    assert 'method="post" action="/admin/teams"' not in overview
    assert 'id="teams"' not in client.get('/admin/roles').text
    with store.read_db() as db:
        assert db.execute('SELECT budget FROM teams WHERE name=?',('New Dashboard Team',)).fetchone()[0]==1000
