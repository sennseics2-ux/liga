"""Copy an existing league and add two explicitly generated historical seasons.

Never changes the source or overwrites an output. Results and memberships are
synthetic, not evidence of real matches. Current credentials and rosters remain.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import random
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import database as store
from game_logic import awards

YEARS = (2024, 2025)
REASON = 'Generated demonstration history with past-only assignments; not an actual match record'
PAIRINGS = (((0, 3), (1, 2)), ((0, 2), (3, 1)), ((0, 1), (2, 3)))


def stamp(value):
    return store.iso(datetime.fromisoformat(value).replace(tzinfo=timezone.utc))


def _fill_history(db, table, identity, entity_id, team_id, start, end, manager_player=False):
    # Fill only uncovered intervals; never rewrite an existing appointment/term.
    rows = db.execute(f'''SELECT * FROM {table} WHERE {identity}=? AND started_at<?
        AND (ended_at IS NULL OR ended_at>?) ORDER BY started_at,id''',
        (entity_id, end, start)).fetchall()
    if table == 'manager_terms':
        team_rows = db.execute('''SELECT * FROM manager_terms WHERE team_id=? AND started_at<?
            AND (ended_at IS NULL OR ended_at>?)''', (team_id, end, start)).fetchall()
        if any(r['manager_id'] != entity_id for r in team_rows):
            raise ValueError('Existing manager history conflicts with a generated season; source is unchanged.')
    cursor = start
    gaps = []
    for row in rows:
        if row['team_id'] != team_id:
            raise ValueError('Existing roster history conflicts with a generated season; source is unchanged.')
        if row['started_at'] > cursor:
            gaps.append((cursor, min(end, row['started_at'])))
        cursor = max(cursor, min(end, row['ended_at'] or end))
    if cursor < end:
        gaps.append((cursor, end))
    for first, last in gaps:
        if table == 'player_team_terms':
            db.execute('''INSERT INTO player_team_terms(player_id,team_id,started_at,ended_at,
                source,end_reason,manager_player) VALUES(?,?,?,?,?,?,?)''',
                (entity_id, team_id, first, last, REASON, 'Generated season concluded', int(manager_player)))
        else:
            db.execute('''INSERT INTO manager_terms(manager_id,team_id,started_at,ended_at,end_reason)
                VALUES(?,?,?,?,?)''', (entity_id, team_id, first, last, REASON))


def _pgn(white, black, when, result, season, round_number, board, location):
    import chess.pgn
    game = chess.pgn.Game()
    game.headers.update(Event=f'Generated demonstration {season}', Site=location,
                        Date=when[:10].replace('-', '.'), Round=f'{round_number}.{board}',
                        White=white['name'], Black=black['name'], Result=result,
                        Annotator='Generated demonstration; not actual match moves')
    game.comment = REASON
    position = game.board()
    node = game
    for san in ('e4', 'e5', 'Nf3', 'Nc6', 'Bb5', 'a6', 'Ba4', 'Nf6'):
        move = position.parse_san(san)
        position.push(move)
        node = node.add_variation(move)
    return game.accept(chess.pgn.StringExporter(headers=True, variations=False, comments=True)) + '\n'


def _historical_rosters(db, teams, allow_historical_guests=False):
    """Plan past memberships without requiring or changing current ownership."""
    candidates=[dict(u) for u in db.execute('''SELECT u.* FROM users u WHERE u.role!='admin' AND
        (u.role='manager' OR u.manager_active=1 OR EXISTS
            (SELECT 1 FROM players p WHERE p.user_id=u.id AND p.is_manager_player=1) OR EXISTS
            (SELECT 1 FROM manager_terms t WHERE t.manager_id=u.id)) ORDER BY u.id''')]
    if len(candidates)<4:
        raise ValueError('Four existing manager accounts are needed for the historical seasons. No current team assignment or invitation is required.')
    # Only mutate these local team dictionaries. Never UPDATE teams.manager_id,
    # activation flags, availability, invitations or current appointments.
    for team,manager in zip(teams,candidates[:4]):
        team['manager_id']=manager['id']
        if not db.execute('SELECT 1 FROM players WHERE user_id=?',(manager['id'],)).fetchone():
            db.execute('''INSERT INTO players(name,user_id,is_manager_player,created_at)
                VALUES(?,?,1,?)''',(manager['name'] or manager['username'],manager['id'],stamp('2024-09-01')))
    managers={team['manager_id'] for team in teams}
    profiles=[dict(p) for p in db.execute('''SELECT p.* FROM players p LEFT JOIN users u ON u.id=p.user_id
        WHERE u.id IS NULL OR u.role!='admin' ORDER BY p.id''')]
    rosters={}
    for team in teams:
        profile=next((p for p in profiles if p['user_id']==team['manager_id']),None)
        rosters[team['id']]=[profile]
    pool=[]
    for player in profiles:
        if player['user_id'] in managers:
            continue
        preferred=rosters.get(player['owner_team_id'])
        if preferred is not None and len(preferred)<24:
            preferred.append(player)
        else:
            pool.append(player)
    for player in pool:
        target=min(rosters.values(),key=len)
        if len(target)>=24:
            raise ValueError('More than 96 players cannot all play in six four-board rounds.')
        target.append(player)
    guest_count=0
    while allow_historical_guests and sum(map(len,rosters.values()))<16:
        team_id=min(rosters,key=lambda key:len(rosters[key]))
        guest_count+=1
        pid=db.execute('''INSERT INTO players(name,created_at) VALUES(?,?)''',
            (f'Historical guest — Team {team_id} — {guest_count}',stamp('2024-09-01'))).lastrowid
        rosters[team_id].append(dict(db.execute('SELECT * FROM players WHERE id=?',(pid,)).fetchone()))
    if sum(map(len,rosters.values()))<16:
        raise ValueError('Past seasons need at least 16 existing chess profiles including the four managers; current team assignments are not required.')
    while min(map(len,rosters.values()))<4:
        smallest=min(rosters.values(),key=len)
        largest=max(rosters.values(),key=len)
        smallest.append(largest.pop())
    return rosters,guest_count


def _assert_no_current_records(db):
    # The requested archive ends June 30, 2026. Never remove current data to
    # satisfy this constraint: stop and leave the source unchanged instead.
    if db.execute('SELECT 1 FROM games WHERE scheduled_at>=? LIMIT 1',(stamp('2026-07-01'),)).fetchone():
        raise ValueError('Current/future games already exist. Nothing was removed; only empty current-season data is supported.')
    if db.execute('''SELECT 1 FROM team_matches m JOIN season_rounds r ON r.id=m.round_id
        JOIN seasons s ON s.id=r.season_id WHERE s.start_year>=2026 OR m.scheduled_at>=? LIMIT 1''',
        (stamp('2026-07-01'),)).fetchone():
        raise ValueError('Current/future team matches already exist. Nothing was removed; only empty current-season data is supported.')


def _populate(seed,allow_historical_guests=False):
    rng = random.Random(seed)
    created = store.iso(store.now_utc())
    with store.transaction() as db:
        teams = [dict(t) for t in db.execute('SELECT * FROM teams ORDER BY id')]
        if len(teams) != 4:
            raise ValueError('Exactly four current teams are required.')
        admin = db.execute("SELECT id FROM users WHERE role='admin' AND account_active=1 ORDER BY id LIMIT 1").fetchone()
        if admin is None:
            raise ValueError('An active administrator account is required.')
        actor = admin['id']
        _assert_no_current_records(db)
        rosters,guest_count = _historical_rosters(db,teams,allow_historical_guests)
        for year in YEARS:
            name = f'{year}-{year+1}'
            start, end = stamp(f'{year}-09-01'), stamp(f'{year+1}-07-01')
            if db.execute('SELECT 1 FROM seasons WHERE start_year=? OR name=?', (year, name)).fetchone():
                raise ValueError(f'{name} already exists; refusing to duplicate or overwrite it.')
            if db.execute('SELECT 1 FROM games WHERE scheduled_at>=? AND scheduled_at<?', (start, end)).fetchone():
                raise ValueError(f'{name} already contains games; review existing history before generating results.')
            season = db.execute('''INSERT INTO seasons(name,start_year,start_date,end_date,round_count,status,created_at)
                VALUES(?,?,?,?,6,'published',?)''', (name, year, f'{year}-09-01', f'{year+1}-06-30', created)).lastrowid
            for team in teams:
                _fill_history(db, 'manager_terms', 'manager_id', team['manager_id'], team['id'], start, end)
                for player in rosters[team['id']]:
                    _fill_history(db, 'player_team_terms', 'player_id', player['id'], team['id'], start, end,
                                  player['user_id'] == team['manager_id'])
            dates = (f'{year}-10-05', f'{year}-11-02', f'{year}-12-07',
                     f'{year+1}-01-11', f'{year+1}-02-08', f'{year+1}-03-08')
            for number, day in enumerate(dates, 1):
                when = stamp(day + 'T14:00:00')
                submitted = store.iso(datetime.fromisoformat(when) - timedelta(days=1))
                recorded = store.iso(datetime.fromisoformat(when) + timedelta(hours=3))
                round_id = db.execute('INSERT INTO season_rounds(season_id,number) VALUES(?,?)', (season, number)).lastrowid
                for left, right in PAIRINGS[(number-1) % 3]:
                    if number > 3:
                        left, right = right, left
                    home, away = teams[left], teams[right]
                    location = 'Generated club fixture — ' + home['name']
                    match = db.execute('''INSERT INTO team_matches(round_id,home_team_id,away_team_id,scheduled_at,location,created_at)
                        VALUES(?,?,?,?,?,?)''', (round_id, home['id'], away['id'], when, location, created)).lastrowid
                    selected = {}
                    for team in (home, away):
                        roster = rosters[team['id']]
                        selected[team['id']] = [roster[((number-1)*4+b) % len(roster)] for b in range(4)]
                        db.execute('INSERT INTO match_lineups(match_id,team_id,manager_id,submitted_at) VALUES(?,?,?,?)',
                                   (match, team['id'], team['manager_id'], submitted))
                        for board, player in enumerate(selected[team['id']], 1):
                            db.execute('INSERT INTO lineup_players(match_id,team_id,board,player_id) VALUES(?,?,?,?)',
                                       (match, team['id'], board, player['id']))
                    for board in range(1, 5):
                        wt, bt = (home, away) if board % 2 else (away, home)
                        white, black = selected[wt['id']][board-1], selected[bt['id']][board-1]
                        result = rng.choice(('1-0', '0-1', '1/2-1/2'))
                        wa, ba = awards(result)
                        game = db.execute('''INSERT INTO games(white_player_id,black_player_id,scheduled_at,event_name,
                            round_label,result,pgn_text,recorded_at,white_award,black_award,white_team_id,black_team_id,
                            attribution_confirmed,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?)''',
                            (white['id'], black['id'], when, f'Generated demonstration {name}', f'Round {number} · Board {board}',
                             result, _pgn(white,black,when,result,name,number,board,location), recorded, wa, ba,
                             wt['id'], bt['id'], created)).lastrowid
                        db.execute('INSERT INTO match_games(match_id,board,game_id) VALUES(?,?,?)', (match, board, game))
                        for player, amount in ((white, wa), (black, ba)):
                            store._ensure_points_baseline(db, player['id'])
                            db.execute('''INSERT INTO points_ledger(player_id,game_id,source,amount,actor_id,reason,created_at)
                                VALUES(?,?,'game_award',?,?,?,?)''', (player['id'], game, amount, actor, REASON, recorded))
                            store._refresh_points(db, player['id'])
                        store._audit(db,'generated_historical_game','game',game,actor,REASON,after={'result':result,'season':name})
            for team in teams:
                db.execute('''UPDATE manager_terms SET final_fantasy_points=(
                    SELECT COALESCE(SUM(
                        CASE WHEN white_team_id=manager_terms.team_id THEN white_award ELSE 0 END +
                        CASE WHEN black_team_id=manager_terms.team_id THEN black_award ELSE 0 END),0)
                    FROM games WHERE scheduled_at>=manager_terms.started_at AND scheduled_at<manager_terms.ended_at)
                    WHERE manager_id=? AND team_id=? AND started_at>=? AND ended_at<=? AND end_reason=?''',
                    (team['manager_id'],team['id'],start,end,REASON))
            store._audit(db,'generated_historical_season','season',season,actor,REASON,after={'rounds':6,'teams':4,'games':48})
    return {'seasons': ['2024-2025', '2025-2026'], 'rounds': 12, 'team_matches': 24,
            'board_games': 96, 'players': sum(map(len, rosters.values())),
            'historical_guests_created':guest_count,'current_season_games':0,'current_season_matches':0,
            'results': 'Generated demonstration; not real match records', 'seed': seed}


def generate(source: Path, output: Path, seed=20261010, *, allow_historical_guests=False):
    source, output = source.resolve(), output.resolve()
    if not source.is_file():
        raise FileNotFoundError('Source database does not exist.')
    if source == output:
        raise ValueError('Source and output must be different files.')
    output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    original = store.DB_PATH
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)) as src, closing(sqlite3.connect(output)) as dst:
            src.backup(dst)
        store.DB_PATH = output
        store.init_db()  # Migration affects only this new private copy.
        report = _populate(seed,allow_historical_guests)
        with store.read_db() as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Generated database integrity check failed.')
        with closing(sqlite3.connect(output)) as db:
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            db.execute('PRAGMA journal_mode=DELETE')
        output.chmod(0o600)
        return report
    except Exception:
        # Only remove files belonging to this invocation, never the source.
        for suffix in ('', '-wal', '-shm', '.pre-v2.bak', '.pre-v3.bak', '.pre-v4.bak', '.pre-v9.bak', '.pre-v25.bak'):
            path = Path(str(output)+suffix)
            if path.exists():
                path.unlink()
        raise
    finally:
        store.DB_PATH = original


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=20261010)
    parser.add_argument('--allow-historical-guests',action='store_true',
                        help='Fill missing past-season lineup slots with named guests without login accounts or current teams')
    args = parser.parse_args()
    try:
        report = generate(args.source, args.output, args.seed,allow_historical_guests=args.allow_historical_guests)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        parser.exit(1, f'Not generated: {exc}\n')
    print(json.dumps(report, indent=2))
    print('Created a PRIVATE database copy containing account credentials:', args.output)
    print('Keep it on the VM; never publish or share it. Review before replacing live data.')
