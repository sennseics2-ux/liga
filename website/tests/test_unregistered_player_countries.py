"""Country storage, profile flags, admin authorization and upgrades."""
import pytest
import database as store
from test_league import client, post, seed_admin, login_admin, new_team


def test_namesakes_keep_their_own_country_and_flag(client):
    portugal=store.create_player('Same Name',country='PT')
    france=store.create_player('Same Name',country='France')
    for player,name,code in [(portugal,'Portugal','pt'),(france,'France','fr')]:
        page=client.get(f'/players/{player}')
        assert page.status_code==200
        assert f'/static/flags/countries/{code}.svg' in page.text
        assert f'<span data-no-i18n>{name}</span>' in page.text
        assert f'action="/admin/players/{player}/country"' not in page.text
    unknown=store.create_player('Country Unknown')
    assert 'profile-country-flag' not in client.get(f'/players/{unknown}').text


def test_admin_can_update_and_clear_unregistered_player_country(client):
    player=store.create_player('Guest Player',country='Portugal')
    seed_admin();login_admin(client)
    page=client.get(f'/players/{player}').text
    assert 'id="player-country-select"' in page
    assert 'value="Portugal" selected' in page
    assert post(client,f'/admin/players/{player}/country',country='France').status_code==200
    assert '/static/flags/countries/fr.svg' in client.get(f'/players/{player}').text
    post(client,f'/admin/players/{player}/country',country='Unknown Country')
    with store.read_db() as db:
        assert db.execute('SELECT country FROM players WHERE id=?',(player,)).fetchone()[0]=='France'
        assert db.execute("SELECT count(*) FROM audit_log WHERE event='player_country_updated'").fetchone()[0]==1
    post(client,f'/admin/players/{player}/country',country='')
    assert 'profile-country-flag' not in client.get(f'/players/{player}').text


def test_country_edits_require_admin_and_do_not_override_linked_accounts(client):
    viewer=store.create_account('CountryViewer','CountryPass123!','player')
    player=store.create_player('Guest Player')
    post(client,'/login',username='CountryViewer',password='CountryPass123!')
    assert post(client,f'/admin/players/{player}/country',country='France').status_code==403
    with pytest.raises(PermissionError):store.update_player_country(player,'France',viewer)
    seed_admin();login_admin(client)
    manager,_=new_team('CountryCaptain','Country Team')
    with store.read_db() as db:
        linked=db.execute('SELECT id FROM players WHERE user_id=?',(manager,)).fetchone()[0]
        admin=db.execute("SELECT id FROM users WHERE username='commissioner'").fetchone()[0]
    with pytest.raises(ValueError,match='linked account'):store.update_player_country(linked,'France',admin)


def test_upgrade_keeps_existing_players_and_can_be_repeated(client):
    player=store.create_player('Existing Guest',rating=1700)
    with store.transaction() as db:
        db.execute('ALTER TABLE players DROP COLUMN country')
        db.execute("DELETE FROM schema_migrations WHERE version IN ('v103_player_countries','v108_unregistered_player_fide')")
    store.init_db()
    assert store.DB_PATH.with_name(store.DB_PATH.name+'.pre-v103.bak').exists()
    with store.read_db() as db:
        row=db.execute('SELECT name,rating,country FROM players WHERE id=?',(player,)).fetchone()
        assert tuple(row)==('Existing Guest',1700,'')
    seed_admin()
    with store.read_db() as db:admin=db.execute("SELECT id FROM users WHERE username='commissioner'").fetchone()[0]
    store.update_player_country(player,'Portugal',admin)
    store.init_db()
    with store.read_db() as db:
        assert db.execute('SELECT country FROM players WHERE id=?',(player,)).fetchone()[0]=='Portugal'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
