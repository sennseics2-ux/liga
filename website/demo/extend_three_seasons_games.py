"""Make a deterministic, self-contained V9 fixture/PGN demo from the V8 demo.

This script is for fictional examples only. Never run against a production DB.
Requires CHESS_DB_PATH or a direct path passed to generate().
"""
import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database as store

SAMPLE_LINES = {
    '1-0': '1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0',
    '0-1': '1. f3 e5 2. g4 Qh4# 0-1',
    '1/2-1/2': '1. Nf3 Nf6 2. Ng1 Ng8 3. Nf3 Nf6 4. Ng1 Ng8 1/2-1/2'
}

def generate(input_path: Path, output_path: Path):
    if output_path.exists():
        raise FileExistsError(f'Output already exists: {output_path}')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_path, output_path)
    store.DB_PATH = output_path
    store.init_db()
    total, examples = 0, 0
    for year, count in ((2024, 10), (2025, 12), (2026, 14)):
        for i in range(count):
            # Stay safely inside the existing demo's dated membership history.
            month, day = (5 + i % 3), (5 + (i * 2) % 19)
            when = f'{year}-{month:02}-{day:02}T17:00:00+00:00'
            with store.read_db() as db:
                active = db.execute('''SELECT DISTINCT p.id,p.name,r.team_id FROM players p
                     JOIN player_team_terms r ON r.player_id=p.id
                     WHERE r.started_at<=? AND (r.ended_at IS NULL OR r.ended_at>?)
                     ORDER BY p.id''', (when, when)).fetchall()
            # Avoid the same team when possible.
            first = active[(2*i) % len(active)]
            second = next((p for p in active if p['id']!=first['id'] and p['team_id']!=first['team_id']),None)
            if second is None:
                raise RuntimeError('No suitable pair in demo player history')
            result = ('1-0','0-1','1/2-1/2')[(i+year)%3]
            gid = store.create_game(first['id'], second['id'], when, f'Fictional Club League {year}', f'Round {i+1}')
            store.update_game_result(gid, result)
            # Attach a few known, legal standard PGN move sequences as examples.
            # PGN text is seeded directly because the generation environment may
            # lack python-chess. It will be validated when replayed by the app.
            if i < 3:
                date=f'{year}.{month:02}.{day:02}'
                headers = (f'[Event "Fictional Club League {year}"]\n[Site "Demo club"]\n'
                           f'[Date "{date}"]\n[Round "{i+1}"]\n[White "{first["name"]}"]\n'
                           f'[Black "{second["name"]}"]\n[Result "{result}"]\n\n')
                pgn = headers + SAMPLE_LINES[result] + '\n'
                with store.transaction() as db:
                    db.execute('UPDATE games SET pgn_text=? WHERE id=?',(pgn,gid))
                examples+=1
            total+=1
    with store.read_db() as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('SELECT COUNT(*) FROM games').fetchone()[0] == total
        assert db.execute('SELECT COUNT(*) FROM games WHERE pgn_text IS NOT NULL').fetchone()[0] == examples
        print(f'Generated {total} fictional finished games, {examples} PGN examples; integrity OK: {output_path}')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    generate(args.input,args.output)
