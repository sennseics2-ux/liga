"""Player identity is numeric, independent of account linkage and display names."""
from html.parser import HTMLParser
import re
import database as store
from test_league import client, new_team, post, seed_admin, login_admin


class ProfileLinks(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links=[]
        self.current=None
        self.feed(text)
    def handle_starttag(self,tag,attrs):
        if tag=='a':
            assert self.current is None, 'Nested anchors break player/card navigation'
            self.current=[dict(attrs).get('href'), '']
    def handle_data(self,data):
        if self.current is not None:
            self.current[1]+=data
    def handle_endtag(self,tag):
        if tag=='a':
            if self.current is not None:self.links.append(self.current)
            self.current=None


def test_duplicate_names_have_separate_public_profiles_and_results(client):
    first = store.create_player('Same Name', rating=1700)
    second = store.create_player('Same Name', rating=1900)
    other = store.create_player('Opponent')
    game = store.create_game(first, other, '2026-10-09T18:00:00+00:00')
    store.update_game_result(game, '1-0')
    for player, rating, count in [(first,1700,1),(second,1900,0)]:
        page = client.get(f'/players/{player}')
        assert page.status_code == 200
        assert re.search(r'career-games-heading.*?<strong data-no-i18n>'+str(count)+r'</strong>',page.text)
        assert str(rating) in page.text
        assert 'class="role-settings"' not in page.text
        assert 'class="profile-tabs"' not in page.text
        assert f'/games?player={player}' in page.text
    games = client.get(f'/games?player={second}').text
    assert f'data-game-id="{game}"' not in games
    assert client.get('/players/999999').status_code == 404
    assert client.get('/players/9223372036854775808').status_code == 404


def test_numeric_linked_player_resolves_to_existing_member(client):
    manager, team = new_team('linked-player', 'Linked Team')
    with store.read_db() as db:
        player = db.execute('SELECT id FROM players WHERE user_id=?',(manager,)).fetchone()[0]
    response = client.get(f'/players/{player}',follow_redirects=False)
    assert response.status_code == 307
    assert response.headers['location'] == '/users/linked-player'
    assert client.get(response.headers['location']).status_code == 200


def test_unlinked_names_link_from_directory_rosters_auctions_and_games(client):
    _, team = new_team('numeric-captain', 'Numeric Team')
    player = store.create_player('Unlinked Player',rating=1500)
    opponent = store.create_player('Unlinked Opponent')
    with store.transaction() as db:
        db.execute('UPDATE players SET owner_team_id=? WHERE id=?',(team,player))
        store._start_player_term(db,player,team)
    auction = store.create_auction(player,50,24)
    game = store.create_game(player,opponent,'2026-10-09T18:00:00+00:00')
    for path in ['/players',f'/teams/{team}','/auctions',f'/auctions/{auction}','/', '/games',f'/games/{game}']:
        response = client.get(path)
        assert response.status_code == 200
        links = ProfileLinks(response.text).links
        assert [f'/players/{player}','Unlinked Player'] in links,path
    assert f'data-player-profile="/players/{player}"' in client.get('/players').text


def test_admin_player_and_game_list_names_open_numeric_profiles(client):
    seed_admin()
    first = store.create_player('Admin Listed Guest')
    second = store.create_player('Admin Opponent')
    store.create_game(first,second,'2026-10-09T18:00:00+00:00')
    store.create_auction(first,50,24)
    login_admin(client)
    for path in ['/admin','/admin/players']:
        response = client.get(path)
        assert response.status_code == 200
        links = ProfileLinks(response.text).links
        assert [f'/players/{first}','Admin Listed Guest'] in links,path
