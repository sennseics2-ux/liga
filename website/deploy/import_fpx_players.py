"""Import the requested AA Coimbra FPX entries as players without accounts."""
import argparse
import csv
from datetime import datetime,timezone
from pathlib import Path

import database as store
from deploy.backup_sqlite import backup

DATA=Path(__file__).resolve().parents[1]/'data_imports'/'aa_coimbra_2025_2026.csv'
SOURCE='fpx:aa-coimbra'


def load_entries(path=DATA):
    with Path(path).open(encoding='utf-8-sig',newline='') as file:
        rows=list(csv.DictReader(file))
    if len(rows)!=128 or rows[0]['fpx_id']!='759' or rows[-1]['fpx_id']!='53304':
        raise ValueError('Import must contain exactly the requested 128 FPX entries.')
    keys=set()
    for row in rows:
        key=row['fpx_id']
        if not key.isascii() or not key.isdecimal() or key in keys:
            raise ValueError('Every entry must have a distinct numeric FPX identifier.')
        keys.add(key)
        row['fide_id']=store.validate_player_fide_id(row['fide_id'])
        if not 2<=len(row['name'])<=80:
            raise ValueError('Invalid player name in the import file.')
    return rows


def import_entries():
    rows=load_entries()
    created=skipped=0
    with store.transaction() as db:
        for row in rows:
            if db.execute('SELECT 1 FROM player_import_records WHERE source=? AND record_key=?',
                          (SOURCE,row['fpx_id'])).fetchone():
                skipped+=1
                continue
            player_id=db.execute('''INSERT INTO players(name,club,fide_id,created_at)
                VALUES(?,?,?,?)''',(row['name'],'AA Coimbra',row['fide_id'],store.iso(store.now_utc()))).lastrowid
            db.execute('INSERT INTO player_import_records(source,record_key,player_id,imported_at) VALUES(?,?,?,?)',
                       (SOURCE,row['fpx_id'],player_id,store.iso(store.now_utc())))
            created+=1
    return created,skipped


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-dir',type=Path,default=Path('/backups'))
    args=parser.parse_args()
    # A backup precedes both schema updates and the atomic import.
    stamp=datetime.now(timezone.utc).strftime('fpx-import-%Y%m%dT%H%M%S%fZ')
    snapshot=backup(store.DB_PATH,args.backup_dir/stamp,keep=0)
    store.init_db()
    created,skipped=import_entries()
    print(f'Players added: {created}. Already imported: {skipped}. Login accounts created: 0.')
    print(f'Original database backup: {snapshot}')


if __name__=='__main__':
    main()
