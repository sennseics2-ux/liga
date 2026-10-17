"""Back up the league and refresh FIDE standard ratings and federation countries."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
import time
from urllib.error import HTTPError

import database as store
import fide_ratings
from deploy.backup_sqlite import backup


def paced_fetcher(fetcher,*,sleep=time.sleep,clock=time.monotonic):
    """Space public API requests and retry short provider rate limits twice."""
    last_request=None
    def fetch(fide_id):
        nonlocal last_request
        for attempt in range(3):
            if last_request is not None:
                sleep(max(0,1-(clock()-last_request)))
            last_request=clock()
            try:
                return fetcher(fide_id)
            except HTTPError as error:
                if error.code!=429 or attempt==2:
                    raise
                delay=5*2**attempt
                retry_after=error.headers.get('Retry-After','') if error.headers else ''
                if retry_after.isascii() and retry_after.isdecimal():
                    delay=max(delay,int(retry_after))
                # Longer limits are handled by the persistent retry schedule.
                if delay>30:
                    raise
                error.close()
                sleep(delay)
    return fetch


def rated_records_without_flags():
    """Include blank and unrecognised countries; linked players use their account."""
    from countries import country_code
    with store.read_db() as db:
        records=[{**dict(row),'kind':'user'} for row in db.execute(
            'SELECT id,fide_id,fide_rating AS rating,country FROM users WHERE fide_rating>0')]
        records += [{**dict(row),'kind':'player'} for row in db.execute(
            'SELECT id,fide_id,rating,country FROM players WHERE user_id IS NULL AND rating>0')]
    return [row for row in records if country_code(row['country']) is None]


def refresh_all(*,fetcher=None,output=print,rated_without_flag=False):
    totals={'updated':0,'failed':0,'skipped':0,'unrated':0}
    if rated_without_flag:
        records=rated_records_without_flags()
        output(f'Targeted refresh: {len(records)} rated records without a recognised country flag.')
    def report(record):
        status=record['status']
        totals[status]+=1
        if status=='updated':
            if record['rating'] is None:
                totals['unrated']+=1
            detail=str(record['rating']) if record['rating'] is not None else 'unrated'
            if record['month']:
                detail+=f" ({record['month']})"
            detail+=f"; country: {record['country']}" if record.get('country') else '; country unchanged'
        elif status=='failed':
            detail='lookup failed; previous rating and country preserved; retry scheduled'
        else:
            detail='record changed during lookup; not updated'
        output(f"{record['kind']} {record['id']}, FIDE {record['fide_id']}: {detail}")
    fide_ratings.sync_ratings(fetcher=fetcher or paced_fetcher(fide_ratings.fetch_player_details),
                              limit=None,force=True,report=report,rated_without_flag=rated_without_flag)
    output(f"Updated: {totals['updated']} (unrated: {totals['unrated']}). "
           f"Failed: {totals['failed']}. Changed/skipped: {totals['skipped']}.")
    if rated_without_flag:
        remaining=rated_records_without_flags()
        totals['without_flag']=len(remaining)
        missing_id=sum(not str(row['fide_id'] or '').strip() for row in remaining)
        output(f"Still rated without a country flag: {len(remaining)} (without a FIDE ID: {missing_id}).")
    return totals


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rated-without-flag',action='store_true',
                        help='Refresh only rated records with a blank or unrecognised country.')
    parser.add_argument('--dry-run',action='store_true',help='List the --rated-without-flag selection without changing the database.')
    parser.add_argument('--backup-dir',type=Path,default=Path('/backups'))
    args=parser.parse_args()
    if args.dry_run:
        if not args.rated_without_flag:
            parser.error('--dry-run requires --rated-without-flag')
        records=rated_records_without_flags()
        for row in records:
            fide_id=row['fide_id'] or 'missing'
            print(f"{row['kind']} {row['id']}, FIDE {fide_id}, rating {row['rating']}",flush=True)
        print(f'Selected rated records without a country flag: {len(records)}.',flush=True)
        return 0
    stamp=datetime.now(timezone.utc).strftime('fide-refresh-%Y%m%dT%H%M%S%fZ')
    snapshot=backup(store.DB_PATH,args.backup_dir/stamp,keep=0)
    print(f'Original database backup: {snapshot}',flush=True)
    store.init_db()
    totals=refresh_all(output=lambda line:print(line,flush=True),rated_without_flag=args.rated_without_flag)
    return 1 if totals['failed'] or totals['skipped'] or totals.get('without_flag',0) else 0


if __name__=='__main__':
    raise SystemExit(main())
