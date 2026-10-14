"""FIDE standard-rating synchronization with persistent retry scheduling."""
from datetime import datetime, timedelta, timezone
import json
import os
import re
import threading
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class ProviderRedirects(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        target=urlsplit(newurl)
        if target.scheme!='https' or target.hostname not in ('fideratings.com','www.fideratings.com'):
            raise ValueError('Unexpected FIDE API redirect.')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def urlopen(request,timeout):
    return build_opener(ProviderRedirects()).open(request,timeout=timeout)
from zoneinfo import ZoneInfo

_wake=threading.Event()
DEFAULT_URL='https://fideratings.com/api/player/{fide_id}/current'
DEFAULT_RATING_FIELD='current.standard.rating'
DEFAULT_MONTH_FIELD='current.standard.date'


def wake_rating_worker():
    _wake.set()


def take_wake():
    requested=_wake.is_set()
    _wake.clear()
    return requested


def _field(payload, path):
    for part in path.split('.'):
        if isinstance(payload,list) and part.isascii() and part.isdigit() and int(part)<len(payload):
            payload=payload[int(part)]
        elif isinstance(payload,dict) and part in payload:
            payload=payload[part]
        else:
            raise ValueError('FIDE API response is missing the configured field.')
    return payload


def fetch_standard_rating(fide_id):
    from database import validate_player_fide_id
    fide_id=validate_player_fide_id(fide_id)
    if fide_id is None:
        raise ValueError('FIDE ID is required for rating lookup.')
    template=os.getenv('CHESS_FIDE_API_URL_TEMPLATE') or DEFAULT_URL
    if not template or '{fide_id}' not in template:
        raise ValueError('FIDE API configuration is missing.')
    url=template.replace('{fide_id}',fide_id)
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in ('fideratings.com','www.fideratings.com') or parsed.username or parsed.password:
        raise ValueError('FIDE API must use the requested HTTPS provider.')
    headers={'Accept':'application/json','User-Agent':'LigaSX-AAC/25'}
    key=os.getenv('CHESS_FIDE_API_KEY','')
    if key:
        header=os.getenv('CHESS_FIDE_API_KEY_HEADER','Authorization')
        if header.lower() not in ('authorization','x-api-key','x-fideratings-key'):
            raise ValueError('Unsupported FIDE API key header.')
        headers[header]=key
    with urlopen(Request(url,headers=headers),timeout=10) as response:
        final=urlsplit(response.geturl())
        if final.scheme!='https' or final.hostname not in ('fideratings.com','www.fideratings.com'):
            raise ValueError('Unexpected FIDE API redirect.')
        data=response.read(262145)
        if len(data)>262144:
            raise ValueError('FIDE API response is too large.')
        payload=json.loads(data)
    rating_path=os.getenv('CHESS_FIDE_RATING_FIELD') or DEFAULT_RATING_FIELD
    month_path=os.getenv('CHESS_FIDE_MONTH_FIELD',DEFAULT_MONTH_FIELD)
    if template==DEFAULT_URL:
        if str(payload.get('fideid'))!=fide_id or not isinstance(payload.get('current'),dict):
            raise ValueError('FIDE API returned an unexpected player.')
        standard=payload['current'].get('standard')
        if standard is None:
            return None,None
        # Former list members retain a last-known historical rating. Avoid
        # treating its old month as a delayed current publication forever.
        if payload.get('current_source')=='last_known_profile':
            month_path=''
    raw=_field(payload,rating_path)
    if isinstance(raw,bool):
        raise ValueError('FIDE standard rating is invalid.')
    if raw in (None,'',0,'0','N/A'):
        rating=None
    elif not re.fullmatch(r'[0-9]{3,4}',str(raw)) or not 100 <= int(raw) <= 4000:
        raise ValueError('FIDE standard rating is invalid.')
    else:
        rating=int(raw)
    month=str(_field(payload,month_path))[:7] if month_path else None
    if month and not re.fullmatch(r'\d{4}-(?:0[1-9]|1[0-2])',month):
        raise ValueError('FIDE publication month is invalid.')
    return rating,month


def next_success(now, month):
    local=now.astimezone(ZoneInfo('Europe/Lisbon'))
    if month and month < local.strftime('%Y-%m'):
        return now+timedelta(hours=6)
    if local.day==1 or (not month and local.day<7):
        return (local+timedelta(days=1)).replace(hour=3,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
    return datetime(local.year+int(local.month==12),local.month%12+1,1,3,tzinfo=ZoneInfo('Europe/Lisbon')).astimezone(timezone.utc)


def sync_ratings(*, fetcher=None, limit=10):
    import database as store
    now=store.now_utc()
    fetcher=fetcher or fetch_standard_rating
    with store.read_db() as db:
        users=[{**dict(row),'kind':'user'} for row in db.execute('''SELECT id,fide_id,fide_attempts FROM users
            WHERE account_active=1 AND fide_id IS NOT NULL AND (fide_next_attempt IS NULL OR fide_next_attempt<=?)
            ORDER BY fide_next_attempt,id LIMIT ?''',(store.iso(now),limit))]
        players=[{**dict(row),'kind':'player'} for row in db.execute('''SELECT id,fide_id,fide_attempts FROM players
            WHERE user_id IS NULL AND fide_id IS NOT NULL AND (fide_next_attempt IS NULL OR fide_next_attempt<=?)
            ORDER BY fide_next_attempt,id LIMIT ?''',(store.iso(now),max(0,limit-len(users))))]
    completed=0
    for user in users+players:
        try:
            rating,month=fetcher(user['fide_id'])
            error=None;attempts=0;next_time=next_success(now,month)
        except Exception:
            rating=month=None;error='Rating lookup failed; retry scheduled.'
            attempts=user['fide_attempts']+1
            next_time=now+timedelta(minutes=min(360,5*2**min(attempts-1,7)))
        with store.transaction() as db:
            if user['kind']=='user':
                current=db.execute('SELECT fide_id,account_active FROM users WHERE id=?',(user['id'],)).fetchone()
                valid=current and current['account_active']
            else:
                current=db.execute('SELECT fide_id,user_id FROM players WHERE id=?',(user['id'],)).fetchone()
                valid=current and current['user_id'] is None
            if not valid or current['fide_id']!=user['fide_id']:
                continue
            table='users' if user['kind']=='user' else 'players'
            rating_field='fide_rating' if user['kind']=='user' else 'rating'
            if error is None:
                db.execute(f'UPDATE {table} SET {rating_field}=?,fide_rating_month=? WHERE id=?',(rating,month,user['id']))
                if user['kind']=='user':
                    db.execute('UPDATE players SET rating=? WHERE user_id=?',(rating,user['id']))
                completed+=1
            db.execute(f"""UPDATE {table} SET fide_checked_at=?,fide_next_attempt=?,fide_error=?,fide_attempts=? WHERE id=?""",
                       (store.iso(now),store.iso(next_time),error,attempts,user['id']))
    return completed
