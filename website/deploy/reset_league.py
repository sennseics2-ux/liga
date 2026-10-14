"""Prepare an empty league database with one existing admin; never alter source."""
import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile

import database as store
from deploy.backup_sqlite import readonly, validate


def prepare(source, output, admin_username=None):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output:
        raise ValueError('Prepared database must differ from the existing database.')
    if output.exists():
        raise FileExistsError('Prepared database already exists; choose a new output path.')
    with closing(readonly(source)) as db:
        db.row_factory = sqlite3.Row
        validate(db)
        admins = db.execute("SELECT * FROM users WHERE role='admin' ORDER BY id").fetchall()
        if admin_username:
            admins = [row for row in admins if row['username'].casefold()==admin_username.casefold()]
        if len(admins) != 1:
            raise ValueError('Expected one admin account. Use --admin-username to select the admin to keep.')
        admin = dict(admins[0])
        id_floor = db.execute('SELECT COALESCE(MAX(id),0) FROM users').fetchone()[0]
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
            sequence = db.execute("SELECT seq FROM sqlite_sequence WHERE name='users'").fetchone()
            if sequence:id_floor=max(id_floor,sequence[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.fresh-league-', dir=output.parent) as folder:
        candidate = Path(folder) / 'league.sqlite3'
        original_path = store.DB_PATH
        try:
            store.DB_PATH = candidate
            store.init_db()
            with store.transaction() as db:
                fields = {row[1] for row in db.execute('PRAGMA table_info(users)')}
                retained = {key:value for key,value in admin.items() if key in fields}
                retained.update(manager_active=0,player_active=0,manager_available=0,
                                auth_version=admin.get('auth_version',0)+1)
                columns = list(retained)
                # Column identifiers come only from the application's schema.
                db.execute('INSERT INTO users ('+','.join(columns)+') VALUES ('+
                           ','.join('?' for _ in columns)+')',list(retained.values()))
                # Deleted users' old session cookies must never match a newly registered user.
                db.execute("UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name='users'",(id_floor,))
            with closing(readonly(candidate)) as db:
                validate(db)
                if db.execute('SELECT count(*) FROM users').fetchone()[0] != 1:
                    raise RuntimeError('Prepared database must contain only the retained admin.')
                for table in ('teams','players','seasons','season_rounds','team_matches','games','auctions','bids'):
                    if db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]:
                        raise RuntimeError('Prepared database still contains league data.')
                snapshot = Path(folder) / 'prepared.sqlite3'
                with closing(sqlite3.connect(snapshot)) as target:
                    db.backup(target)
                    validate(target)
            snapshot.chmod(0o600)
            os.link(snapshot,output)  # Atomic install without overwriting any existing file.
        finally:
            store.DB_PATH = original_path
    return admin['username']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--admin-username')
    args=parser.parse_args()
    try:
        username=prepare(args.source,args.output,args.admin_username)
    except (ValueError,FileExistsError,FileNotFoundError) as exc:
        parser.exit(1,f'Not reset: {exc}\n')
    print(f'Fresh database prepared; retained admin: {username}. All other accounts and league records removed.')


if __name__=='__main__':
    main()
