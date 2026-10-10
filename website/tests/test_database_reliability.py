"""Reliability, accounting and migration regressions reproduced in the review."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from threading import Barrier

import pytest

import database as store


@pytest.fixture
def league(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'league.sqlite3')
    store.init_db()
    return store


def account(name, role='manager'):
    with store.transaction() as db:
        return db.execute('''INSERT INTO users(username,password_hash,role,created_at,
            manager_active,player_active,manager_available) VALUES(?,?,?,?,?,?,?)''',
            (name, 'unused-test-password-hash', role, store.iso(store.now_utc()),
             int(role == 'manager'), int(role != 'admin'), int(role == 'manager'))).lastrowid


def team(name='Review Team'):
    manager = account(name.replace(' ', '_'))
    tid = store.create_team(name)
    store.assign_manager(tid, manager)
    return manager, tid


def expire(*auctions):
    with store.transaction() as db:
        db.executemany('UPDATE auctions SET ends_at=? WHERE id=?',
                       [(store.iso(store.now_utc() - timedelta(seconds=1)), aid) for aid in auctions])


def test_accepting_manager_invitation_cannot_poison_open_auction(league):
    manager = account('invited_manager')
    player = store.create_player('Invited Manager', user_id=manager)
    auction = store.create_auction(player, 10, 1)
    tid = store.create_team('Vacant Squad')
    invitation = store.invite_manager(tid, manager)
    with pytest.raises(ValueError, match='open auction'):
        store.respond_invitation(manager, invitation, True)
    with store.read_db() as db:
        assert db.execute('SELECT manager_id FROM teams WHERE id=?', (tid,)).fetchone()[0] is None
        assert db.execute('SELECT is_manager_player,owner_team_id FROM players WHERE id=?', (player,)).fetchone()[:] == (0, None)
        assert db.execute('SELECT status FROM manager_invitations WHERE id=?', (invitation,)).fetchone()[0] == 'pending'
    expire(auction)
    assert store.settle_expired() == 1
    store.respond_invitation(manager, invitation, True)


def test_startup_quarantines_legacy_manager_conflict_and_keeps_service_available(league):
    manager = account('legacy_manager')
    player = store.create_player('Legacy Manager', user_id=manager)
    auction = store.create_auction(player, 10, 1)
    tid = store.create_team('Legacy Assigned Team')
    with store.transaction() as db:
        db.execute('UPDATE teams SET manager_id=? WHERE id=?', (manager, tid))
    store.init_db()
    store.init_db()
    with store.read_db() as db:
        assert db.execute('SELECT status FROM auctions WHERE id=?', (auction,)).fetchone()[0] == 'failed'
        assert db.execute('SELECT owner_team_id,is_manager_player FROM players WHERE id=?', (player,)).fetchone()[:] == (tid, 1)
        assert db.execute("SELECT count(*) FROM audit_log WHERE event='auction_failed'").fetchone()[0] == 1
    assert store.readiness()['failed_auctions'] == 1


def test_failed_auction_rolls_back_partial_debit_without_blocking_other_settlements(league):
    _manager, buyer = team()
    broken_player = store.create_player('Broken Transfer')
    healthy_player = store.create_player('Healthy Transfer')
    broken = store.create_auction(broken_player, 10, 1)
    healthy = store.create_auction(healthy_player, 10, 1)
    store.place_bid(broken, buyer, 300)
    store.place_bid(healthy, buyer, 200)
    with store.transaction() as db:
        # A late constraint failure occurs after the attempted buyer debit.
        db.execute(f'''CREATE TRIGGER reject_fixture_transfer BEFORE UPDATE OF owner_team_id ON players
            WHEN NEW.id={broken_player} BEGIN SELECT RAISE(ABORT,'Fixture ownership conflict'); END''')
    expire(broken, healthy)
    assert store.settle_expired() == 1
    with store.read_db() as db:
        assert db.execute('SELECT budget FROM teams WHERE id=?', (buyer,)).fetchone()[0] == 800
        assert db.execute('SELECT owner_team_id FROM players WHERE id=?', (broken_player,)).fetchone()[0] is None
        assert db.execute('SELECT count(*) FROM player_team_terms WHERE player_id=?', (broken_player,)).fetchone()[0] == 0
        assert db.execute('SELECT status FROM auctions WHERE id=?', (broken,)).fetchone()[0] == 'failed'
        assert db.execute('SELECT status FROM auctions WHERE id=?', (healthy,)).fetchone()[0] == 'closed'
    another = store.create_auction(store.create_player('Another Transfer'), 10, 1)
    assert store.place_bid(another, buyer, 100)
    store.init_db()  # A quarantined legacy row cannot block the next restart.


def test_admin_retry_respects_other_reservations_and_records_recovery(league):
    admin = account('commissioner', 'admin')
    _manager, buyer = team()
    broken_player = store.create_player('Quarantined Player')
    broken = store.create_auction(broken_player, 10, 1)
    store.place_bid(broken, buyer, 700)
    with store.transaction() as db:
        db.execute('UPDATE players SET is_manager_player=1 WHERE id=?', (broken_player,))
    expire(broken)
    assert store.settle_expired() == 0
    another = store.create_auction(store.create_player('Reserved Player'), 10, 1)
    store.place_bid(another, buyer, 600)
    with store.transaction() as db:
        db.execute('UPDATE players SET is_manager_player=0 WHERE id=?', (broken_player,))
    assert not store.retry_auction(broken, admin, 'Legacy manager flag repaired')
    with store.read_db() as db:
        assert db.execute('SELECT budget FROM teams WHERE id=?', (buyer,)).fetchone()[0] == 1000
        assert db.execute('SELECT status FROM auctions WHERE id=?', (broken,)).fetchone()[0] == 'failed'
    store.cancel_auction(another, admin, 'Release reservation after review')
    assert store.retry_auction(broken, admin, 'Reservation safely released')
    with store.read_db() as db:
        assert db.execute('SELECT budget FROM teams WHERE id=?', (buyer,)).fetchone()[0] == 300
        assert db.execute('SELECT status FROM auctions WHERE id=?', (broken,)).fetchone()[0] == 'closed'
        assert db.execute("SELECT count(*) FROM audit_log WHERE event='auction_retried' AND actor_id=?", (admin,)).fetchone()[0] == 2


def test_cancellation_requires_admin_and_reason_and_never_refunds_reserved_credit(league):
    manager, buyer = team()
    admin = account('commissioner', 'admin')
    auction = store.create_auction(store.create_player('Cancel Player'), 10, 1)
    store.place_bid(auction, buyer, 800)
    with pytest.raises(ValueError, match='administrators'):
        store.cancel_auction(auction, manager, 'Manager attempts cancellation')
    with pytest.raises(ValueError, match='reason'):
        store.cancel_auction(auction, admin, '')
    store.cancel_auction(auction, admin, 'Duplicate administrative listing')
    with store.read_db() as db:
        assert db.execute('SELECT budget FROM teams WHERE id=?', (buyer,)).fetchone()[0] == 1000
        assert store.reserved_credits(db, buyer) == 0
        assert db.execute('SELECT count(*) FROM bids WHERE auction_id=?', (auction,)).fetchone()[0] == 1


def test_early_admin_close_quarantines_legacy_conflict_and_records_actor(league):
    admin = account('commissioner', 'admin')
    player = store.create_player('Early Closing Player')
    auction = store.create_auction(player, 10, 24)
    with store.transaction() as db:
        db.execute('UPDATE players SET is_manager_player=1 WHERE id=?', (player,))
    assert not store.close_auction(auction, admin, 'Resolve invalid historic listing')
    with store.read_db() as db:
        assert db.execute('SELECT status FROM auctions WHERE id=?', (auction,)).fetchone()[0] == 'failed'
        entry = db.execute("SELECT * FROM audit_log WHERE event='auction_close_requested'").fetchone()
        assert entry['actor_id'] == admin
        assert entry['reason'] == 'Resolve invalid historic listing'


def test_old_free_agent_result_never_changes_team_after_a_purchase(league):
    _manager, buyer = team()
    white, black = store.create_player('Historical White'), store.create_player('Historical Black')
    game = store.create_game(white, black, '2020-01-05T12:00:00+00:00')
    store.update_game_result(game, '1-0')
    auction = store.create_auction(white, 10, 1)
    store.place_bid(auction, buyer, 100)
    expire(auction)
    store.settle_expired()
    store.update_game_result(game, '1/2-1/2')
    with store.read_db() as db:
        assert store._team_at(db, white, '2020-01-05T12:00:00+00:00') is None
        assert db.execute('SELECT white_team_id FROM games WHERE id=?', (game,)).fetchone()[0] is None
        assert db.execute('SELECT owner_team_id FROM players WHERE id=?', (white,)).fetchone()[0] == buyer


def test_future_fixture_confirms_actual_match_membership_and_remains_confirmed_when_cleared(league, monkeypatch):
    clock = [datetime(2026, 1, 1, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr(store, 'now_utc', lambda: clock[0])
    _seller, old_team = team('Scheduling Team')
    buyer, new_team = team('Playing Team')
    white, black = store.create_player('Scheduled White'), store.create_player('Scheduled Black')
    with store.transaction() as db:
        db.execute('UPDATE players SET owner_team_id=? WHERE id=?', (old_team, white))
        store._start_player_term(db, white, old_team)
    game = store.create_game(white, black, '2026-01-10T12:00:00+00:00')
    with store.read_db() as db:
        assert db.execute('SELECT white_team_id,attribution_confirmed FROM games WHERE id=?', (game,)).fetchone()[:] == (old_team, 0)
    clock[0] = datetime(2026, 1, 5, 12, tzinfo=timezone.utc)
    auction = store.create_auction(white, 10, 1)
    store.place_bid(auction, new_team, 100)
    assert store.close_auction(auction)
    clock[0] = datetime(2026, 1, 10, 13, tzinfo=timezone.utc)
    store.update_game_result(game, '1-0')
    with store.read_db() as db:
        assert db.execute('SELECT white_team_id,attribution_confirmed FROM games WHERE id=?', (game,)).fetchone()[:] == (new_team, 1)
    clock[0] = datetime(2026, 1, 20, 12, tzinfo=timezone.utc)
    store.kick_player(buyer, white)
    store.update_game_result(game, '*')
    store.update_game_result(game, '1/2-1/2')
    with store.read_db() as db:
        assert db.execute('SELECT white_team_id,attribution_confirmed FROM games WHERE id=?', (game,)).fetchone()[:] == (new_team, 1)


def test_manual_adjustment_survives_reversible_game_results_with_audit(league):
    admin = account('commissioner', 'admin')
    white, black = store.create_player('Scoring White'), store.create_player('Scoring Black')
    game = store.create_game(white, black, '2026-01-05T12:00:00+00:00')
    store.update_game_result(game, '1-0', actor_id=admin, reason='Verified club result')
    assert store.adjust_player_points(white, 2, admin, 'Independent tournament award') == 5
    store.update_game_result(game, '*', actor_id=admin, reason='Game was recorded twice')
    store.update_game_result(game, '*', actor_id=admin, reason='Confirm duplicate removed')
    with store.read_db() as db:
        assert db.execute('SELECT points FROM players WHERE id=?', (white,)).fetchone()[0] == 2
        assert db.execute('SELECT SUM(amount) FROM points_ledger WHERE player_id=?', (white,)).fetchone()[0] == 2
        audit = db.execute("SELECT * FROM audit_log WHERE event='points_adjusted'").fetchone()
        assert audit['actor_id'] == admin
        assert audit['reason'] == 'Independent tournament award'
        assert json.loads(audit['after_json']) == {'delta': 2, 'points': 5}
    with pytest.raises(ValueError, match='administrators'):
        store.adjust_player_points(white, 10, account('ordinary_member', 'player'), 'Forged score correction')


def test_legacy_ledger_migration_preserves_totals_game_awards_ids_and_bid_references(monkeypatch, tmp_path):
    path = tmp_path / 'v23.sqlite3'
    monkeypatch.setattr(store, 'DB_PATH', path)
    old_schema = store.SCHEMA.replace("('open','closed','failed','cancelled')", "('open','closed')").replace('closed_at TEXT,\n    failure_reason TEXT', 'closed_at TEXT')
    old_schema = old_schema.replace('    attribution_confirmed INTEGER NOT NULL DEFAULT 0 CHECK(attribution_confirmed IN (0,1)),\n', '')
    with sqlite3.connect(path) as db:
        db.executescript(old_schema)
        for pid, points in ((7, 5), (9, 10)):
            db.execute('INSERT INTO players(id,name,points,created_at) VALUES(?,?,?,?)', (pid, f'Legacy {pid}', points, '2020-01-01'))
        db.execute('''INSERT INTO games(id,white_player_id,black_player_id,scheduled_at,result,white_award,created_at)
            VALUES(13,7,9,'2020-01-02','1-0',3,'2020-01-01')''')
        db.execute("INSERT INTO auctions(id,player_id,starting_price,ends_at,created_at) VALUES(17,7,10,'2099-01-01','2020-01-01')")
        db.execute("INSERT INTO teams(id,name,created_at) VALUES(21,'Legacy Team','2020-01-01')")
        db.execute("INSERT INTO bids(id,auction_id,team_id,amount,placed_at) VALUES(25,17,21,11,'2020-01-01')")
    store.init_db()
    store.init_db()
    with store.read_db() as db:
        assert db.execute('SELECT id,points FROM players ORDER BY id').fetchall()[0][:] == (7, 5)
        assert db.execute('SELECT auction_id,team_id FROM bids WHERE id=25').fetchone()[:] == (17, 21)
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute("SELECT count(*) FROM points_ledger WHERE source='legacy_adjustment'").fetchone()[0] == 2
        assert db.execute('SELECT attribution_confirmed FROM games WHERE id=13').fetchone()[0] == 1
    store.update_game_result(13, '*')
    with store.read_db() as db:
        assert db.execute('SELECT points FROM players WHERE id=7').fetchone()[0] == 2
        assert db.execute('SELECT points FROM players WHERE id=9').fetchone()[0] == 10
    backup = path.with_name(path.name + '.pre-v24.bak')
    assert backup.exists()
    assert backup.stat().st_mode & 0o777 == 0o600
    assert path.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(backup) as db:
        assert db.execute('SELECT points FROM players WHERE id=7').fetchone()[0] == 5


def test_role_quitting_never_activates_an_unapproved_opposite_role(league):
    admin = account('commissioner', 'admin')
    player = account('player_only', 'player')
    store.quit_role(player, 'player')
    with store.read_db() as db:
        assert db.execute('SELECT manager_active,player_active FROM users WHERE id=?', (player,)).fetchone()[:] == (0, 0)
    store.request_role(player, 'manager')
    with store.read_db() as db:
        request = db.execute('SELECT id FROM role_requests WHERE user_id=?', (player,)).fetchone()[0]
    store.review_role_request(admin, request, True)
    store.quit_role(player, 'manager')
    with store.read_db() as db:
        assert db.execute('SELECT manager_active,player_active FROM users WHERE id=?', (player,)).fetchone()[:] == (0, 0)


def test_readiness_rejects_missing_or_empty_database_without_creating_it(league, monkeypatch, tmp_path):
    assert store.readiness()['database'] == 'ready'
    missing = tmp_path / 'missing.sqlite3'
    monkeypatch.setattr(store, 'DB_PATH', missing)
    with pytest.raises(sqlite3.OperationalError):
        store.readiness()
    assert not missing.exists()
    sqlite3.connect(missing).close()
    with pytest.raises(sqlite3.DatabaseError, match='tables'):
        store.readiness()


def test_concurrent_bids_cannot_overspend_reserved_budget(league):
    _manager, buyer = team()
    auctions = [store.create_auction(store.create_player(f'Race Player {i}'), 10, 1) for i in range(2)]
    barrier = Barrier(2)

    def bid(aid):
        barrier.wait()
        try:
            store.place_bid(aid, buyer, 700)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(bid, auctions)) == [False, True]
    with store.read_db() as db:
        assert store.reserved_credits(db, buyer) == 700


def test_concurrent_point_adjustments_do_not_lose_updates(league):
    admin = account('commissioner', 'admin')
    player = store.create_player('Concurrent Scorer')
    barrier = Barrier(2)

    def award(amount):
        barrier.wait()
        return store.adjust_player_points(player, amount, admin, 'Concurrent independent award')

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(award, (2, 3)))
    with store.read_db() as db:
        assert db.execute('SELECT points FROM players WHERE id=?', (player,)).fetchone()[0] == 5
        assert db.execute("SELECT count(*) FROM points_ledger WHERE source='manual_adjustment'").fetchone()[0] == 2
