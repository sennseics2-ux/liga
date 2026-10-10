from collections import Counter
import sqlite3
import pytest
import database as store
from demo.generate_past_seasons import generate, REASON
from game_logic import parse_pgn
from test_league import client, seed_admin

PASSWORD='SyntheticFixture123!'


def seed_four_teams():
    seed_admin()
    for n in range(4):
        manager=store.create_account(f'manager{n}',PASSWORD,'manager',f'manager{n}@example.com')
        team=store.create_team(f'Current Team {n}')
        store.assign_manager(team,manager)
        for p in range(4):
            uid=store.create_account(f'player{n}_{p}',PASSWORD,'player',f'player{n}_{p}@example.com')
            pid=store.create_player(f'Current Player {n}-{p}',user_id=uid)
            with store.transaction() as db:
                db.execute('UPDATE players SET owner_team_id=? WHERE id=?',(team,pid))
                store._start_player_term(db,pid,team)
    with store.read_db() as db:
        pid=db.execute('SELECT id FROM players WHERE is_manager_player=0 LIMIT 1').fetchone()[0]
        admin=db.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
    store.adjust_player_points(pid,7,actor_id=admin,reason='Existing adjustment retained')


def snapshot(db):
    return {t:list(db.execute('SELECT * FROM '+t+' ORDER BY id')) for t in ('users','teams','auctions','bids')}


def test_generated_two_seasons_use_current_rosters_and_preserve_source(client,tmp_path):
    seed_four_teams()
    source=store.DB_PATH
    with sqlite3.connect(source) as db:
        before=snapshot(db)
        original_players=list(db.execute('SELECT id,name,user_id,owner_team_id,points FROM players ORDER BY id'))
    output=tmp_path/'prepared.sqlite3'
    report=generate(source,output)
    assert report['board_games']==96 and report['players']==20
    assert output.stat().st_mode & 0o777==0o600
    with sqlite3.connect(source) as db:
        assert snapshot(db)==before
        assert list(db.execute('SELECT id,name,user_id,owner_team_id,points FROM players ORDER BY id'))==original_players
    with sqlite3.connect(output) as db:
        assert snapshot(db)==before
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute("SELECT COUNT(*) FROM points_ledger WHERE source='manual_adjustment'").fetchone()[0]==1
        seasons=db.execute('SELECT id,name,round_count,status FROM seasons ORDER BY start_year').fetchall()
        assert [s[1] for s in seasons]==['2024-2025','2025-2026']
        for sid,name,count,status in seasons:
            assert count==6 and status=='published'
            matches=db.execute('''SELECT m.id,m.home_team_id,m.away_team_id,m.scheduled_at FROM team_matches m
                JOIN season_rounds r ON r.id=m.round_id WHERE r.season_id=?''',(sid,)).fetchall()
            assert len(matches)==12
            assert set(Counter(tuple(sorted((h,a))) for _,h,a,_ in matches).values())=={2}
            assert set(Counter((h,a) for _,h,a,_ in matches).values())=={1}
            for mid,h,a,when in matches:
                lineups=db.execute('SELECT team_id,submitted_at FROM match_lineups WHERE match_id=?',(mid,)).fetchall()
                assert {t for t,_ in lineups}=={h,a}
                assert all(submitted<when for _,submitted in lineups)
                assert db.execute('SELECT COUNT(*) FROM lineup_players WHERE match_id=?',(mid,)).fetchone()[0]==8
                assert db.execute('SELECT COUNT(*) FROM match_games WHERE match_id=?',(mid,)).fetchone()[0]==4
            played=set(row[0] for row in db.execute('''SELECT DISTINCT l.player_id FROM lineup_players l JOIN team_matches m ON m.id=l.match_id
                JOIN season_rounds r ON r.id=m.round_id WHERE r.season_id=?''',(sid,)))
            assert played=={p[0] for p in original_players}
        for white,black,when,pgn,wt,bt in db.execute('SELECT white_player_id,black_player_id,scheduled_at,pgn_text,white_team_id,black_team_id FROM games'):
            parsed=parse_pgn(pgn)
            assert parsed['result']!='*' and len(parsed['moves'])==8
            assert REASON in pgn
            for pid,team in ((white,wt),(black,bt)):
                assert db.execute('''SELECT 1 FROM player_team_terms WHERE player_id=? AND team_id=? AND started_at<=?
                    AND (ended_at IS NULL OR ended_at>?)''',(pid,team,when,when)).fetchone()
        assert db.execute('SELECT COUNT(*) FROM points_ledger WHERE source="game_award"').fetchone()[0]==192
        for pid,points in db.execute('SELECT id,points FROM players'):
            assert points==db.execute('SELECT SUM(amount) FROM points_ledger WHERE player_id=?',(pid,)).fetchone()[0]
    with pytest.raises(FileExistsError):generate(source,output)
    with pytest.raises(ValueError,match='already exists'):generate(output,tmp_path/'duplicate.sqlite3')
    assert not (tmp_path/'duplicate.sqlite3').exists()


def test_existing_conflicting_history_fails_without_touching_source(client,tmp_path):
    seed_four_teams()
    with store.transaction() as db:
        player=db.execute('SELECT id,owner_team_id FROM players WHERE is_manager_player=0 LIMIT 1').fetchone()
        other=db.execute('SELECT id FROM teams WHERE id!=? LIMIT 1',(player['owner_team_id'],)).fetchone()[0]
        db.execute('''INSERT INTO player_team_terms(player_id,team_id,started_at,ended_at,source)
            VALUES(?,?,'2024-09-01T00:00:00+00:00','2025-07-01T00:00:00+00:00','Actual prior membership')''',(player['id'],other))
    output=tmp_path/'conflict.sqlite3'
    with pytest.raises(ValueError,match='conflicts'):generate(store.DB_PATH,output)
    assert not output.exists()
    with store.read_db() as db:assert db.execute('SELECT COUNT(*) FROM seasons').fetchone()[0]==0
