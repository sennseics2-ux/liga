"""Synchronous account/auction operations called as whole thread-pool jobs."""
import database as store


def authenticate_account(username, password):
    with store.read_db() as db:
        user = db.execute('SELECT * FROM users WHERE username=? COLLATE NOCASE', (username,)).fetchone()
    if user is None or not user['account_active'] or not store.verify_password(password, user['password_hash']):
        return None
    return dict(user)


def team_for_member(user):
    with store.read_db() as db:
        row = db.execute('SELECT * FROM teams WHERE manager_id=?', (user['id'],)).fetchone()
    return dict(row) if row is not None else None


def close_auction_safely(auction_id, actor_id, reason):
    # The database service owns quarantine, audit, and settlement atomicity.
    return store.close_auction(auction_id, actor_id=actor_id, reason=reason)
