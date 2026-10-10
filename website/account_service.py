"""Account profiles, recovery links, and administrator-controlled activation."""
from datetime import timedelta
import hashlib
import os
import re
import secrets
import smtplib
import sqlite3
from email.message import EmailMessage
from urllib.parse import urlsplit


def validate_email(value):
    value = str(value or '').strip().lower()
    if len(value) > 254 or value.count('@') != 1:
        raise ValueError('Enter a valid email address.')
    local, domain = value.split('@')
    if (not 1 <= len(local) <= 64 or local.startswith('.') or local.endswith('.') or '..' in local
            or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)
            or len(domain) > 253 or '.' not in domain):
        raise ValueError('Enter a valid email address.')
    labels = domain.split('.')
    if any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in labels):
        raise ValueError('Enter a valid email address.')
    if not re.fullmatch(r'[A-Za-z]{2,63}', labels[-1]):
        raise ValueError('Enter a valid email address.')
    return value


def validate_fide_id(value):
    value = str(value or '').strip()
    if value and not re.fullmatch(r'[0-9]{6,8}', value):
        raise ValueError('FIDE ID must contain 6 to 8 digits.')
    return value or None


def account(user_id):
    import database as store
    with store.read_db() as db:
        row = db.execute('''SELECT id,username,role,email,name,country,fide_id,fide_id_locked,
            account_active,fide_rating,fide_rating_month,fide_checked_at,fide_error
            FROM users WHERE id=?''', (user_id,)).fetchone()
    if not row:
        raise ValueError('Account not found.')
    return dict(row)


def update_profile(user_id, name, country, fide_id, *, email=None, current_password=None,
                   actor_id=None, fide_id_locked=None):
    import database as store
    name = str(name or '').strip()
    country = str(country or '').strip()
    fide_id = validate_fide_id(fide_id)
    if not 2 <= len(name) <= 80 or any(ord(c) < 32 for c in name):
        raise ValueError('Name must be 2–80 characters.')
    if len(country) > 80 or any(ord(c) < 32 for c in country):
        raise ValueError('Country must be 80 characters or fewer.')
    with store.read_db() as db:
        previous = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    if not previous:
        raise ValueError('Account not found.')
    normalized_email = validate_email(email) if email is not None else previous['email']
    email_changed = normalized_email != previous['email']
    if email_changed and (actor_id is not None or not store.verify_password(str(current_password or ''), previous['password_hash'])):
        raise ValueError('Enter your current password to change your recovery email.')
    with store.transaction() as db:
        user = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        if actor_id is not None:
            store._admin_actor(db, actor_id)
        elif not user['account_active']:
            raise ValueError('This account is deactivated.')
        if user['auth_version'] != previous['auth_version'] or user['email'] != previous['email']:
            raise ValueError('Your account changed. Refresh the page and try again.')
        if user['fide_id_locked'] and fide_id != user['fide_id'] and actor_id is None:
            raise ValueError('Your FIDE ID is locked by the administrator.')
        lock = user['fide_id_locked'] if actor_id is None or fide_id_locked is None else int(bool(fide_id_locked))
        changed = fide_id != user['fide_id']
        try:
            db.execute('''UPDATE users SET name=?,country=?,fide_id=?,fide_id_locked=?,email=?,
                fide_rating=CASE WHEN ? THEN NULL ELSE fide_rating END,
                fide_rating_month=CASE WHEN ? THEN NULL ELSE fide_rating_month END,
                fide_next_attempt=CASE WHEN ? THEN NULL ELSE fide_next_attempt END,
                fide_error=CASE WHEN ? THEN NULL ELSE fide_error END,
                fide_attempts=CASE WHEN ? THEN 0 ELSE fide_attempts END WHERE id=?''',
                (name,country,fide_id,lock,normalized_email,changed,changed,changed,changed,changed,user_id))
        except sqlite3.IntegrityError:
            raise ValueError('That email address is already associated with another account.') from None
        db.execute('UPDATE players SET name=?,rating=CASE WHEN ? THEN NULL ELSE rating END WHERE user_id=?', (name,changed,user_id))
        if email_changed:
            db.execute('DELETE FROM password_resets WHERE user_id=?', (user_id,))
        store._audit(db,'profile_updated','user',user_id,actor_id or user_id,'Account profile updated',
                     before={'name':user['name'],'country':user['country'],'fide_id':user['fide_id'],'fide_id_locked':user['fide_id_locked']},
                     after={'name':name,'country':country,'fide_id':fide_id,'fide_id_locked':lock})
    return changed and bool(fide_id)


def revoke_sessions(user_id):
    import database as store
    with store.transaction() as db:
        db.execute('UPDATE users SET auth_version=auth_version+1 WHERE id=?', (user_id,))
        db.execute('DELETE FROM password_resets WHERE user_id=?', (user_id,))


def set_account_active(user_id, active, *, actor_id, password=None):
    import database as store
    if user_id == actor_id and not active:
        with store.read_db() as db:
            user = db.execute('SELECT password_hash FROM users WHERE id=?', (user_id,)).fetchone()
        if not user or not store.verify_password(str(password or ''),user['password_hash']):
            raise ValueError('Enter your current password to deactivate your account.')
    with store.transaction() as db:
        if active or actor_id != user_id:
            store._admin_actor(db,actor_id)
        user = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        if not user:
            raise ValueError('Account not found.')
        if actor_id==user_id and not user['account_active']:
            raise ValueError('This account is deactivated.')
        if user['role']=='admin' and not active and user['account_active']:
            if db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND account_active=1").fetchone()[0] <= 1:
                raise ValueError('The last active administrator cannot deactivate their account.')
        if bool(user['account_active']) == bool(active):
            return
        db.execute('UPDATE users SET account_active=?,auth_version=auth_version+1 WHERE id=?', (int(active),user_id))
        db.execute('DELETE FROM password_resets WHERE user_id=?', (user_id,))
        if not active:
            for a in db.execute("SELECT a.id FROM auctions a JOIN players p ON p.id=a.player_id WHERE p.user_id=? AND a.status='open'",(user_id,)).fetchall():
                store._fail_auction(db,a['id'],'Player account deactivated.',actor_id)
            db.execute("UPDATE role_requests SET status='cancelled',reviewed_at=? WHERE user_id=? AND status='pending'", (store.iso(store.now_utc()),user_id))
            db.execute("UPDATE manager_invitations SET status='cancelled',responded_at=? WHERE manager_id=? AND status='pending'",(store.iso(store.now_utc()),user_id))
            team=db.execute('SELECT id FROM teams WHERE manager_id=?',(user_id,)).fetchone()
            if team:
                store._unassign_manager(db,team['id'],'account deactivated')
            db.execute('UPDATE users SET manager_available=0 WHERE id=?', (user_id,))
        store._audit(db,'account_reactivated' if active else 'account_deactivated','user',user_id,actor_id,
                     'Account activation changed',before={'active':bool(user['account_active'])},after={'active':bool(active)})


def issue_reset(username, email):
    import database as store
    try:
        email=validate_email(email)
    except ValueError:
        return None
    username=str(username or '').strip()
    if not 3 <= len(username) <= 32:
        return None
    raw=secrets.token_urlsafe(32)
    digest=hashlib.sha256(raw.encode()).hexdigest()
    with store.transaction() as db:
        user=db.execute('''SELECT id,auth_version FROM users WHERE username=? COLLATE NOCASE
            AND email=? COLLATE NOCASE AND account_active=1''',(username,email)).fetchone()
        if not user:
            return None
        db.execute('DELETE FROM password_resets WHERE user_id=? OR expires_at<?',(user['id'],store.iso(store.now_utc())))
        db.execute('''INSERT INTO password_resets(token_hash,user_id,auth_version,email,expires_at,created_at)
            VALUES(?,?,?,?,?,?)''',(digest,user['id'],user['auth_version'],email,
                store.iso(store.now_utc()+timedelta(hours=1)),store.iso(store.now_utc())))
    return raw


def reset_password(raw_token, password):
    import database as store
    if not re.fullmatch(r'[A-Za-z0-9_-]{40,80}',str(raw_token or '')):
        raise ValueError('This recovery link is invalid or expired.')
    if not isinstance(password,str) or not 12 <= len(password) <= 256:
        raise ValueError('Password must contain 12–256 characters.')
    digest=hashlib.sha256(raw_token.encode()).hexdigest()
    replacement=store.hash_password(password)
    with store.transaction() as db:
        row=db.execute('''SELECT r.*,u.auth_version AS current_version,u.email AS current_email,u.account_active
            FROM password_resets r JOIN users u ON u.id=r.user_id WHERE token_hash=?''',(digest,)).fetchone()
        if (not row or row['used_at'] or row['expires_at'] <= store.iso(store.now_utc()) or
                not row['account_active'] or row['auth_version'] != row['current_version'] or row['email'] != row['current_email']):
            raise ValueError('This recovery link is invalid or expired.')
        db.execute('UPDATE users SET password_hash=?,auth_version=auth_version+1 WHERE id=?',(replacement,row['user_id']))
        db.execute('DELETE FROM password_resets WHERE user_id=?',(row['user_id'],))


def send_recovery(username, email):
    """Background task; never log tokens, recipients, credentials, or reset links."""
    import logging
    public=os.getenv('CHESS_PUBLIC_URL','').rstrip('/')
    host=os.getenv('CHESS_SMTP_HOST','')
    sender=os.getenv('CHESS_SMTP_FROM','')
    if not host or not sender or urlsplit(public).scheme != 'https' or not urlsplit(public).netloc:
        logging.getLogger(__name__).warning('Password recovery SMTP or public HTTPS URL is not configured.')
        return
    token=issue_reset(username,email)
    if token is None:
        return
    email=validate_email(email)
    message=EmailMessage()
    message['Subject']='Liga SX-AAC — Password recovery / Recuperar palavra-passe'
    message['From']=sender;message['To']=email
    message.set_content('Reset your password / Redefina a sua palavra-passe:\n\n'+public+'/reset-password#token='+token+
        '\n\nThis link expires in 1 hour and can be used once. Ignore it if you did not request it.\n'
        'Esta ligação expira numa hora e só pode ser utilizada uma vez. Ignore-a se não pediu a recuperação.\n')
    try:
        mode=os.getenv('CHESS_SMTP_SECURITY','starttls')
        if mode not in ('starttls','ssl'):
            raise ValueError('SMTP must use TLS.')
        import ssl
        context=ssl.create_default_context()
        if mode=='ssl':
            client=smtplib.SMTP_SSL(host,int(os.getenv('CHESS_SMTP_PORT','465')),timeout=15,context=context)
        else:
            client=smtplib.SMTP(host,int(os.getenv('CHESS_SMTP_PORT','587')),timeout=15)
        with client:
            if mode=='starttls':
                client.starttls(context=context)
            username=os.getenv('CHESS_SMTP_USER','')
            if username:
                client.login(username,os.getenv('CHESS_SMTP_PASSWORD',''))
            client.send_message(message)
    except Exception:
        logging.getLogger(__name__).error('Password recovery email delivery failed. Check SMTP configuration.')
