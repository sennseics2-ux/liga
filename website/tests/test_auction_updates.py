"""Auction snapshot privacy, input bounds and settlement/ownership regressions."""
from datetime import timedelta

import pytest

import database as store
from test_league import client, post, token


PUBLIC_FIELDS = {'id', 'status', 'starting_price', 'bid_count', 'high_bid',
                 'high_bid_team_id', 'minimum'}


def seed_market():
    first_manager = store.create_account('snapshot-first', 'SnapshotPassphrase123!', 'manager')
    second_manager = store.create_account('snapshot-second', 'SnapshotPassphrase123!', 'manager')
    first_team, second_team = store.create_team('Snapshot First'), store.create_team('Snapshot Second')
    store.assign_manager(first_team, first_manager)
    store.assign_manager(second_team, second_manager)
    first = store.create_auction(store.create_player('Snapshot Player One'), 10, 24)
    second = store.create_auction(store.create_player('Snapshot Player Two'), 20, 24)
    with store.transaction() as db:
        db.execute('UPDATE teams SET budget=789 WHERE id=?', (second_team,))
    store.place_bid(first, first_team, 100)
    store.place_bid(first, second_team, 150)
    store.place_bid(second, first_team, 200)
    return first_manager, second_manager, first_team, second_team, first, second


def snapshot(client, ids=''):
    response = client.get('/api/auctions/snapshot', params={'ids': ids})
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['vary'] == 'Cookie'
    return response.json()


def test_anonymous_snapshot_contains_public_bid_totals_only(client):
    _, _, _, second_team, first, second = seed_market()
    data = snapshot(client, f'{first},{second},{first}')
    assert data['viewer_team_id'] is None and data['available_credits'] is None
    assert len(data['auctions']) == 2
    assert all(set(item) == PUBLIC_FIELDS for item in data['auctions'])
    assert data['auctions'][0]['high_bid'] == 150
    assert data['auctions'][0]['high_bid_team_id'] == second_team
    assert data['auctions'][0]['bid_count'] == 2
    assert data['auctions'][0]['minimum'] == 200
    assert data == snapshot(client)


def test_assigned_manager_sees_only_own_available_funds_and_bid(client):
    _, _, first_team, second_team, first, second = seed_market()
    post(client, '/login', username='snapshot-first', password='SnapshotPassphrase123!')
    data = snapshot(client, f'{first},{second}')
    assert data['viewer_team_id'] == first_team
    assert data['available_credits'] == 800
    records = {item['id']: item for item in data['auctions']}
    assert set(records[first]) == PUBLIC_FIELDS | {'available', 'my_bid'}
    assert records[first]['my_bid'] == 100 and records[first]['available'] == 800
    assert records[second]['my_bid'] == 200 and records[second]['available'] == 1000
    # Extra query values cannot select another manager's private finances.
    response = client.get('/api/auctions/snapshot', params={
        'ids': f'{first},{second}', 'team_id': second_team, 'viewer_team_id': second_team})
    assert response.json() == data
    assert 'budget' not in str(data) and 'password' not in str(data)

    post(client, '/logout')
    post(client, '/login', username='snapshot-second', password='SnapshotPassphrase123!')
    other = snapshot(client, f'{first},{second}')
    records = {item['id']: item for item in other['auctions']}
    assert other['viewer_team_id'] == second_team and other['available_credits'] == 639
    assert records[first]['my_bid'] == 150 and records[first]['available'] == 789
    assert records[second]['my_bid'] is None and records[second]['available'] == 639


def test_player_and_revoked_manager_session_do_not_receive_private_finances(client):
    first_manager, _, _, _, first, second = seed_market()
    store.create_account('snapshot-player', 'SnapshotPassphrase123!', 'player')
    post(client, '/login', username='snapshot-player', password='SnapshotPassphrase123!')
    player = snapshot(client, f'{first},{second}')
    assert player['viewer_team_id'] is None and player['available_credits'] is None
    assert all(set(item) == PUBLIC_FIELDS for item in player['auctions'])
    post(client, '/logout')
    post(client, '/login', username='snapshot-first', password='SnapshotPassphrase123!')
    assert snapshot(client)['viewer_team_id'] is not None
    with store.transaction() as db:
        db.execute('UPDATE users SET auth_version=auth_version+1 WHERE id=?', (first_manager,))
    revoked = snapshot(client)
    assert revoked['viewer_team_id'] is None and revoked['available_credits'] is None
    assert all(set(item) == PUBLIC_FIELDS for item in revoked['auctions'])


@pytest.mark.parametrize('ids', ['0', '-1', '1.0', '1e2', '1,,2', '1,', ',1',
    ' 1', '1 OR 1=1', '9223372036854775808', '9' * 1201, ','.join(['1'] * 101)])
def test_snapshot_rejects_invalid_or_unbounded_identifier_lists(client, ids):
    response = client.get('/api/auctions/snapshot', params={'ids': ids})
    assert response.status_code == 400
    assert 'detail' in response.json()


def test_snapshot_accepts_bounded_unknown_identifiers(client):
    assert snapshot(client, ','.join(str(number) for number in range(1, 101)))['auctions'] == []


def test_snapshot_settles_expired_auctions_and_contains_no_quarantine_details(client):
    manager = store.create_account('snapshot-expiry', 'SnapshotPassphrase123!', 'manager')
    team = store.create_team('Snapshot Expiry')
    store.assign_manager(team, manager)
    broken_player = store.create_player('Snapshot Legacy Conflict')
    broken = store.create_auction(broken_player, 10, 24)
    healthy_player = store.create_player('Snapshot Valid Transfer')
    healthy = store.create_auction(healthy_player, 10, 24)
    store.place_bid(healthy, team, 25)
    post(client, '/login', username='snapshot-expiry', password='SnapshotPassphrase123!')
    csrf = token(client)
    with store.transaction() as db:
        db.execute('UPDATE players SET is_manager_player=1 WHERE id=?', (broken_player,))
        db.execute('UPDATE auctions SET ends_at=? WHERE id IN (?,?)',
                   (store.iso(store.now_utc() - timedelta(seconds=1)), broken, healthy))
    data = snapshot(client, f'{broken},{healthy}')
    records = {item['id']: item for item in data['auctions']}
    assert records[broken]['status'] == 'failed'
    assert records[healthy]['status'] == 'closed'
    assert data['available_credits'] == 975
    assert all('failure_reason' not in item for item in records.values())
    assert snapshot(client)['auctions'] == []
    # A stale tab cannot place another bid after polling settled the expiry.
    response = client.post(f'/auctions/{healthy}/bid', data={'csrf': csrf, 'amount': '26'},
                           follow_redirects=False)
    assert response.status_code == 303
    with store.read_db() as db:
        assert db.execute('SELECT count(*) FROM bids WHERE auction_id=?', (healthy,)).fetchone()[0] == 1
        assert db.execute('SELECT budget FROM teams WHERE id=?', (team,)).fetchone()[0] == 975


def test_reassigned_manager_cannot_bid_with_previously_captured_team(client):
    previous = store.create_account('snapshot-previous', 'SnapshotPassphrase123!', 'manager')
    current = store.create_account('snapshot-current', 'SnapshotPassphrase123!', 'manager')
    team = store.create_team('Snapshot Reassigned')
    store.assign_manager(team, previous)
    auction = store.create_auction(store.create_player('Snapshot Reassignment Player'), 10, 24)
    store.assign_manager(team, current)
    with pytest.raises(ValueError):
        store.place_bid(auction, team, 25, manager_id=previous)
    with store.read_db() as db:
        assert db.execute('SELECT count(*) FROM bids WHERE auction_id=?', (auction,)).fetchone()[0] == 0
    assert store.place_bid(auction, team, 25, manager_id=current)
    with store.transaction() as db:
        db.execute('UPDATE users SET manager_active=0 WHERE id=?', (current,))
    with pytest.raises(ValueError):
        store.place_bid(auction, team, 30, manager_id=current)


def test_first_bid_and_fifty_credit_increment_match_form_and_snapshot(client):
    _, _, first_team, second_team, _, _ = seed_market()
    auction = store.create_auction(store.create_player('Increment Player'), 73, 24)
    assert snapshot(client, str(auction))['auctions'][0]['minimum'] == 73
    with pytest.raises(ValueError, match='minimum bid is 73'):
        store.place_bid(auction, first_team, 72)
    store.place_bid(auction, first_team, 73)
    for amount in (74, 122):
        with pytest.raises(ValueError, match='minimum bid is 123'):
            store.place_bid(auction, second_team, amount)
    assert snapshot(client, str(auction))['auctions'][0]['minimum'] == 123
    post(client, '/login', username='snapshot-second', password='SnapshotPassphrase123!')
    assert 'min="123"' in client.get(f'/auctions/{auction}').text
    post(client, f'/auctions/{auction}/bid', amount='122')
    assert snapshot(client, str(auction))['auctions'][0]['bid_count'] == 1
    store.place_bid(auction, second_team, 123)
    store.place_bid(auction, first_team, 180)
    assert snapshot(client, str(auction))['auctions'][0]['minimum'] == 230
