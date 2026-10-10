"""Auction accounting and recovery; database.py retains the public facade.

Persistence imports are local so callers and tests can configure database.DB_PATH
and its clock/transaction helpers without circular initialization.
"""
from datetime import timedelta
import logging
import sqlite3

logger = logging.getLogger(__name__)


def highest_bid(db, auction_id):
    return db.execute('''SELECT b.*, t.name AS team_name FROM bids b
        JOIN teams t ON t.id=b.team_id WHERE b.auction_id=? ORDER BY b.amount DESC,b.id ASC LIMIT 1''',
                      (auction_id,)).fetchone()


def reserved_credits(db, team_id, exclude_auction=None):
    import database as store
    row = db.execute('''SELECT COALESCE(SUM(b.amount),0) AS amount FROM bids b
      JOIN auctions a ON a.id=b.auction_id
      WHERE a.status='open' AND a.ends_at > ? AND b.team_id=?
        AND (? IS NULL OR a.id != ?)
        AND b.id = (SELECT b2.id FROM bids b2 WHERE b2.auction_id=a.id
                    ORDER BY b2.amount DESC,b2.id ASC LIMIT 1)''',
                     (store.iso(store.now_utc()), team_id, exclude_auction, exclude_auction)).fetchone()
    return row['amount']


def settle_auction(db, auction_id):
    import database as store
    auction = db.execute('SELECT * FROM auctions WHERE id=?', (auction_id,)).fetchone()
    if not auction or auction['status'] != 'open':
        return False
    player = db.execute('SELECT is_manager_player,owner_team_id FROM players WHERE id=?', (auction['player_id'],)).fetchone()
    if not player:
        raise ValueError('The auction player no longer exists.')
    if player['is_manager_player']:
        raise ValueError('Manager-players cannot be transferred.')
    if player['owner_team_id'] != auction['seller_team_id']:
        raise ValueError('The player owner changed after the auction was opened.')
    top = store.highest_bid(db, auction_id)
    if top:
        team = db.execute('SELECT budget FROM teams WHERE id=?', (top['team_id'],)).fetchone()
        if not team or top['amount'] > team['budget'] - store.reserved_credits(db, top['team_id'], exclude_auction=auction_id):
            raise ValueError('Cannot settle auction: winning team has insufficient unreserved budget.')
        changed = db.execute('UPDATE teams SET budget=budget-? WHERE id=? AND budget>=?',
                             (top['amount'], top['team_id'], top['amount']))
        if changed.rowcount != 1:
            raise RuntimeError('Cannot settle auction: winning team has insufficient budget')
        if store._roster_tracking_ready(db):
            # The seller was known to own the player when the auction opened.
            previous=db.execute('SELECT id FROM player_team_terms WHERE player_id=? AND ended_at IS NULL',(auction['player_id'],)).fetchone()
            if not previous and auction['seller_team_id'] is not None:
                store._start_player_term(db,auction['player_id'],auction['seller_team_id'],auction['created_at'],'auction listing')
            store._stop_player_term(db,auction['player_id'],reason='transferred')
            store._start_player_term(db,auction['player_id'],top['team_id'],source='auction win')
        db.execute('UPDATE players SET owner_team_id=? WHERE id=?', (top['team_id'], auction['player_id']))
        if auction['seller_team_id'] is not None:
            db.execute('UPDATE teams SET budget=budget+? WHERE id=?',
                       (top['amount'], auction['seller_team_id']))
        db.execute('UPDATE auctions SET status=\'closed\',winner_team_id=?,final_price=?,closed_at=? WHERE id=?',
                   (top['team_id'], top['amount'], store.iso(store.now_utc()), auction_id))
    else:
        db.execute('UPDATE auctions SET status=\'closed\', closed_at=? WHERE id=?', (store.iso(store.now_utc()), auction_id))
    store._audit(db, 'auction_settled', 'auction', auction_id,
           after={'winner_team_id': top['team_id'] if top else None, 'final_price': top['amount'] if top else None})
    return True


def _fail_auction(db, auction_id, reason, actor_id=None):
    import database as store
    reason = str(reason)[:500]
    db.execute("UPDATE auctions SET status='failed',failure_reason=?,closed_at=NULL WHERE id=?", (reason, auction_id))
    store._audit(db, 'auction_failed', 'auction', auction_id, actor_id, reason,
           after={'status': 'failed', 'failure_reason': reason})
    logger.warning('Auction %s quarantined: %s', auction_id, reason)


def _settle_isolated(db, auction_id):
    """Roll back an individual auction before recording its recovery alert.

    Infrastructure errors still propagate; inconsistent legacy business records
    cannot roll back other settlements or prevent the application from starting.
    """
    import database as store
    db.execute('SAVEPOINT auction_settlement')
    try:
        settled = store.settle_auction(db, auction_id)
    except (ValueError, RuntimeError, sqlite3.IntegrityError) as exc:
        db.execute('ROLLBACK TO auction_settlement')
        db.execute('RELEASE auction_settlement')
        store._fail_auction(db, auction_id, str(exc))
        return False
    else:
        db.execute('RELEASE auction_settlement')
        return settled


def _settle_expired(db):
    import database as store
    rows = db.execute("SELECT id FROM auctions WHERE status='open' AND ends_at<=? ORDER BY ends_at,id",
                      (store.iso(store.now_utc()),)).fetchall()
    return sum(store._settle_isolated(db, row['id']) for row in rows)


def settle_expired():
    import database as store
    with store.transaction() as db:
        return store._settle_expired(db)


def close_auction(auction_id, actor_id=None, reason='Closed by administrator'):
    """Close early on administrator request, quarantining a broken transfer."""
    import database as store
    reason = store._reason(reason)
    with store.transaction() as db:
        if actor_id is not None:
            store._admin_actor(db, actor_id)
        auction = db.execute('SELECT status,ends_at FROM auctions WHERE id=?', (auction_id,)).fetchone()
        if not auction or auction['status'] != 'open':
            raise ValueError('Only an open auction can be closed.')
        db.execute('UPDATE auctions SET ends_at=? WHERE id=?', (store.iso(store.now_utc()), auction_id))
        store._audit(db, 'auction_close_requested', 'auction', auction_id, actor_id, reason,
               before={'ends_at': auction['ends_at']})
        return store._settle_isolated(db, auction_id)


def cancel_auction(auction_id, actor_id, reason):
    import database as store
    reason = store._reason(reason)
    with store.transaction() as db:
        store._admin_actor(db, actor_id)
        auction = db.execute('SELECT status FROM auctions WHERE id=?', (auction_id,)).fetchone()
        if not auction or auction['status'] not in ('open', 'failed'):
            raise ValueError('Only an open or failed auction can be cancelled.')
        db.execute("UPDATE auctions SET status='cancelled',closed_at=?,failure_reason=NULL WHERE id=?",
                   (store.iso(store.now_utc()), auction_id))
        store._audit(db, 'auction_cancelled', 'auction', auction_id, actor_id, reason,
               before={'status': auction['status']}, after={'status': 'cancelled'})


def retry_auction(auction_id, actor_id, reason):
    import database as store
    reason = store._reason(reason)
    with store.transaction() as db:
        store._admin_actor(db, actor_id)
        auction = db.execute('SELECT * FROM auctions WHERE id=?', (auction_id,)).fetchone()
        if not auction or auction['status'] != 'failed':
            raise ValueError('Only a failed auction can be retried.')
        if db.execute("SELECT 1 FROM auctions WHERE player_id=? AND status='open'", (auction['player_id'],)).fetchone():
            raise ValueError('This player already has another open auction.')
        if auction['ends_at'] > store.iso(store.now_utc()):
            raise ValueError('Wait until this auction expires before retrying, or cancel it.')
        db.execute("UPDATE auctions SET status='open',failure_reason=NULL WHERE id=?", (auction_id,))
        store._audit(db, 'auction_retried', 'auction', auction_id, actor_id, reason)
        return store._settle_isolated(db, auction_id)


def place_bid(auction_id, team_id, amount, manager_id=None):
    import database as store
    if not isinstance(amount, int) or amount < 1:
        raise ValueError('Enter a valid positive bid.')
    with store.transaction() as db:
        store._settle_expired(db)
        auction = db.execute('SELECT * FROM auctions WHERE id=?', (auction_id,)).fetchone()
        team = db.execute('SELECT * FROM teams WHERE id=?', (team_id,)).fetchone()
        if not auction or auction['status'] != 'open' or auction['ends_at'] <= store.iso(store.now_utc()):
            raise ValueError('This auction is closed.')
        if not team or team['manager_id'] is None:
            raise ValueError('Only an assigned manager can bid for a team.')
        if manager_id is not None:
            manager = db.execute('SELECT manager_active,role FROM users WHERE id=?', (manager_id,)).fetchone()
            if (team['manager_id'] != manager_id or not manager or
                    not manager['manager_active'] or manager['role']=='admin'):
                raise ValueError('Your team assignment changed. Refresh the page before bidding.')
        if auction['seller_team_id'] == team_id:
            raise ValueError('You cannot bid on a player you already own.')
        top = store.highest_bid(db, auction_id)
        minimum = max(auction['starting_price'], top['amount'] + 1 if top else 0)
        if amount < minimum:
            raise ValueError(f'The minimum bid is {minimum} credits.')
        available = team['budget'] - store.reserved_credits(db, team_id, exclude_auction=auction_id)
        if amount > available:
            raise ValueError(f'You have {available} credits available for this auction (other leading bids reserve credits).')
        db.execute('INSERT INTO bids(auction_id,team_id,amount,placed_at) VALUES (?,?,?,?)',
                   (auction_id, team_id, amount, store.iso(store.now_utc())))
        return True


def create_auction(player_id, starting_price, duration_hours):
    import database as store
    if starting_price < 1 or starting_price > 1000000:
        raise ValueError('Starting price must be between 1 and 1,000,000 credits.')
    if not 1 <= duration_hours <= 720:
        raise ValueError('Duration must be between 1 and 720 hours.')
    with store.transaction() as db:
        player = db.execute('SELECT * FROM players WHERE id=?', (player_id,)).fetchone()
        if not player:
            raise ValueError('Player not found.')
        if player['is_manager_player']:
            raise ValueError('Managers who play for their own team cannot be listed for transfer.')
        if player['user_id'] is not None:
            user=db.execute('SELECT player_active FROM users WHERE id=?',(player['user_id'],)).fetchone()
            if user and not user['player_active']:
                raise ValueError('This account has no active player role.')
        if db.execute('SELECT id FROM auctions WHERE player_id=? AND status=\'open\'', (player_id,)).fetchone():
            raise ValueError('That player is already listed for transfer.')
        ends_at = store.iso(store.now_utc() + timedelta(hours=duration_hours))
        return db.execute('''INSERT INTO auctions(player_id,seller_team_id,starting_price,ends_at,created_at)
                            VALUES (?,?,?,?,?)''',
                          (player_id, player['owner_team_id'], starting_price, ends_at, store.iso(store.now_utc()))).lastrowid

