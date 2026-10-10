"""Generate a standalone fictional ClubDraft database with audited 2024–26 histories.

Usage: python demo/generate_three_seasons.py --output /path/to/league.sqlite3
Will not overwrite an existing file. Does not read or modify your current league.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import database as store

SEED = 20261008
PASSWORD = 'ChessDemo2026!'
TEAMS = ['Coimbra Knights', 'Porto Rooks', 'Lisbon Bishops', 'Braga Queens',
         'Aveiro Gambits', 'Faro Castles', 'Leiria Pawns', 'Viseu Checkmates']
CLUBS = ['Clube de Xadrez de Coimbra', 'Academia de Xadrez do Porto',
         'Clube de Xadrez de Lisboa', 'Clube de Xadrez de Braga',
         'Xadrez Aveiro', 'Clube de Xadrez de Faro']
FIRST = ['Ana','Miguel','Beatriz','Tiago','Inês','João','Carolina','Rafael','Sofia','André',
         'Mariana','Pedro','Catarina','Diogo','Leonor','Francisco','Marta','Gonçalo',
         'Isabel','Henrique','Rita','Tomás','Diana','Daniel']
LAST = ['Silva','Costa','Santos','Oliveira','Pereira','Rodrigues','Ferreira',
        'Gomes','Martins','Almeida','Ribeiro','Carvalho','Lopes','Sousa']


def ts(date: str) -> str:
    return date + 'T12:00:00+00:00'


def add_days(datetime_str: str, days: int) -> str:
    return (datetime.fromisoformat(datetime_str) + timedelta(days=days)).isoformat(timespec='seconds')


def generate(path: Path) -> dict:
    path = path.resolve()
    if path.exists():
        raise FileExistsError(f'Refusing to overwrite {path}; choose a different --output file')
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    original_path = store.DB_PATH
    store.DB_PATH = path
    try:
        store.init_db()
        hash_value = store.hash_password(PASSWORD)
        teams = []
        manager_accounts = []
        manager_profiles = {}
        players = []
        free_players = []
        budgets = [1000] * len(TEAMS)
        owner = {}
        now_month = '2026-10-08'
        with store.transaction() as db:
            def user(username: str, role: str, player_active=1, manager_active=0):
                return db.execute('''INSERT INTO users(username,password_hash,role,created_at,manager_active,
                    player_active,manager_available) VALUES(?,?,?,?,?,?,?)''',
                    (username,hash_value,role,ts('2023-12-05'),manager_active,player_active,
                     int(bool(manager_active)))).lastrowid

            admin_id = user('demo_admin','admin',0,0)
            for name in TEAMS:
                teams.append(db.execute('INSERT INTO teams(name,budget,created_at) VALUES(?,?,?)',
                                        (name,1000,ts('2023-12-01'))).lastrowid)
            # Eleven managers have accounts; eight serve at a time, three retire mid-history.
            for i in range(11):
                uid = user(f'captain{i+1:02d}', 'manager',1,1)
                manager_accounts.append(uid)
                pid = db.execute('''INSERT INTO players(name,club,rating,points,owner_team_id,user_id,
                    is_manager_player,created_at) VALUES(?,?,?,?,NULL,?,1,?)''',
                    (f'Captain {i+1:02d}',CLUBS[i%len(CLUBS)],1650+i*37,18+i*3,uid,ts('2023-12-05'))).lastrowid
                manager_profiles[uid] = pid
                owner[pid] = None
            for i in range(57):
                uid = user(f'player{i+1:02d}', 'player')
                name = f'{FIRST[i%len(FIRST)]} {LAST[(i*5+i//len(FIRST))%len(LAST)]}'
                rating = 1260 + (i*47)%1050
                score = 20 + (i*17)%94
                pid = db.execute('''INSERT INTO players(name,club,rating,points,owner_team_id,user_id,
                    is_manager_player,created_at) VALUES(?,?,?,?,NULL,?,0,?)''',
                    (name,CLUBS[i%len(CLUBS)],rating,score,uid,ts('2023-12-05'))).lastrowid
                players.append(pid)
                owner[pid] = None

            def beginning(player_id: int, team_id: int, date: str, source='season opening', mp=False):
                assert owner[player_id] is None, (player_id,team_id)
                db.execute('UPDATE players SET owner_team_id=? WHERE id=?',(team_id,player_id))
                db.execute('''INSERT INTO player_team_terms(player_id,team_id,started_at,source,manager_player)
                    VALUES(?,?,?,?,?)''',(player_id,team_id,date,source,int(mp)))
                owner[player_id] = team_id

            def leave(player_id: int, date: str, reason: str):
                assert owner[player_id] is not None
                updated = db.execute('''UPDATE player_team_terms SET ended_at=?,end_reason=?
                    WHERE player_id=? AND team_id=? AND ended_at IS NULL''',
                    (date,reason,player_id,owner[player_id]))
                assert updated.rowcount == 1
                db.execute('UPDATE players SET owner_team_id=NULL WHERE id=?',(player_id,))
                owner[player_id] = None

            current_manager = {}
            def appoint(idx: int, uid: int, date: str):
                team_id = teams[idx]
                assert db.execute('SELECT manager_id FROM teams WHERE id=?',(team_id,)).fetchone()[0] is None
                db.execute('UPDATE teams SET manager_id=? WHERE id=?',(uid,team_id))
                db.execute('INSERT INTO manager_terms(manager_id,team_id,started_at) VALUES(?,?,?)',
                           (uid,team_id,date))
                db.execute('UPDATE users SET manager_available=0 WHERE id=?',(uid,))
                beginning(manager_profiles[uid],team_id,date,'manager appointment',True)
                current_manager[idx] = uid

            def manager_switch(idx: int, successor: int, date: str):
                team_id = teams[idx]
                uid = current_manager[idx]
                leave(manager_profiles[uid],date,'resigned')
                db.execute('''UPDATE manager_terms SET ended_at=?,end_reason='resigned',
                    final_fantasy_points=?,final_budget=? WHERE manager_id=? AND team_id=? AND ended_at IS NULL''',
                    (date,db.execute('SELECT SUM(points) FROM players WHERE owner_team_id=?',(team_id,)).fetchone()[0],
                     budgets[idx],uid,team_id))
                db.execute('UPDATE teams SET manager_id=NULL WHERE id=?',(team_id,))
                db.execute('UPDATE users SET manager_available=1 WHERE id=?',(uid,))
                appoint(idx,manager_accounts[successor],date)

            for i in range(8):
                appoint(i,manager_accounts[i],ts('2024-01-01'))
            # All eight teams start 2024 with exactly six ordinary players + their manager-player.
            for idx,pid in enumerate(players[:48]):
                beginning(pid,teams[idx//6],ts('2024-01-01'))
            free_players = list(players[48:])
            transfer_log = []

            def auction(player_id: int, dst_idx: int, date: str, amount: int):
                team_id = teams[dst_idx]
                seller_id = owner[player_id]
                assert seller_id != team_id
                assert budgets[dst_idx] >= amount
                selling_idx = teams.index(seller_id) if seller_id else None
                created = add_days(date,-2)
                id_ = db.execute('''INSERT INTO auctions(player_id,seller_team_id,starting_price,ends_at,status,
                    winner_team_id,final_price,created_at,closed_at)
                    VALUES(?,?,?,?,'closed',?,?,?,?)''',
                    (player_id,seller_id,max(1,amount-30),date,team_id,amount,created,date)).lastrowid
                # Ascending bids, with the winning team's final bid matching the recorded price.
                others=[k for k in range(8) if k!=dst_idx and k!=selling_idx]
                losing_team = teams[rng.choice(others)]
                for team,price,timing in [
                    (losing_team,max(1,amount-24),add_days(date,-1)),
                    (team_id,amount,date)]:
                    db.execute('INSERT INTO bids(auction_id,team_id,amount,placed_at) VALUES(?,?,?,?)',
                               (id_,team,price,timing))
                if seller_id:
                    leave(player_id,date,'transferred')
                    budgets[selling_idx]+=amount
                beginning(player_id,team_id,date,'auction win')
                budgets[dst_idx]-=amount
                db.execute('UPDATE teams SET budget=? WHERE id=?',(budgets[dst_idx],team_id))
                if seller_id:
                    db.execute('UPDATE teams SET budget=? WHERE id=?',(budgets[selling_idx],seller_id))
                transfer_log.append((id_,player_id,seller_id,team_id,amount,date))

            def run_events(year:int, months:list[int], count:int, free_count:int):
                dates=sorted(ts(f'{year}-{months[k%len(months)]:02d}-{min(27,3+(k//len(months))*6+(k%3)*2):02d}') for k in range(count))
                for k,date in enumerate(dates):
                    # Some new players join via recorded free-agent auctions.
                    if k < free_count:
                        pid=free_players.pop(0)
                    else:
                        eligible=[pid for pid in players[:48]+players[48:] if owner[pid] is not None
                                  and sum(1 for x in players if owner[x]==owner[pid])>=4]
                        pid=rng.choice(eligible)
                    source=owner[pid]
                    targets=[idx for idx,t in enumerate(teams) if t!=source and budgets[idx]>=115]
                    assert targets, 'Demo teams unexpectedly exhausted all transfer budget'
                    target=rng.choice(targets)
                    amount=38+rng.randrange(0,74)
                    auction(pid,target,date,amount)

            run_events(2024,[3,4,6,7,8,9,10,11],12,2)
            # The 2025 campaign changes two managers with dated handovers.
            manager_switch(1,8,ts('2025-01-10'))
            run_events(2025,[2,3,4,5,6,7,8,9,10,11],16,2)
            manager_switch(4,9,ts('2025-12-05'))
            # The third handover occurred in 2026.
            manager_switch(6,10,ts('2026-01-12'))
            run_events(2026,[2,3,4,5,6,7,8,9],12,2)
            assert len(free_players)==3
            # 3 currently-open auctions for available free agents; none has closed or moved.
            for k,pid in enumerate(free_players):
                date=ts(f'2026-10-{16+k:02d}')
                aid=db.execute('''INSERT INTO auctions(player_id,seller_team_id,starting_price,ends_at,status,created_at)
                    VALUES(?,NULL,?,?,'open',?)''',
                    (pid,40+k*10,date,ts('2026-10-07'))).lastrowid
                db.execute('INSERT INTO bids(auction_id,team_id,amount,placed_at) VALUES(?,?,?,?)',
                           (aid,teams[(k+2)%8],45+k*10,ts('2026-10-08')))
            # Future deployments should not treat this historical dataset as match results:
            # points in `players` are fictional *current* totals, not per-season scores.
        store.init_db()  # repeatable migration must preserve exact seeded records
        report=validate(path,transfer_log)
        assert report['transfer_count']==40
        return report
    finally:
        store.DB_PATH = original_path


def validate(path:Path,transfers:list|None=None) -> dict:
    import sqlite3
    db=sqlite3.connect(path)
    db.row_factory=sqlite3.Row
    try:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        row_counts={t:db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in
                    ('users','teams','players','auctions','bids','manager_terms','player_team_terms')}
        assert row_counts['teams']==8
        history=db.execute('SELECT * FROM player_team_terms ORDER BY player_id,started_at,id').fetchall()
        previous={}
        for term in history:
            pid=term['player_id']
            if pid in previous:
                assert previous[pid]['ended_at'] is not None, (pid,'overlap')
                assert previous[pid]['ended_at'] <= term['started_at'],(pid,'overlap dates')
            if term['ended_at']:
                assert term['ended_at']>=term['started_at']
            previous[pid]=term
        owners=db.execute('SELECT id,owner_team_id FROM players').fetchall()
        for p in owners:
            active=db.execute('SELECT team_id FROM player_team_terms WHERE player_id=? AND ended_at IS NULL',(p['id'],)).fetchall()
            assert len(active)==int(p['owner_team_id'] is not None),(p['id'],active)
            if active:
                assert active[0]['team_id']==p['owner_team_id']
        sales=db.execute("SELECT * FROM auctions WHERE status='closed' AND winner_team_id IS NOT NULL ORDER BY closed_at").fetchall()
        assert len(sales)==40
        for a in sales:
            bid=db.execute('SELECT team_id,amount FROM bids WHERE auction_id=? ORDER BY amount DESC,id LIMIT 1',(a['id'],)).fetchone()
            assert bid['team_id']==a['winner_team_id'] and bid['amount']==a['final_price']
            assert a['winner_team_id']!=a['seller_team_id']
            started=db.execute('SELECT * FROM player_team_terms WHERE player_id=? AND team_id=? AND started_at=?',
                               (a['player_id'],a['winner_team_id'],a['closed_at'])).fetchone()
            assert started is not None,(a['id'],'missing winning team term')
            if a['seller_team_id']:
                ended=db.execute('SELECT * FROM player_team_terms WHERE player_id=? AND team_id=? AND ended_at=?',
                                 (a['player_id'],a['seller_team_id'],a['closed_at'])).fetchone()
                assert ended is not None,(a['id'],'missing seller departure term')
        for r in db.execute('SELECT * FROM manager_terms'):
            mp=db.execute('''SELECT 1 FROM player_team_terms r JOIN players p ON p.id=r.player_id
                WHERE p.user_id=? AND r.team_id=? AND r.manager_player=1 AND r.started_at=?
                AND r.ended_at IS ?''',(r['manager_id'],r['team_id'],r['started_at'],r['ended_at'])).fetchone()
            assert mp is not None,('manager-player history missing',r['id'])
        for team in db.execute('SELECT * FROM teams'):
            active=db.execute('SELECT * FROM manager_terms WHERE team_id=? AND ended_at IS NULL',(team['id'],)).fetchall()
            assert len(active)==1 and active[0]['manager_id']==team['manager_id']
            assert team['budget']>=0
            for season in (2024,2025,2026):
                start=f'{season}-01-01T00:00:00+00:00'; end=f'{season+1}-01-01T00:00:00+00:00'
                roster=db.execute('''SELECT DISTINCT player_id FROM player_team_terms
                    WHERE team_id=? AND started_at<? AND (ended_at IS NULL OR ended_at>?)''',
                    (team['id'],end,start)).fetchall()
                assert len(roster)>=5,(team['id'],season,'incomplete season roster')
        assert db.execute("SELECT COUNT(*) FROM player_team_terms WHERE source LIKE 'legacy%' OR source='imported current snapshot'").fetchone()[0]==0
        return {**row_counts,'transfer_count':len(sales),'open_auctions':db.execute("SELECT COUNT(*) FROM auctions WHERE status='open'").fetchone()[0],
                '2024_teams':8,'2025_teams':8,'2026_teams':8,
                'active_roster':db.execute('SELECT COUNT(*) FROM players WHERE owner_team_id IS NOT NULL').fetchone()[0]}
    finally:
        db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'demo'/'league-three-seasons.sqlite3')
    args=parser.parse_args()
    result=generate(args.output)
    print('Demo created:', args.output)
    for k,v in result.items():
        print(f'{k}: {v}')
    print('Local test-only logins: demo_admin / captain01 / player01')
    print('Demo password: ChessDemo2026!')
