"""Back up the league and fill only blank countries using FIDE federations."""
import argparse
from datetime import datetime,timezone
from pathlib import Path

import database as store
from fide_ratings import fetch_federation_country
from deploy.backup_sqlite import backup
from deploy.refresh_fide_ratings import paced_fetcher


def fill_missing(*,fetcher=None,output=print):
    fetcher=fetcher or paced_fetcher(fetch_federation_country)
    totals={'updated':0,'unknown':0,'failed':0,'skipped':0}
    with store.read_db() as db:
        records=[{**dict(row),'kind':'user'} for row in db.execute('''
            SELECT id,fide_id,id AS user_id,country FROM users
            WHERE trim(coalesce(fide_id,''))!=''
            ORDER BY id''') if not str(row['country'] or '').strip()]
        records += [{**dict(row),'kind':'player'} for row in db.execute('''
            SELECT p.id,p.user_id,p.country,CASE WHEN p.user_id IS NULL THEN p.fide_id ELSE u.fide_id END AS fide_id
            FROM players p LEFT JOIN users u ON u.id=p.user_id
            WHERE trim(coalesce(CASE WHEN p.user_id IS NULL THEN p.fide_id ELSE u.fide_id END,''))!=''
            ORDER BY p.id''') if not str(row['country'] or '').strip()]
    lookups={}
    for record in records:
        fid=record['fide_id']
        if fid not in lookups:
            try:
                lookups[fid]=(fetcher(fid),False)
            except Exception:
                lookups[fid]=(None,True)
        country,failed=lookups[fid]
        if failed:
            status='failed';detail='lookup failed; country unchanged; rerun to retry'
        elif country is None:
            status='unknown';detail='country unresolved after provider and official FIDE checks; needs review'
        else:
            with store.transaction() as db:
                if record['kind']=='user':
                    current=db.execute('SELECT country,fide_id,id AS user_id FROM users WHERE id=?',(record['id'],)).fetchone()
                    table='users'
                else:
                    current=db.execute('''SELECT p.country,p.user_id,
                        CASE WHEN p.user_id IS NULL THEN p.fide_id ELSE u.fide_id END AS fide_id
                        FROM players p LEFT JOIN users u ON u.id=p.user_id WHERE p.id=?''',(record['id'],)).fetchone()
                    table='players'
                if (current and not str(current['country'] or '').strip()
                        and current['fide_id']==fid and current['user_id']==record['user_id']):
                    db.execute(f'UPDATE {table} SET country=? WHERE id=?',(country,record['id']))
                    status='updated';detail=country
                else:
                    status='skipped';detail='record changed during lookup; country unchanged'
        totals[status]+=1
        output(f"{record['kind']} {record['id']}, FIDE {fid}: {detail}")
    output(f"Countries filled: {totals['updated']}. Unknown federation: {totals['unknown']}. "
           f"Failed: {totals['failed']}. Changed/skipped: {totals['skipped']}.")
    return totals


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-dir',type=Path,default=Path('/backups'))
    args=parser.parse_args()
    stamp=datetime.now(timezone.utc).strftime('missing-countries-%Y%m%dT%H%M%S%fZ')
    snapshot=backup(store.DB_PATH,args.backup_dir/stamp,keep=0)
    print(f'Original database backup: {snapshot}',flush=True)
    store.init_db()
    totals=fill_missing(output=lambda line:print(line,flush=True))
    return 1 if totals['unknown'] or totals['failed'] or totals['skipped'] else 0


if __name__=='__main__':
    raise SystemExit(main())
