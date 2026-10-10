"""Historical game records and reversible scoring with independent adjustments.

Persistence imports are local to keep the database.py facade configurable.
"""


def create_game(white_player_id, black_player_id, scheduled_at, event_name='', round_label=''):
    import database as store
    from game_logic import parse_timestamp
    when = parse_timestamp(scheduled_at)
    try:
        white, black = int(white_player_id), int(black_player_id)
    except (TypeError, ValueError):
        raise ValueError('Choose two registered chess players.') from None
    if white == black:
        raise ValueError('A player cannot play themselves.')
    event_name, round_label = str(event_name).strip(), str(round_label).strip()
    if len(event_name) > 100 or len(round_label) > 35:
        raise ValueError('Event or round label is too long.')
    with store.transaction() as db:
        rows = db.execute('SELECT id FROM players WHERE id IN (?,?)', (white, black)).fetchall()
        if len(rows) != 2:
            raise ValueError('Both players must already exist in the league.')
        cursor = db.execute('''INSERT INTO games(white_player_id,black_player_id,scheduled_at,
                          event_name,round_label,white_team_id,black_team_id,created_at)
                          VALUES(?,?,?,?,?,?,?,?)''',
                          (white, black, when, event_name, round_label,
                           store._team_at(db,white,when), store._team_at(db,black,when),store.iso(store.now_utc())))
        return cursor.lastrowid


def _team_at(db, player_id, when):
    term = db.execute('''SELECT team_id FROM player_team_terms
        WHERE player_id=? AND started_at<=? AND (ended_at IS NULL OR ended_at>?)
        ORDER BY started_at DESC,id DESC LIMIT 1''', (player_id, when, when)).fetchone()
    if term:
        return term['team_id']
    # No dated membership is either a known free-agent period or an unknown
    # legacy period. Neither permits assigning a historical game to today's
    # owner. Imported approximate memberships have explicit sources/dates.
    return None


def _ensure_points_baseline(db, player_id):
    import database as store
    if not db.execute("SELECT 1 FROM points_ledger WHERE player_id=? AND source='legacy_adjustment'", (player_id,)).fetchone():
        player = db.execute('SELECT points FROM players WHERE id=?', (player_id,)).fetchone()
        if not player:
            raise ValueError('Player not found.')
        existing = db.execute('SELECT COALESCE(SUM(amount),0) FROM points_ledger WHERE player_id=?', (player_id,)).fetchone()[0]
        db.execute('''INSERT INTO points_ledger(player_id,source,amount,reason,created_at)
            VALUES(?,'legacy_adjustment',?,'Initial independent points balance',?)''',
            (player_id, player['points'] - existing, store.iso(store.now_utc())))


def _refresh_points(db, player_id):
    db.execute('''UPDATE players SET points=(SELECT COALESCE(SUM(amount),0)
        FROM points_ledger WHERE player_id=?) WHERE id=?''', (player_id, player_id))


def adjust_player_points(player_id, delta, actor_id, reason):
    """Apply a signed, audited adjustment independently of reversible game awards."""
    import database as store
    if isinstance(delta, bool) or not isinstance(delta, int) or delta == 0 or abs(delta) > 1_000_000:
        raise ValueError('Enter a nonzero adjustment between −1,000,000 and 1,000,000 points.')
    reason = store._reason(reason)
    with store.transaction() as db:
        store._admin_actor(db, actor_id)
        store._ensure_points_baseline(db, player_id)
        before = db.execute('SELECT points FROM players WHERE id=?', (player_id,)).fetchone()[0]
        db.execute('''INSERT INTO points_ledger(player_id,source,amount,actor_id,reason,created_at)
            VALUES(?,'manual_adjustment',?,?,?,?)''', (player_id, delta, actor_id, reason, store.iso(store.now_utc())))
        store._refresh_points(db, player_id)
        after = db.execute('SELECT points FROM players WHERE id=?', (player_id,)).fetchone()[0]
        store._audit(db, 'points_adjusted', 'player', player_id, actor_id, reason,
               before={'points': before}, after={'delta': delta, 'points': after})
        return after


def update_game_result(game_id, result, pgn_text=None, actor_id=None, reason='Game result recorded or corrected'):
    """Atomic, reversible scoring (win=3, draw=1, loss=0).

    Game entries are updated in a ledger alongside independent manual adjustments.
    The player's cached total is derived from that ledger in the same transaction.
    Trusted offline tools can omit the actor; web routes pass the authenticated admin.
    """
    import database as store
    from game_logic import RESULTS, parse_pgn, awards
    if result not in RESULTS and not (result is None and pgn_text is not None):
        raise ValueError('Choose a valid chess result.')
    reason = store._reason(reason)
    parsed = parse_pgn(pgn_text) if pgn_text is not None else None
    with store.transaction() as db:
        if actor_id is not None:
            store._admin_actor(db, actor_id)
        game = db.execute('SELECT * FROM games WHERE id=?', (game_id,)).fetchone()
        if game is None:
            raise ValueError('Game not found.')
        pgn = pgn_text if pgn_text is not None else game['pgn_text']
        pgn_result = parsed['result'] if parsed is not None else None
        if pgn and pgn_result is None:
            pgn_result = parse_pgn(pgn)['result']
        if result is None:
            # An ongoing uploaded PGN preserves the latest saved result while
            # holding the writer lock, rather than an earlier read's snapshot.
            result = pgn_result if pgn_result and pgn_result != '*' else game['result']
        if pgn_result and pgn_result != '*' and result != pgn_result:
            raise ValueError(f'The attached PGN declares {pgn_result}; choose that result or replace the PGN.')
        wa, ba = awards(result)
        for player_id, amount in ((game['white_player_id'], wa), (game['black_player_id'], ba)):
            store._ensure_points_baseline(db, player_id)
            entry = db.execute("SELECT id FROM points_ledger WHERE game_id=? AND player_id=? AND source='game_award'", (game_id, player_id)).fetchone()
            if entry:
                db.execute('UPDATE points_ledger SET amount=?,actor_id=?,reason=?,created_at=? WHERE id=?',
                           (amount, actor_id, reason, store.iso(store.now_utc()), entry['id']))
            else:
                db.execute('''INSERT INTO points_ledger(player_id,game_id,source,amount,actor_id,reason,created_at)
                    VALUES(?,?,'game_award',?,?,?,?)''', (player_id, game_id, amount, actor_id, reason, store.iso(store.now_utc())))
            store._refresh_points(db, player_id)
        # Team IDs at scheduling time are provisional: a transfer may happen
        # before the match. Confirm dated membership on the first final result,
        # then preserve it through corrections, including clearing/re-recording.
        confirmed = game['attribution_confirmed']
        wt, bt = game['white_team_id'], game['black_team_id']
        if not confirmed and result != '*':
            wt = store._team_at(db, game['white_player_id'], game['scheduled_at'])
            bt = store._team_at(db, game['black_player_id'], game['scheduled_at'])
            confirmed = 1
        db.execute('''UPDATE games SET result=?,pgn_text=?,recorded_at=?,
                     white_award=?,black_award=?,white_team_id=?,black_team_id=?,attribution_confirmed=? WHERE id=?''',
                   (result,pgn,store.iso(store.now_utc()) if result != '*' else None,wa,ba,wt,bt,confirmed,game_id))
        store._audit(db, 'game_result_updated', 'game', game_id, actor_id, reason,
               before={'result': game['result'], 'white_award': game['white_award'], 'black_award': game['black_award'], 'has_pgn': bool(game['pgn_text']), 'white_team_id': game['white_team_id'], 'black_team_id': game['black_team_id']},
               after={'result': result, 'white_award': wa, 'black_award': ba, 'has_pgn': bool(pgn), 'white_team_id': wt, 'black_team_id': bt})


def attach_pgn(game_id, text, actor_id=None, reason='PGN attached and result recorded'):
    """Attach one legal PGN and, when it declares a result, finalize that result."""
    import database as store
    store.update_game_result(game_id, None, text, actor_id=actor_id, reason=reason)


def remove_game_pgn(game_id, actor_id=None, reason='PGN removed'):
    import database as store
    with store.transaction() as db:
        if actor_id is not None:
            store._admin_actor(db, actor_id)
        if db.execute('UPDATE games SET pgn_text=NULL WHERE id=?', (game_id,)).rowcount != 1:
            raise ValueError('Game not found.')
        store._audit(db, 'game_pgn_removed', 'game', game_id, actor_id, reason)

