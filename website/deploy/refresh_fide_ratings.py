"""Back up the league and refresh every FIDE standard rating and country."""
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


def refresh_all(*,fetcher=None,output=print):
    totals={'updated':0,'failed':0,'skipped':0,'unrated':0}
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
                              limit=None,force=True,report=report)
    output(f"Updated: {totals['updated']} (unrated: {totals['unrated']}). "
           f"Failed: {totals['failed']}. Changed/skipped: {totals['skipped']}.")
    return totals


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-dir',type=Path,default=Path('/backups'))
    args=parser.parse_args()
    stamp=datetime.now(timezone.utc).strftime('fide-refresh-%Y%m%dT%H%M%S%fZ')
    snapshot=backup(store.DB_PATH,args.backup_dir/stamp,keep=0)
    print(f'Original database backup: {snapshot}',flush=True)
    store.init_db()
    totals=refresh_all(output=lambda line:print(line,flush=True))
    return 1 if totals['failed'] or totals['skipped'] else 0


if __name__=='__main__':
    raise SystemExit(main())
