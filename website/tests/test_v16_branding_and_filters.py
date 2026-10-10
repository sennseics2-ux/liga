from test_league import client, new_team
import database as store


def test_empty_numeric_directory_filters_do_not_error(client):
    _, team_id = new_team('filtermgr', 'Filter Team')
    player_id = store.create_player('Filter Example', 'Filter Club', 2050)
    with store.transaction() as db:
        db.execute('UPDATE players SET owner_team_id=?, points=? WHERE id=?', (team_id, 12, player_id))
        store._start_player_term(db, player_id, team_id)
    response = client.get('/players', params={'sort': 'rating_desc', 'min_rating': ''})
    assert response.status_code == 200
    assert 'Filter Example' in response.text
    response = client.get('/teams', params={'sort': 'players_desc', 'min_players': ''})
    assert response.status_code == 200
    assert 'Filter Team' in response.text


def test_header_uses_liga_sx_aac_branding_and_favicon(client):
    response = client.get('/')
    assert response.status_code == 200
    assert 'Liga SX-AAC' in response.text
    assert '/static/sx-aac-logo.png' in response.text
    assert '/static/favicon.ico' in response.text
