"""Chess Fantasy League: server-rendered FastAPI web application."""
import asyncio
import io
import json
import warnings
import os
import re
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Query
from starlette.datastructures import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi.responses import HTMLResponse, RedirectResponse, Response, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from deploy.security import allowed as auth_rate_allowed, MAX_REQUEST_BYTES
from web_security import (BoundedRequestBodyMiddleware, parse_secure_form,
                          safe_return_path, browser_http_exception_handler, website_request_limit)
from web_queries import authenticate_account, team_for_member, close_auction_safely, AccountDeactivated

import database as store
from countries import country_field, country_code
import account_service as accounts
import league_seasons as seasons
from league_honours import season_honours
from player_statistics import player_totals, team_season_scores
from league_standings import season_table, current_table

BASE_DIR = Path(__file__).resolve().parent
MAX_PHOTO_BYTES = 5 * 1024 * 1024
# Cap decompression as well as compressed upload size.
Image.MAX_IMAGE_PIXELS = 12_000_000
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def local_time(value):
    """Display club dates in Lisbon, with an explicit zone and UTC storage."""
    try:
        date = datetime.fromisoformat(str(value))
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        local = date.astimezone(ZoneInfo('Europe/Lisbon'))
        return local.strftime('%Y-%m-%d · %H:%M %Z') + ' (Europe/Lisbon)'
    except (ValueError, TypeError):
        return '—'


def game_long_date(value):
    """English fallback for the game list; client localizes the Lisbon calendar date."""
    try:
        day = datetime.fromisoformat(local_time(value)[:10])
        return f"{day.day} {day.strftime('%B %Y')}"
    except (ValueError, TypeError):
        return '—'


def replay_time(value):
    """Compact review timestamp in Lisbon, with city localized by the template."""
    local = local_time(value)
    try:
        day = datetime.fromisoformat(local[:10])
        return day.strftime('%d-%m-%Y') + local[10:18]
    except (ValueError, TypeError):
        return '—'


TEMPLATES.env.filters['game_long_date'] = game_long_date
TEMPLATES.env.filters['replay_time'] = replay_time
TEMPLATES.env.filters['local_time'] = local_time
TEMPLATES.env.filters['local_date'] = lambda value: '.'.join(reversed(local_time(value)[:10].split('-'))) if value else '—'


async def rating_loop():
    import fide_ratings
    ticks=30
    while True:
        if ticks>=30 or fide_ratings.take_wake():
            ticks=0
            try:
                await run_in_threadpool(fide_ratings.sync_ratings)
            except Exception:
                import logging
                logging.getLogger(__name__).error('Rating synchronization failed; the worker will retry.')
        await asyncio.sleep(2)
        ticks+=1


async def expiry_loop():
    tick = 0
    while True:
        await asyncio.sleep(2)
        tick += 1
        try:
            if tick % 15 == 0:
                await asyncio.to_thread(store.settle_expired)
        except Exception as exc:
            print(f"Periodic settlement error: {exc}", flush=True)


@asynccontextmanager
async def lifespan(app):
    await run_in_threadpool(store.init_db)
    await run_in_threadpool(store.settle_expired)
    task = asyncio.create_task(expiry_loop())
    ratings_task = asyncio.create_task(rating_loop())
    try:
        yield
    finally:
        task.cancel()
        ratings_task.cancel()
        await asyncio.gather(task,ratings_task,return_exceptions=True)


PRODUCTION = os.getenv("CHESS_ENV", "development").lower() == "production"
ALLOWED_HOSTS = [h.strip() for h in os.getenv("CHESS_ALLOWED_HOSTS", "").split(",") if h.strip()]
if PRODUCTION:
    if not ALLOWED_HOSTS or any('*' in host for host in ALLOWED_HOSTS):
        raise RuntimeError("Production requires exact CHESS_ALLOWED_HOSTS (no wildcards).")
    if os.getenv("CHESS_HTTPS_ONLY") != "1":
        raise RuntimeError("Production requires CHESS_HTTPS_ONLY=1 behind a working HTTPS proxy.")
    configured_secret = os.getenv("CHESS_SESSION_SECRET", "")
    if len(configured_secret) < 32 or 'REPLACE' in configured_secret.upper() or 'CHANGE_ME' in configured_secret.upper():
        raise RuntimeError("Set a permanent random CHESS_SESSION_SECRET of at least 32 characters.")

app = FastAPI(title="Liga SX-AAC", lifespan=lifespan,
              docs_url=None if PRODUCTION else '/docs',
              redoc_url=None if PRODUCTION else '/redoc',
              openapi_url=None if PRODUCTION else '/openapi.json')
if PRODUCTION:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
secret = os.getenv("CHESS_SESSION_SECRET", "")
if not secret:
    secret = secrets.token_hex(32)
    print("WARNING: CHESS_SESSION_SECRET not set; login sessions reset on restart. Set it before production.")
app.add_middleware(SessionMiddleware, secret_key=secret, same_site="lax",
                   https_only=os.getenv("CHESS_HTTPS_ONLY") == "1", max_age=60 * 60 * 24 * 14)
app.add_middleware(BoundedRequestBodyMiddleware, max_bytes=MAX_REQUEST_BYTES,
                   request_limit=website_request_limit)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def session_user(request):
    uid = request.session.get("user_id")
    if not isinstance(uid, int):
        return None
    with store.read_db() as db:
        row = db.execute("SELECT id,username,role,name,account_active,manager_active,player_active,manager_available,auth_version FROM users WHERE id=?", (uid,)).fetchone()
    if not row or not row['account_active'] or request.session.get('auth_version', 0) != row['auth_version']:
        request.session.clear()
        return None
    return dict(row)


def csrf_token(request):
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return request.session["csrf"]


async def form_data(request):
    path = request.url.path
    files = ('photo',) if path == '/my/player/photo' or re.fullmatch(r'/teams/\d+/photo', path) else (
        ('pgn',) if re.fullmatch(r'/admin/games/\d+/(pgn|result)', path) else ())
    return await parse_secure_form(request, csrf_token, allowed_files=files,
                                   allowed_fields=expected_form_fields(path))


def expected_form_fields(path):
    """Keep mutations small and prevent unexpected uploaded form content."""
    fields = {
        '/register': ('username', 'password', 'role', 'next', 'email'),
        '/login': ('username', 'password', 'next'),
        '/logout': (),
        '/forgot-password': ('username', 'email'),
        '/reset-password': ('token','password','confirm_password'),
        '/account/settings': ('name','country','fide_id','email','current_password'),
        '/account/deactivate': ('current_password','confirmation'),
        '/admin/seasons': ('start_year','start_date','end_date','round_count'),
        '/account/security': ('current_password', 'new_password', 'confirm_password'),
        '/my/player/photo': (), '/my/player/photo/remove': (),
        '/my/manager/availability': ('available',),
        '/my/manager/resign': ('confirmation',),
        '/admin/teams': ('name',),
        '/admin/players': ('name', 'club', 'rating', 'user_id'),
        '/admin/auctions': ('player_id', 'starting_price', 'duration_hours'),
        '/admin/games': ('white_player_id', 'black_player_id', 'scheduled_at', 'event_name', 'round_label'),
    }
    if path in fields:
        return fields[path]
    patterns = (
        (r'/admin/players/\d+/country', ('country',)),
        (r'/admin/players/\d+/name', ('name','original_name')),
        (r'/admin/teams/\d+/name', ('name','original_name')),
        (r'/admin/users/\d+/profile', ('name','country','fide_id','fide_id_locked')),
        (r'/admin/users/\d+/activation', ('active','confirmation')),
        (r'/admin/seasons/\d+/edit', ('start_year','start_date','end_date','round_count')),
        (r'/admin/seasons/\d+/publish', ()),
        (r'/admin/seasons/\d+/matches', ('round_id','home_team_id','away_team_id','scheduled_at','location')),
        (r'/admin/matches/\d+/edit', ('round_id','home_team_id','away_team_id','scheduled_at','location')),
        (r'/matches/\d+/lineup', ('player_1','player_2','player_3','player_4')),

        (r'/my/roles/(manager|player)/(quit|request)', ()),
        (r'/my/manager/invitations/\d+/respond', ('decision',)),
        (r'/my/manager/players/\d+/kick', ('confirmation',)),
        (r'/auctions/\d+/bid', ('amount',)),
        (r'/admin/games/\d+/result', ('result', 'reason')),
        (r'/admin/games/\d+/pgn', ('reason',)),
        (r'/admin/games/\d+/pgn/remove', ('reason',)),
        (r'/admin/teams/\d+/manager', ('manager_id',)),
        (r'/admin/teams/\d+/remove-manager', ('confirmation',)),
        (r'/admin/invitations/\d+/cancel', ()),
        (r'/admin/role-requests/\d+/review', ('decision',)),
        (r'/admin/auctions/\d+/(close|cancel|retry)', ('reason',)),
        (r'/admin/players/\d+/points', ('adjustment', 'reason')),
    )
    return next((allowed for pattern, allowed in patterns if re.fullmatch(pattern, path)), ())


INTERFACE_COPY = json.loads((BASE_DIR / 'static' / 'pt-PT.json').read_text())


def captain_copy(text):
    # Only known interface copy is renamed; account names and stored history stay literal.
    if text not in INTERFACE_COPY:
        return text
    replacements = {'manager':'captain','managers':'captains','Manager':'Captain',
                    'Managers':'Captains','MANAGER':'CAPTAIN','MANAGERS':'CAPTAINS'}
    return re.sub(r'\b(?:manager|managers|Manager|Managers|MANAGER|MANAGERS)\b',
                  lambda match: replacements[match[0]], text)


def flash(request, message, kind="info", *, key=None, values=None):
    message = captain_copy(message)
    key = captain_copy(key) if key else None
    if values and 'role' in values:
        values = {**values, 'role': captain_copy(values['role'])}
    request.session['flash'] = {'message': message, 'kind': kind,
                                'key': key or message, 'values': values or {}}


def redirect(path):
    return RedirectResponse(path, status_code=303)


def auth(request, role=None):
    user = session_user(request)
    if not user:
        raise HTTPException(401, "Log in to continue.")
    if role == "admin" and user["role"] != "admin":
        raise HTTPException(403, "You do not have permission to do that.")
    if role in ("manager", "player") and (user["role"] == "admin" or not user[f"{role}_active"]):
        raise HTTPException(403, "Your role is not active.")
    return user


def view(request, name, **context):
    user = session_user(request)
    data = {
        "request": request,
        "user": user,
        "csrf": csrf_token(request),
        "flash": request.session.pop("flash", None),
        "page": name,
        "now": store.iso(store.now_utc()),
        **context,
    }
    response = TEMPLATES.TemplateResponse(request, name, data)
    # Session-dependent responses must not be reused by shared caches.
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Vary'] = 'Cookie'
    return response


def render_http_error(request, status, detail, recovery_url):
    response = view(request, 'error.html', status_code=status,
                    title='Refresh and try again' if status == 403 else 'Unable to open this page',
                    message=captain_copy(detail), recovery_url=recovery_url,
                    login_url='/login?next=' + quote(safe_return_path(recovery_url), safe=''))
    response.status_code = status
    return response


app.add_exception_handler(StarletteHTTPException, browser_http_exception_handler(render_http_error))


def parse_optional_int(value, *, minimum=None, maximum=None):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if not re.fullmatch(r'-?\d+', text):
        return None
    number = int(text)
    if minimum is not None and number < minimum:
        number = minimum
    if maximum is not None and number > maximum:
        number = maximum
    return number


def get_team(db, user):
    if not user or not user["manager_active"]:
        return None
    return db.execute("SELECT * FROM teams WHERE manager_id=?", (user["id"],)).fetchone()


def auction_rows(db, status="open"):
    return db.execute("""
        SELECT a.*, p.name AS player_name, p.club, p.rating,
               st.name AS seller_name, wt.name AS winner_name,
               (SELECT COUNT(*) FROM bids WHERE auction_id=a.id) AS bid_count,
               (SELECT amount FROM bids WHERE auction_id=a.id ORDER BY amount DESC,id ASC LIMIT 1) AS high_bid,
               (SELECT team_id FROM bids WHERE auction_id=a.id ORDER BY amount DESC,id ASC LIMIT 1) AS high_bid_team_id
        FROM auctions a JOIN players p ON p.id=a.player_id
        LEFT JOIN teams st ON st.id=a.seller_team_id
        LEFT JOIN teams wt ON wt.id=a.winner_team_id
        WHERE a.status=? ORDER BY CASE WHEN a.status='open' THEN a.ends_at END ASC, a.id DESC
    """, (status,)).fetchall()


@app.middleware("http")
async def headers(request, call_next):
    if PRODUCTION:
        if request.method == 'POST' and not auth_rate_allowed(
                request.client.host if request.client else None, request.url.path):
            return PlainTextResponse('Too many attempts. Please try again later.',
                                     status_code=429, headers={'Retry-After': '600'})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    if not request.url.path.startswith('/static/'):
        response.headers.setdefault('Cache-Control', 'private, no-store')
        response.headers.setdefault('Vary', 'Cookie')
    if PRODUCTION:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
            "form-action 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; connect-src 'self'"
        )
    return response


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    store.settle_expired()
    with store.read_db() as db:
        open_auctions = auction_rows(db)[:3]
        totals = {
            "managers": db.execute("SELECT COUNT(*) FROM users WHERE manager_active=1").fetchone()[0],
            "players": db.execute("SELECT COUNT(*) FROM players").fetchone()[0],
            "auctions": db.execute("SELECT COUNT(*) FROM auctions WHERE status='open'").fetchone()[0],
        }
    return view(request, "home.html", auctions=open_auctions, totals=totals)


@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    if session_user(request):
        return redirect("/dashboard")
    return view(request, "auth.html", mode="register", error=None,
                next=safe_return_path(request.query_params.get('next')))


@app.post("/register")
async def register(request: Request):
    data = await form_data(request)
    username = str(data.get("username", "")).strip()
    role = str(data.get("role", "")).strip()
    password = str(data.get("password", ""))
    next_path = safe_return_path(data.get('next'))
    try:
        email = accounts.validate_email(data.get('email'))
        user_id = await run_in_threadpool(store.create_account, username, password, role, email)
    except ValueError as exc:
        return await run_in_threadpool(view, request, "auth.html", mode="register", error=str(exc), username=username, selected_role=role, email=str(data.get('email','')), next=next_path)
    request.session.clear()
    request.session["user_id"] = user_id
    request.session["auth_version"] = 0
    flash(request, ("Account created. Visit your member profile to review manager invitations and availability." if role == "manager"
                    else "Player account created. The administrator can now activate your chess profile."), "success")
    return redirect(next_path)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    next_path = safe_return_path(request.query_params.get('next'), '')
    if session_user(request):
        return redirect(next_path or '/dashboard')
    return view(request, "auth.html", mode="login", error=None, next=next_path)


@app.post("/login")
async def login(request: Request):
    data = await form_data(request)
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    next_path = safe_return_path(data.get('next'), '')
    try:
        user = await run_in_threadpool(authenticate_account, username, password)
    except AccountDeactivated as exc:
        return await run_in_threadpool(view, request, "auth.html", mode="login", error=str(exc), username=username, next=next_path)
    if not user:
        return await run_in_threadpool(view, request, "auth.html", mode="login", error="Incorrect username or password.", username=username, next=next_path)
    request.session.clear()
    request.session["user_id"] = user["id"]
    request.session["auth_version"] = user["auth_version"]
    return redirect(next_path or ('/admin' if user['role'] == 'admin' else '/dashboard'))


@app.post("/logout")
async def logout(request: Request):
    await form_data(request)
    user = await run_in_threadpool(session_user, request)
    if user:
        await run_in_threadpool(accounts.revoke_sessions, user['id'])
    request.session.clear()
    return redirect("/")


@app.get('/account/profile', response_class=HTMLResponse)
def own_profile(request: Request):
    user = auth(request)
    if user['role'] == 'admin':
        return view(request, 'administrator_profile.html')
    return redirect(f'/users/{quote(user["username"], safe="")}')


@app.get('/account/security', response_class=HTMLResponse)
def security_form(request: Request):
    auth(request)
    return view(request, 'account_security.html', error=None)


@app.post('/account/security', response_class=HTMLResponse)
async def update_password(request: Request):
    user = await run_in_threadpool(auth, request)
    data = await form_data(request)
    current = str(data.get('current_password', ''))
    new = str(data.get('new_password', ''))
    confirm = str(data.get('confirm_password', ''))
    if new != confirm:
        return await run_in_threadpool(view, request, 'account_security.html', error='New passwords do not match.')
    try:
        updated_version = await run_in_threadpool(store.change_account_password, user['id'], current, new)
    except ValueError as exc:
        return await run_in_threadpool(view, request, 'account_security.html', error=str(exc))
    # Keep only this browser's session valid; other logins are now revoked.
    request.session.clear()
    request.session['user_id'] = user['id']
    request.session['auth_version'] = updated_version
    flash(request, 'Password updated. Other sessions have been signed out.', 'success')
    return redirect('/account/security')


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = auth(request)
    if user["role"] == "admin":
        return redirect("/admin")
    return redirect(f'/users/{quote(user["username"], safe="")}/manager' if user['manager_active'] else f'/users/{quote(user["username"], safe="")}')


@app.get("/my/manager", response_class=HTMLResponse)
def manager_page(request: Request):
    user=auth(request)
    if user["role"] == "admin":
        return redirect("/admin")
    return redirect(f'/users/{quote(user["username"], safe="")}/manager')


@app.get("/my/player", response_class=HTMLResponse)
def player_page(request: Request):
    user=auth(request)
    if user["role"] == "admin":
        return redirect("/admin")
    return redirect(f'/users/{quote(user["username"], safe="")}')


@app.get('/members', include_in_schema=False)
def old_member_directory():
    """Existing bookmarks go to the single public player directory."""
    return redirect('/players')


def normalize_photo(contents: bytes) -> bytes:
    """Validate and re-encode raster images; discard any embedded metadata."""
    if not contents or len(contents) > MAX_PHOTO_BYTES:
        raise ValueError('Choose an image smaller than 5 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(contents)) as img:
                if img.format not in ('JPEG', 'PNG', 'WEBP'):
                    raise ValueError('Upload a JPG, PNG or WebP image.')
                img.load()
                img = ImageOps.exif_transpose(img)
                # Consistent square avatar while maintaining aspect ratio.
                clean = ImageOps.fit(img.convert('RGB'), (512, 512), method=Image.Resampling.LANCZOS)
                out = io.BytesIO()
                clean.save(out, format='JPEG', quality=84, optimize=True)
                return out.getvalue()
    except ValueError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('Invalid image. Please upload a JPG, PNG or WebP photo.') from exc


def resolve_member(db, username):
    """Use username as the canonical identifier, retaining legacy numeric bookmarks."""
    row = db.execute("SELECT id,username FROM users WHERE username=? COLLATE NOCASE AND role!='admin'", (username,)).fetchone()
    if row:
        return row, False
    if username.isdecimal():
        row = db.execute("SELECT id,username FROM users WHERE id=? AND role!='admin'", (int(username),)).fetchone()
        if row:
            return row, True
    return None, False


@app.get('/users/{username}/photo')
def member_photo(username: str):
    """Profile images use the same canonical username URL as profiles."""
    with store.read_db() as db:
        member, legacy = resolve_member(db, username)
        if not member:
            raise HTTPException(404, 'Member not found')
        if legacy or username != member['username']:
            return RedirectResponse(f"/users/{quote(member['username'], safe='')}/photo", status_code=308)
        photo = db.execute("SELECT photo_data FROM users WHERE id=?", (member['id'],)).fetchone()
    if photo is None or photo['photo_data'] is None:
        raise HTTPException(404, 'No photo uploaded')
    return Response(content=photo['photo_data'], media_type='image/jpeg',
                    headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@app.post('/my/player/photo')
async def upload_member_photo(request: Request):
    user = await run_in_threadpool(auth, request, 'player')
    data = await form_data(request)
    uploaded = data.get('photo')
    if not isinstance(uploaded, UploadFile) or not uploaded.filename:
        flash(request, 'Choose a JPG, PNG or WebP file.', 'error')
        return redirect('/account/settings')
    try:
        contents = await uploaded.read(MAX_PHOTO_BYTES + 1)
        photo = await run_in_threadpool(normalize_photo, contents)
        await run_in_threadpool(store.save_profile_photo, user['id'], photo)
        flash(request, 'Your profile photo has been updated.', 'success')
    except ValueError as exc:
        flash(request, str(exc), 'error')
    finally:
        await uploaded.close()
    return redirect('/account/settings')


@app.post('/my/player/photo/remove')
async def remove_member_photo(request: Request):
    user = await run_in_threadpool(auth, request)
    await form_data(request)
    await run_in_threadpool(store.remove_profile_photo, user['id'])
    flash(request, 'Your profile photo was removed.', 'success')
    return redirect('/account/settings')


@app.get('/teams/{team_id}/photo')
def team_photo(team_id: int):
    with store.read_db() as db:
        photo = db.execute('SELECT photo_data FROM team_photos WHERE team_id=?', (team_id,)).fetchone()
    if not photo:
        raise HTTPException(404, 'No photo uploaded')
    return Response(content=photo['photo_data'], media_type='image/jpeg',
                    headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


def team_photo_authorization(request, team_id):
    user = auth(request, 'manager')
    with store.read_db() as db:
        try:
            store.check_team_photo_manager(db, team_id, user['id'])
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
    return user


@app.post('/teams/{team_id}/photo')
async def upload_team_photo(request: Request, team_id: int):
    user = await run_in_threadpool(team_photo_authorization, request, team_id)
    data = await form_data(request)
    uploaded = data.get('photo')
    if not isinstance(uploaded, UploadFile) or not uploaded.filename:
        flash(request, 'Choose a JPG, PNG or WebP file.', 'error')
        return redirect(f'/teams/{team_id}')
    try:
        contents = await uploaded.read(MAX_PHOTO_BYTES + 1)
        photo = await run_in_threadpool(normalize_photo, contents)
        await run_in_threadpool(store.save_team_photo, team_id, user['id'], photo)
        flash(request, 'The team profile picture has been updated.', 'success')
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        flash(request, str(exc), 'error')
    finally:
        await uploaded.close()
    return redirect(f'/teams/{team_id}')


@app.post('/teams/{team_id}/photo/remove')
async def remove_team_photo(request: Request, team_id: int):
    user = await run_in_threadpool(team_photo_authorization, request, team_id)
    await form_data(request)
    try:
        await run_in_threadpool(store.remove_team_photo, team_id, user['id'])
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    flash(request, 'The team profile picture was removed.', 'success')
    return redirect(f'/teams/{team_id}')


@app.get('/users/{username}/player', response_class=HTMLResponse)
def member_player_redirect(request: Request, username: str):
    with store.read_db() as db:
        member, _ = resolve_member(db, username)
        if member is None:
            raise HTTPException(404, 'Member not found')
    return redirect(f"/users/{quote(member['username'], safe='')}")


@app.get('/players/{player_id}', response_class=HTMLResponse)
def player_profile(request: Request, player_id: int):
    """Every player record has a stable public identity independent of its name."""
    if not 0 < player_id < 2**63:
        raise HTTPException(404, 'Player not found')
    with store.read_db() as db:
        profile = db.execute("""SELECT p.*,t.name AS team_name,u.username
            FROM players p LEFT JOIN teams t ON t.id=p.owner_team_id
            LEFT JOIN users u ON u.id=p.user_id AND u.role!='admin' WHERE p.id=?""",
            (player_id,)).fetchone()
        if profile is None:
            raise HTTPException(404, 'Player not found')
        if profile['username']:
            return RedirectResponse('/users/' + quote(profile['username'], safe=''), status_code=307)
        past_teams = db.execute("""SELECT term.*,t.name AS team_name
            FROM player_team_terms term JOIN teams t ON t.id=term.team_id
            WHERE term.player_id=? ORDER BY term.started_at DESC,term.id DESC""", (player_id,)).fetchall()
        games = game_rows(db, where='g.white_player_id=? OR g.black_player_id=?',
                          values=(player_id,player_id), limit=8)
        visible, values = public_game_visibility()
        career = player_totals(db, player_id, visible, values)
        affiliation = None
        if profile['owner_team_id']:
            term = next((row for row in past_teams if row['team_id']==profile['owner_team_id'] and not row['ended_at']), None)
            affiliation = {'role':'Player','team_id':profile['owner_team_id'],
                           'team_name':profile['team_name'],'joined_at':term['started_at'] if term else None}
    member = {'username':profile['name'],'name':profile['name'],'country':profile['country'],'fide_id':profile['fide_id'],
              'account_active':True,'player_active':True,'manager_active':False,'photo_updated_at':None}
    return view(request,'member_profile.html',member=member,profile=profile,standalone_player=True,
                owner=False,selected_tab='player',career=career,past_teams=past_teams,
                member_games=games,affiliation=affiliation,country_flag_code=country_code(profile['country']),
                **country_field(profile['country']))


@app.post('/admin/players/{player_id}/country')
async def admin_player_country(request: Request, player_id: int):
    administrator = await run_in_threadpool(auth, request, 'admin')
    data = await form_data(request)
    if not 0 < player_id < 2**63:
        raise HTTPException(404, 'Player not found')
    try:
        await run_in_threadpool(store.update_player_country,player_id,data.get('country',''),administrator['id'])
        flash(request,'Player country updated.','success')
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect(f'/players/{player_id}#player-country')


@app.post('/admin/players/{player_id}/name')
async def admin_player_name(request: Request, player_id: int):
    administrator=await run_in_threadpool(auth,request,'admin')
    data=await form_data(request)
    if not 0<player_id<2**63:
        raise HTTPException(404,'Player not found')
    try:
        await run_in_threadpool(store.update_player_name,player_id,data.get('name',''),
                               administrator['id'],data.get('original_name',''))
        flash(request,'Player name updated.','success')
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect('/admin/players#player-list')


@app.post('/admin/teams/{team_id}/name')
async def admin_team_name(request: Request, team_id: int):
    administrator=await run_in_threadpool(auth,request,'admin')
    data=await form_data(request)
    if not 0<team_id<2**63:
        raise HTTPException(404,'Team not found')
    try:
        await run_in_threadpool(store.update_team_name,team_id,data.get('name',''),
                               administrator['id'],data.get('original_name',''))
        flash(request,'Team name updated.','success')
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect('/admin/teams#teams')


@app.get('/users/{username}', response_class=HTMLResponse)
@app.get('/users/{username}/manager', response_class=HTMLResponse)
def member_profile(request: Request, username: str):
    """Public member profile with owner-only role and team actions."""
    viewer = session_user(request)
    is_manager_tab = request.url.path.endswith('/manager')
    store.settle_expired()
    with store.read_db() as db:
        found, legacy = resolve_member(db, username)
        if found is None:
            raise HTTPException(404,'Member not found')
        if legacy or username != found['username']:
            suffix = '/manager' if is_manager_tab else ''
            return RedirectResponse(f"/users/{quote(found['username'], safe='')}{suffix}", status_code=308)
        member_id=found['id']
        member=db.execute('''SELECT id,username,name,country,fide_id,account_active,role,manager_active,player_active,manager_available,photo_updated_at
            FROM users WHERE id=? AND role!='admin' ''',(member_id,)).fetchone()
        owner = bool(viewer and viewer['id']==member_id)
        profile=db.execute("""SELECT p.*,t.name AS team_name FROM players p
            LEFT JOIN teams t ON t.id=p.owner_team_id WHERE p.user_id=?""",(member_id,)).fetchone()
        history=db.execute("""SELECT h.*,t.name AS team_name FROM manager_terms h
            JOIN teams t ON t.id=h.team_id WHERE h.manager_id=? ORDER BY h.started_at DESC,h.id DESC""",
            (member_id,)).fetchall()
        team=db.execute('SELECT * FROM teams WHERE manager_id=?',(member_id,)).fetchone()
        roster = db.execute('SELECT * FROM players WHERE owner_team_id=? ORDER BY is_manager_player DESC,rating DESC,name',
                            (team['id'],)).fetchall() if team else []
        score=next((row['points'] for row in current_table(db) if row['id']==team['id']),0) if team else 0
        past_teams=db.execute('''SELECT term.*,t.name AS team_name
            FROM player_team_terms term JOIN teams t ON t.id=term.team_id
            WHERE term.player_id=? ORDER BY term.started_at DESC,term.id DESC''',
            (profile['id'],)).fetchall() if profile else []
        affiliation = None
        if is_manager_tab and member['manager_active'] and team:
            term = next((row for row in history if row['team_id']==team['id'] and not row['ended_at']), None)
            affiliation = {'role':'Captain', 'team_id':team['id'], 'team_name':team['name'],
                           'joined_at':term['started_at'] if term else None}
        elif not is_manager_tab and member['player_active'] and profile and profile['owner_team_id']:
            term = next((row for row in past_teams if row['team_id']==profile['owner_team_id'] and not row['ended_at']), None)
            affiliation = {'role':'Player', 'team_id':profile['owner_team_id'], 'team_name':profile['team_name'],
                           'joined_at':term['started_at'] if term else None}
        member_games=game_rows(db,where='g.white_player_id=? OR g.black_player_id=?',
                               values=(profile['id'],profile['id']), limit=8) if profile else []
        visible, visibility_values=public_game_visibility()
        career=player_totals(db,profile['id'],visible,visibility_values) if profile else None
        # Invitations, pending role applications, and bid positions are private.
        invitations=[]
        request_rows=[]
        bids=[]
        reserved=0
        if owner:
            invitations=db.execute("""SELECT i.*,t.name AS team_name FROM manager_invitations i
                JOIN teams t ON t.id=i.team_id WHERE i.manager_id=? AND i.status='pending' ORDER BY i.id DESC""",
                (member_id,)).fetchall()
            request_rows=db.execute("SELECT * FROM role_requests WHERE user_id=? AND status='pending' ORDER BY id DESC",(member_id,)).fetchall()
            if team:
                bids=db.execute("""
                    SELECT a.id AS auction_id, p.id AS player_id, p.name AS player_name, a.ends_at, b.amount,
                      (SELECT team_id FROM bids WHERE auction_id=a.id ORDER BY amount DESC,id ASC LIMIT 1) AS leader_id
                    FROM bids b JOIN auctions a ON a.id=b.auction_id JOIN players p ON p.id=a.player_id
                    WHERE b.team_id=? AND a.status='open' AND b.id=(
                        SELECT id FROM bids WHERE auction_id=a.id AND team_id=? ORDER BY id DESC LIMIT 1
                    ) ORDER BY a.ends_at
                """, (team['id'], team['id'])).fetchall()
                reserved=store.reserved_credits(db, team['id'])
    return view(request,'member_profile.html',member=member,owner=owner,
                selected_tab='manager' if is_manager_tab else 'player',
                profile=profile,team=team,roster=roster,score=score,bids=bids,reserved=reserved,
                available=team['budget']-reserved if team else 0,
                history=history,invitations=invitations,request_rows=request_rows,member_games=member_games,
                past_teams=past_teams,career=career,affiliation=affiliation,
                country_flag_code=country_code(member['country']))


@app.post('/my/roles/{role}/quit')
async def quit_role(request: Request,role: str):
    user=await run_in_threadpool(auth, request)
    await form_data(request)
    if role not in ('player','manager'):
        raise HTTPException(404,'Unknown role')
    try:
        await run_in_threadpool(store.quit_role, user['id'], role)
        flash(request, f'{role.capitalize()} role deactivated. Administrator approval is required to reactivate it.',
              'success', key='{role} role deactivated. Administrator approval is required to reactivate it.',
              values={'role':role.capitalize()})
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect('/my/manager' if role=='player' else '/my/player')


@app.post('/my/roles/{role}/request')
async def request_role(request: Request,role: str):
    user=await run_in_threadpool(auth, request)
    await form_data(request)
    if role not in ('player','manager'):
        raise HTTPException(404,'Unknown role')
    try:
        await run_in_threadpool(store.request_role, user['id'], role)
        flash(request, f'Your {role} role request has been sent to the administrator.', 'success',
              key='Your {role} role request has been sent to the administrator.', values={'role':role})
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect(f'/my/{role}')


@app.post('/my/manager/availability')
async def manager_availability(request: Request):
    user=await run_in_threadpool(auth, request, 'manager')
    data=await form_data(request)
    try:
        if str(data.get('available','')) not in ('0','1'):
            raise ValueError('Choose available or unavailable.')
        await run_in_threadpool(store.set_availability, user['id'], str(data['available'])=='1')
        flash(request,'Availability updated.','success')
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect('/my/manager')


@app.post('/my/manager/resign')
async def manager_resign(request: Request):
    user=await run_in_threadpool(auth, request, 'manager')
    data=await form_data(request)
    if data.get('confirmation') != 'RESIGN':
        flash(request,'Type RESIGN to confirm that you want to leave your team.','error')
        return redirect('/my/manager')
    try:
        await run_in_threadpool(store.resign_team, user['id'])
        flash(request,'You have resigned from the team. This action cannot be undone.','success')
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect('/my/manager')


@app.post('/my/manager/invitations/{invitation_id}/respond')
async def manager_respond(request: Request,invitation_id: int):
    user=await run_in_threadpool(auth, request, 'manager')
    data=await form_data(request)
    if data.get('decision') not in ('accept','decline'):
        raise HTTPException(400,'Invalid response')
    try:
        await run_in_threadpool(store.respond_invitation, user['id'], invitation_id, data.get('decision')=='accept')
        flash(request,'Invitation accepted.' if data.get('decision')=='accept' else 'Invitation declined.','success')
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect('/my/manager')


@app.post('/my/manager/players/{player_id}/kick')
async def manager_kick(request: Request,player_id: int):
    user=await run_in_threadpool(auth, request, 'manager')
    data=await form_data(request)
    if data.get('confirmation')!='KICK':
        flash(request,'Type KICK to confirm player removal.','error')
        return redirect('/my/manager')
    try:
        await run_in_threadpool(store.kick_player, user['id'], player_id)
        flash(request,'Player removed from your team. They are now a free agent. This cannot be undone.','success')
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect('/my/manager')


@app.get("/auctions", response_class=HTMLResponse)
def auctions(request: Request):
    store.settle_expired()
    with store.read_db() as db:
        current = auction_rows(db)
        completed = auction_rows(db, "closed")[:12]
        team = get_team(db, session_user(request))
        available = team['budget']-store.reserved_credits(db, team['id']) if team else 0
    return view(request, "auctions.html", auctions=current, completed=completed, team=team,available=available)


@app.get("/auctions/{auction_id}", response_class=HTMLResponse)
def auction_detail(request: Request, auction_id: int):
    store.settle_expired()
    with store.read_db() as db:
        auction = db.execute("""
            SELECT a.*, p.name AS player_name, p.club, p.rating, p.points,
              st.name AS seller_name, wt.name AS winner_name
            FROM auctions a JOIN players p ON p.id=a.player_id
            LEFT JOIN teams st ON st.id=a.seller_team_id
            LEFT JOIN teams wt ON wt.id=a.winner_team_id WHERE a.id=?
        """, (auction_id,)).fetchone()
        if auction is None:
            raise HTTPException(404, "Auction not found")
        bids = db.execute("""SELECT b.*, t.name AS team_name FROM bids b JOIN teams t ON t.id=b.team_id
             WHERE b.auction_id=? ORDER BY b.amount DESC, b.id DESC LIMIT 50""", (auction_id,)).fetchall()
        team = get_team(db, session_user(request))
        available = (team["budget"] - store.reserved_credits(db, team["id"], exclude_auction=auction_id)) if team else None
        minimum = store.minimum_bid(auction["starting_price"], bids[0]["amount"] if bids else None)
    return view(request, "auction.html", auction=auction, bids=bids, team=team, available=available, minimum=minimum)


@app.get('/api/auctions/snapshot')
def auction_snapshot(request: Request, ids: str = ''):
    """Small polling response: public bids and only the viewer's own finances."""
    if len(ids)>1200:
        raise HTTPException(400, 'Too many auctions requested.')
    parts = ids.split(',') if ids else []
    if len(parts)>100 or any(not part.isdecimal() or not 0<int(part)<2**63 for part in parts):
        raise HTTPException(400, 'Choose valid auction identifiers.')
    auction_ids = list(dict.fromkeys(int(part) for part in parts))
    user = session_user(request)
    store.settle_expired()
    with store.read_db() as db:
        # Budget, reservations and bid positions must share one read snapshot.
        db.execute('BEGIN')
        team = get_team(db, user)
        where = 'a.id IN ('+','.join('?' for _ in auction_ids)+')' if auction_ids else "a.status='open'"
        records = db.execute(f'''SELECT a.id,a.status,a.starting_price,
            (SELECT count(*) FROM bids WHERE auction_id=a.id) AS bid_count,
            (SELECT amount FROM bids WHERE auction_id=a.id ORDER BY amount DESC,id LIMIT 1) AS high_bid,
            (SELECT team_id FROM bids WHERE auction_id=a.id ORDER BY amount DESC,id LIMIT 1) AS high_bid_team_id
            FROM auctions a WHERE {where} ORDER BY a.id LIMIT 100''', auction_ids).fetchall()
        snapshots=[]
        for auction in records:
            item = dict(auction)
            item['minimum'] = store.minimum_bid(item['starting_price'], item['high_bid'])
            item['high_bid'] = item['high_bid'] or item['starting_price']
            if team:
                item['available'] = team['budget']-store.reserved_credits(db, team['id'], exclude_auction=item['id'])
                row=db.execute('SELECT max(amount) FROM bids WHERE auction_id=? AND team_id=?',
                               (item['id'],team['id'])).fetchone()
                item['my_bid'] = row[0]
            snapshots.append(item)
        available_credits = team['budget']-store.reserved_credits(db, team['id']) if team else None
    return {'auctions':snapshots,'viewer_team_id':team['id'] if team else None,
            'available_credits':available_credits}


@app.post("/auctions/{auction_id}/bid")
async def bid(request: Request, auction_id: int):
    user = await run_in_threadpool(auth, request, "manager")
    data = await form_data(request)
    team = await run_in_threadpool(team_for_member, user)
    if team is None:
        flash(request, "The administrator must assign you a team before you can bid.", "error")
        return redirect(f"/auctions/{auction_id}")
    try:
        amount_str = str(data.get("amount", ""))
        if not amount_str.isdecimal() or len(amount_str) > 8:
            raise ValueError("Enter a valid whole number of credits.")
        await run_in_threadpool(store.place_bid, auction_id, team["id"], int(amount_str), manager_id=user['id'])
        flash(request, "Bid placed successfully. Good luck!", "success")
    except ValueError as exc:
        flash(request, str(exc), "error")
    return redirect(f"/auctions/{auction_id}")


@app.get("/players", response_class=HTMLResponse)
def players(request: Request, q: str = '', team: str = 'all', status: str = 'all',
            club: str = 'all', min_rating: str | None = None, sort: str = 'rating_desc'):
    """Search, filter and sort the public player pool with SQL allowlisted ordering."""
    order_options = {
        'rating_desc': 'p.rating IS NULL, p.rating DESC, p.name COLLATE NOCASE ASC',
        'rating_asc': 'p.rating IS NULL, p.rating ASC, p.name COLLATE NOCASE ASC',
        'name_asc': 'p.name COLLATE NOCASE ASC',
        'name_desc': 'p.name COLLATE NOCASE DESC',
    }
    if sort not in order_options:
        sort = 'rating_desc'
    if status not in ('all','free','owned','market','nontransferable'):
        status = 'all'
    min_rating_value = parse_optional_int(min_rating, minimum=0, maximum=3500)
    if len(q) > 120:
        q = q[:120]
    clauses = ['(p.user_id IS NULL OR (u.account_active=1 AND u.player_active=1))']
    params = []
    if q.strip():
        clauses.append('(p.name LIKE ? OR u.username LIKE ?)')
        term = '%' + q.strip() + '%'
        params.extend([term,term])
    if team == 'free':
        clauses.append('p.owner_team_id IS NULL')
    elif team != 'all':
        if team.isdigit():
            clauses.append('p.owner_team_id=?')
            params.append(int(team))
        else:
            team='all'
    if club != 'all':
        clauses.append('p.club=?')
        params.append(club)
    if min_rating_value is not None:
        clauses.append('p.rating>=?')
        params.append(min_rating_value)
    if status == 'free':
        clauses.append('p.owner_team_id IS NULL AND p.is_manager_player=0')
    elif status == 'owned':
        clauses.append('p.owner_team_id IS NOT NULL')
    elif status == 'market':
        clauses.append("EXISTS(SELECT 1 FROM auctions a WHERE a.player_id=p.id AND a.status='open')")
    elif status == 'nontransferable':
        clauses.append('p.is_manager_player=1')
    with store.read_db() as db:
        teams = db.execute('SELECT id,name FROM teams ORDER BY name COLLATE NOCASE').fetchall()
        clubs = [r[0] for r in db.execute("SELECT DISTINCT club FROM players WHERE club!='' ORDER BY club COLLATE NOCASE")]
        rows = db.execute(f"""SELECT p.*, t.name AS owner_name, u.username, u.photo_updated_at,
            EXISTS(SELECT 1 FROM auctions a WHERE a.player_id=p.id AND a.status='open') AS listed
            FROM players p LEFT JOIN teams t ON t.id=p.owner_team_id
            LEFT JOIN users u ON u.id=p.user_id
            WHERE {' AND '.join(clauses)} ORDER BY {order_options[sort]}""",params).fetchall()
    return view(request,'players.html',players=rows,teams=teams,clubs=clubs,
                filters={'q':q,'team':team,'status':status,'club':club,
                         'min_rating':min_rating_value,'sort':sort})


@app.get('/teams', response_class=HTMLResponse)
def team_directory(request: Request, q: str = '', manager: str = 'all',
                   min_players: str | None = None, sort: str = 'name'):
    """Browsable public team directory; all filter input is parameterized."""
    order_options = {
        'name':'team_name COLLATE NOCASE ASC',
        'name_desc':'team_name COLLATE NOCASE DESC',
        'points_desc':'team_name COLLATE NOCASE ASC',
        'budget_desc':'budget DESC,team_name COLLATE NOCASE ASC',
    }
    if sort not in order_options:
        sort='name'
    if manager not in ('all','assigned','vacant'):
        manager='all'
    min_players_value = parse_optional_int(min_players, minimum=0, maximum=9999)
    q=q[:120]
    params=[]
    conditions=[]
    if q.strip():
        conditions.append('(t.name LIKE ? OR u.username LIKE ?)')
        params.extend(['%'+q.strip()+'%']*2)
    if manager == 'assigned':
        conditions.append('t.manager_id IS NOT NULL')
    elif manager == 'vacant':
        conditions.append('t.manager_id IS NULL')
    with store.read_db() as db:
        query="""SELECT t.*,photo.updated_at AS photo_updated_at,t.name AS team_name,u.username AS manager_name,
            COUNT(p.id) AS player_count
            FROM teams t LEFT JOIN team_photos photo ON photo.team_id=t.id LEFT JOIN users u ON u.id=t.manager_id
            LEFT JOIN players p ON p.owner_team_id=t.id """
        if conditions:
            query += ' WHERE '+' AND '.join(conditions)
        query += ' GROUP BY t.id'
        if min_players_value is not None:
            query += ' HAVING COUNT(p.id)>=?'
            params.append(min_players_value)
        query += ' ORDER BY '+order_options[sort]
        teams=[dict(row) for row in db.execute(query,params)]
        league_points={row['id']:row['points'] for row in current_table(db)}
        for row in teams:row['league_points']=league_points.get(row['id'],0)
        if sort=='points_desc':teams.sort(key=lambda row:row['league_points'],reverse=True)
    return view(request,'teams.html',teams=teams,
                filters={'q':q,'manager':manager,'min_players':min_players_value,'sort':sort})


@app.get('/teams/{team_id}', response_class=HTMLResponse)
def team_detail(request: Request, team_id: int, season: str | None = None):
    """Current roster plus annual membership and manager appointment archives."""
    store.settle_expired()
    year_now=store.now_utc().year
    with store.read_db() as db:
        honours=season_honours(db,team_id)
        team=db.execute("""SELECT t.*,photo.updated_at AS photo_updated_at,u.username AS manager_name
            FROM teams t LEFT JOIN team_photos photo ON photo.team_id=t.id LEFT JOIN users u ON u.id=t.manager_id WHERE t.id=?""",(team_id,)).fetchone()
        if not team:
            raise HTTPException(404,'Team not found')
        oldest_year=max(1900,min(int(team['created_at'][:4]),year_now))
        oldest=db.execute("""SELECT MIN(year) FROM (
                SELECT substr(started_at,1,4) AS year FROM player_team_terms WHERE team_id=?
                UNION ALL SELECT substr(started_at,1,4) AS year FROM manager_terms WHERE team_id=?
            )""",(team_id,team_id)).fetchone()[0]
        if oldest and oldest.isdigit():
            oldest_year=max(1900,min(oldest_year,int(oldest)))
        configured=[dict(row) for row in db.execute('SELECT * FROM seasons ORDER BY start_year DESC')]
        season_options=[{'value':f"s{row['id']}",'label':row['name']} for row in configured]
        season_options += [{'value':str(year),'label':f'{year}-{year+1}'} for year in range(year_now,oldest_year-1,-1)
                           if year not in {row['start_year'] for row in configured}]
        season=season or (season_options[0]['value'] if season_options else str(year_now))
        if str(season).isascii() and str(season).isdigit():
            matching=next((row for row in configured if row['start_year']==int(season)),None)
            if matching:
                season=f"s{matching['id']}"
        if not any(option['value']==season for option in season_options):
            raise HTTPException(404,'Season unavailable for this team')
        start,end,season_name=season_bounds(db,season)
        visible, visibility_values=public_game_visibility()
        season_scores=team_season_scores(db,team_id,start,end,
            int(season[1:]) if str(season).startswith('s') else None,visible,visibility_values)
        season_keys=[option['value'] for option in season_options]
        current_season=seasons.calendar_view(db,'current')['season']
        if current_season['id']:
            current_start,current_end,_=season_bounds(db,f"s{current_season['id']}")
        else:
            zone=ZoneInfo('Europe/Lisbon')
            current_start=store.iso(datetime(current_season['start_year'],7,1,tzinfo=zone))
            current_end=store.iso(datetime(current_season['start_year']+1,7,1,tzinfo=zone))
        current_season_scores=team_season_scores(db,team_id,current_start,current_end,
            current_season['id'],visible,visibility_values)
        current_score=next((row['points'] for row in season_table(db,current_season['id'],True) if row['id']==team_id),0)
        current=db.execute("""SELECT p.*,u.username,u.photo_updated_at FROM players p LEFT JOIN users u ON u.id=p.user_id
            WHERE p.owner_team_id=? ORDER BY CASE WHEN p.user_id=? THEN 0 ELSE 1 END,p.rating DESC,p.name COLLATE NOCASE""",
            (team_id,team['manager_id'])).fetchall()
        membership=db.execute("""SELECT r.*,p.name,p.club,p.rating,p.user_id,u.username,u.photo_updated_at,
                p.owner_team_id AS present_owner
            FROM player_team_terms r JOIN players p ON p.id=r.player_id
            LEFT JOIN users u ON u.id=p.user_id
            WHERE r.team_id=? AND r.started_at < ?
              AND (r.ended_at IS NULL OR r.ended_at > ?)
            ORDER BY r.manager_player DESC,p.name COLLATE NOCASE,r.started_at""",
            (team_id,end,start)).fetchall()
        management=db.execute("""SELECT mt.*,u.username FROM manager_terms mt
            JOIN users u ON u.id=mt.manager_id
            WHERE mt.team_id=? AND mt.started_at < ?
             AND (mt.ended_at IS NULL OR mt.ended_at > ?)
            ORDER BY mt.started_at DESC""",(team_id,end,start)).fetchall()
        team_games=game_rows(db,where='(g.white_team_id=? OR g.black_team_id=?) AND g.scheduled_at>=? AND g.scheduled_at<?',
                             values=(team_id,team_id,start,end),limit=50)
        history_complete=db.execute("SELECT 1 FROM player_team_terms WHERE team_id=? AND source IN ('imported current snapshot','legacy auction listing','legacy auction win') LIMIT 1",(team_id,)).fetchone() is None
        transfers=db.execute("""SELECT a.*,p.name AS player_name,
            seller.name AS seller_name,buyer.name AS buyer_name
            FROM auctions a JOIN players p ON p.id=a.player_id
            LEFT JOIN teams seller ON seller.id=a.seller_team_id
            LEFT JOIN teams buyer ON buyer.id=a.winner_team_id
            WHERE a.status='closed' AND a.winner_team_id IS NOT NULL
              AND (a.seller_team_id=? OR a.winner_team_id=?)
              AND a.closed_at>=? AND a.closed_at<?
            ORDER BY a.closed_at DESC,a.id DESC""",
            (team_id,team_id,start,end)).fetchall()
    return view(request,'team_detail.html',team=team,current=current,season_honours=honours,
                season=season,seasons=season_keys,season_options=season_options,season_name=season_name,membership=membership,
                management=management,transfers=transfers,team_games=team_games,history_complete=history_complete,
                current_score=current_score,current_season_scores=current_season_scores,season_scores=season_scores,season_end=end)



# --------------------------- Fixtures & chess games ---------------------------

def season_bounds(db, key):
    if str(key).startswith('s') and str(key)[1:].isascii() and str(key)[1:].isdigit():
        row=db.execute('SELECT * FROM seasons WHERE id=?',(int(str(key)[1:]),)).fetchone()
        if not row:
            raise HTTPException(400,'Invalid season.')
        zone=ZoneInfo('Europe/Lisbon')
        start=datetime.fromisoformat(row['start_date']).replace(tzinfo=zone)
        end=(datetime.fromisoformat(row['end_date'])+timedelta(days=1)).replace(tzinfo=zone)
        return store.iso(start),store.iso(end),row['name']
    if str(key).isascii() and str(key).isdigit() and 1900 <= int(key) <= 2100:
        configured=db.execute('SELECT id FROM seasons WHERE start_year=?',(int(key),)).fetchone()
        if configured:
            return season_bounds(db,f"s{configured['id']}")
        return f'{key}-01-01T00:00:00+00:00',f'{int(key)+1}-01-01T00:00:00+00:00',f'{key}-{int(key)+1}'
    raise HTTPException(400,'Invalid season.')


def public_game_visibility():
    """Pairings expose both lineups, so embargo match games until kickoff.

    Applies to every viewer, including admins, and every game surface. Standalone
    games are unaffected. Use the match's live schedule rather than game copies.
    """
    return ('''NOT EXISTS (SELECT 1 FROM match_games private_board
        JOIN team_matches private_match ON private_match.id=private_board.match_id
        WHERE private_board.game_id=g.id AND
          (julianday(private_match.scheduled_at) IS NULL OR
           julianday(private_match.scheduled_at)>julianday(?)))''', (store.iso(store.now_utc()),))


def game_rows(db, *, where='1=1', values=(), limit=200, offset=0, order='newest'):
    """Public game summary rows; where clause must be hardcoded by caller."""
    ordering = 'g.scheduled_at ASC, g.id ASC' if order == 'soonest' else 'g.scheduled_at DESC, g.id DESC'
    visible, visibility_values = public_game_visibility()
    return db.execute(f"""SELECT g.id,g.white_player_id,g.black_player_id,g.scheduled_at,
        g.event_name,g.round_label,g.result,g.recorded_at,g.white_award,g.black_award,
        g.white_team_id,g.black_team_id,g.created_at,
        (g.pgn_text IS NOT NULL AND length(g.pgn_text)>0) AS pgn_available,
        wp.name AS white_name, bp.name AS black_name,
        wp.user_id AS white_user_id, bp.user_id AS black_user_id,
        wu.username AS white_username, bu.username AS black_username,
        wt.name AS white_team_name, bt.name AS black_team_name, mg.match_id, gs.name AS season_name, gr.number AS season_round_number,
        gm.home_team_id AS match_home_team_id, gm.away_team_id AS match_away_team_id
        FROM games g JOIN players wp ON wp.id=g.white_player_id
        JOIN players bp ON bp.id=g.black_player_id
        LEFT JOIN users wu ON wu.id=wp.user_id
        LEFT JOIN users bu ON bu.id=bp.user_id
        LEFT JOIN teams wt ON wt.id=g.white_team_id
        LEFT JOIN teams bt ON bt.id=g.black_team_id
        LEFT JOIN match_games mg ON mg.game_id=g.id
        LEFT JOIN team_matches gm ON gm.id=mg.match_id
        LEFT JOIN season_rounds gr ON gr.id=gm.round_id
        LEFT JOIN seasons gs ON gs.id=gr.season_id
        WHERE ({where}) AND {visible} ORDER BY {ordering} LIMIT ? OFFSET ?
    """, (*values, *visibility_values, limit, offset)).fetchall()


@app.get('/games', response_class=HTMLResponse)
def games_directory(request: Request, q: str = '', status: str = 'all', season: str = 'all',
                    page: str = '1', sort: str = '', white_player: str = 'all', black_player: str = 'all', player: str = 'all'):
    if status not in ('all', 'scheduled', 'finished'):
        status = 'all'
    q = q[:100]
    if sort == 'upcoming':
        sort = 'soonest'
    sort = sort if sort in ('newest','soonest') else ('soonest' if status == 'scheduled' else 'newest')
    page_number = parse_optional_int(page, minimum=1, maximum=1000000) or 1
    page_size = 25
    with store.read_db() as db:
        visible, visibility_values = public_game_visibility()
        clauses, args = [visible], list(visibility_values)
        if q.strip():
            clauses.append('(wp.name LIKE ? OR bp.name LIKE ? OR g.event_name LIKE ?)')
            search = '%' + q.strip()[:100].replace('\\','\\\\').replace('%','\\%').replace('_','\\_') + '%'
            clauses[-1] = clauses[-1].replace('LIKE ?', "LIKE ? ESCAPE '\\'")
            args.extend([search] * 3)
        any_player_id = parse_optional_int(player[:20], minimum=1, maximum=9223372036854775807)
        if any_player_id is not None:
            clauses.append('(g.white_player_id=? OR g.black_player_id=?)')
            args.extend((any_player_id,any_player_id))
        white_id = parse_optional_int(white_player[:20], minimum=1, maximum=9223372036854775807)
        black_id = parse_optional_int(black_player[:20], minimum=1, maximum=9223372036854775807)
        for column, player_id in (('white_player_id', white_id), ('black_player_id', black_id)):
            if player_id is not None:
                clauses.append(f'g.{column}=?')
                args.append(player_id)
        player_options = [dict(row) for row in db.execute(f'''SELECT DISTINCT p.id,p.name FROM players p
            JOIN games g ON p.id=g.white_player_id OR p.id=g.black_player_id
            WHERE {visible} ORDER BY p.name COLLATE NOCASE,p.id''', visibility_values)]
        if status == 'scheduled':
            clauses.append("g.result='*'")
        if status == 'finished':
            clauses.append("g.result!='*'")
        if season != 'all':
            start,end,_=season_bounds(db,season)
            clauses.append('g.scheduled_at>=? AND g.scheduled_at<?')
            args.extend((start,end))
        where = ' AND '.join(clauses) if clauses else '1=1'
        total_count = db.execute(f'''SELECT count(*) FROM games g
            JOIN players wp ON wp.id=g.white_player_id JOIN players bp ON bp.id=g.black_player_id
            WHERE {where}''', args).fetchone()[0]
        total_pages = max(1, (total_count+page_size-1)//page_size)
        page_number = min(page_number, total_pages)
        rows = game_rows(db, where=where, values=tuple(args), limit=page_size,
                         offset=(page_number-1)*page_size, order=sort)
        years = [r[0] for r in db.execute(f'SELECT DISTINCT substr(g.scheduled_at,1,4) FROM games g WHERE {visible} ORDER BY 1 DESC', visibility_values)]
        configured=[dict(row) for row in db.execute('SELECT * FROM seasons ORDER BY start_year DESC')]
        season_options=[{'value':f"s{row['id']}",'label':row['name']} for row in configured]
        season_options += [{'value':year,'label':f'{year}-{int(year)+1}'} for year in years
                           if int(year) not in {row['start_year'] for row in configured}]
        finished = db.execute(f"SELECT COUNT(*) FROM games g WHERE g.result!='*' AND {visible}", visibility_values).fetchone()[0]
    filters = {'q':q,'status':status,'season':season,'sort':sort,
               'player':str(any_player_id) if any_player_id else 'all',
               'white_player':str(white_id) if white_id else 'all',
               'black_player':str(black_id) if black_id else 'all'}
    page_url = lambda number: '/games?' + urlencode({**filters, 'page':number})
    pagination_pages = []
    for number in sorted({1, total_pages, *range(max(1, page_number-1), min(total_pages, page_number+1)+1)}):
        if pagination_pages and number > pagination_pages[-1] + 1:
            pagination_pages.append(None)
        pagination_pages.append(number)
    return view(request,'games.html',games=rows,years=years,season_options=season_options, filters=filters,
                finished=finished,player_options=player_options,page=page_number,page_size=page_size,
                total_count=total_count,total_pages=total_pages,pagination_pages=pagination_pages,page_url=page_url,
                has_previous=page_number>1,has_next=page_number<total_pages,
                previous_url=page_url(page_number-1),next_url=page_url(page_number+1))


@app.get('/games/{game_id}', response_class=HTMLResponse)
def game_detail(request: Request, game_id: int):
    from game_logic import parse_pgn
    user = session_user(request)
    with store.read_db() as db:
        rows = game_rows(db, where='g.id=?', values=(game_id,), limit=1)
        if not rows:
            raise HTTPException(404, 'Game not found.')
        game = dict(rows[0])
        game['pgn_text'] = db.execute('SELECT pgn_text FROM games WHERE id=?', (game_id,)).fetchone()[0]
    replay = None
    if game['pgn_text']:
        try:
            replay = parse_pgn(game['pgn_text'])
        except ValueError:
            # Legacy manually changed PGNs should not bring down the game page.
            replay = None
    return view(request,'game_detail.html',game=game,replay=replay,
                pgn_available=bool(game['pgn_available']),is_admin=bool(user and user['role']=='admin'))


@app.get('/games/{game_id}/pgn')
def download_game_pgn(request: Request, game_id: int):
    with store.read_db() as db:
        if not game_rows(db, where='g.id=?', values=(game_id,), limit=1):
            raise HTTPException(404, 'Game not found.')
        row = db.execute('SELECT pgn_text FROM games WHERE id=?',(game_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Game not found.')
    if row['pgn_text'] is None:
        raise HTTPException(404, 'No PGN attached to this game.')
    return Response(content=row['pgn_text'],media_type='application/x-chess-pgn',
                    headers={'Content-Disposition': f'attachment; filename="game-{game_id}.pgn"',
                             'Cache-Control': 'private, no-store', 'Vary':'Cookie'})


@app.post('/admin/games')
async def admin_create_game(request: Request):
    await run_in_threadpool(auth, request, 'admin')
    data = await form_data(request)
    try:
        game_id=await run_in_threadpool(store.create_game, data.get('white_player_id'), data.get('black_player_id'), data.get('scheduled_at'), data.get('event_name',''), data.get('round_label',''))
        flash(request,'Game scheduled successfully. You can now record the result or attach its PGN.','success')
        return redirect(f'/games/{game_id}')
    except ValueError as exc:
        flash(request,str(exc),'error')
        return redirect('/games')


async def upload_pgn_field(file):
    from game_logic import MAX_PGN_BYTES
    if not isinstance(file, UploadFile) or not file.filename:
        return None
    if not file.filename.lower().endswith('.pgn'):
        raise ValueError('Choose a .pgn file.')
    raw = await file.read(MAX_PGN_BYTES + 1)
    if len(raw) > MAX_PGN_BYTES:
        raise ValueError('PGN files must be 256 KB or smaller.')
    try:
        return raw.decode('utf-8-sig')
    except UnicodeError:
        raise ValueError('PGN file must use UTF-8 text encoding.') from None


@app.post('/admin/games/{game_id}/result')
async def admin_game_result(request: Request, game_id: int):
    administrator = await run_in_threadpool(auth, request, 'admin')
    data = await form_data(request)
    try:
        pgn = await upload_pgn_field(data.get('pgn'))
        await run_in_threadpool(store.update_game_result, game_id, str(data.get('result','')), pgn, actor_id=administrator['id'], reason=str(data.get('reason','')).strip() or 'Official result recorded or corrected')
        flash(request,'Chess result saved.','success')
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect(f'/games/{game_id}')


@app.post('/admin/games/{game_id}/pgn')
async def admin_game_pgn(request: Request, game_id: int):
    administrator = await run_in_threadpool(auth, request, 'admin')
    data = await form_data(request)
    try:
        pgn = await upload_pgn_field(data.get('pgn'))
        if pgn is None:
            raise ValueError('Choose a PGN file.')
        await run_in_threadpool(store.attach_pgn, game_id, pgn, actor_id=administrator['id'], reason=str(data.get('reason','')).strip() or 'PGN uploaded by administrator')
        flash(request,'PGN attached. Any declared game result was applied automatically.','success')
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect(f'/games/{game_id}')


@app.post('/admin/games/{game_id}/pgn/remove')
async def admin_remove_game_pgn(request: Request, game_id: int):
    administrator = await run_in_threadpool(auth, request, 'admin')
    data = await form_data(request)
    try:
        await run_in_threadpool(store.remove_game_pgn, game_id, actor_id=administrator['id'], reason=str(data.get('reason','')).strip() or 'PGN removed by administrator')
        flash(request,'PGN removed. The recorded result was kept.','success')
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect(f'/games/{game_id}')


@app.get("/standings", response_class=HTMLResponse)
def standings(request: Request, season: str='current', round_number: str=Query('all',alias='round')):
    with store.read_db() as db:
        context=seasons.calendar_view(db,season)
        if context is None:
            raise HTTPException(404,'Season not found.')
        if round_number!='all' and round_number not in {str(rnd['number']) for rnd in context['schedule_rounds']}:
            raise HTTPException(400,'Invalid round.')
        rows=season_table(db,context['season']['id'],context['season']['start_year']==context['current_year'],
                          through_round=None if round_number=='all' else int(round_number))
    return view(request,'standings.html',standings=rows,round_selection=round_number,**context)


@app.get('/admin/games', include_in_schema=False)
def retired_admin_games(request: Request):
    auth(request, 'admin')
    return redirect('/games')


@app.get('/admin/teams', response_class=HTMLResponse)
@app.get('/admin/roles', response_class=HTMLResponse)
@app.get('/admin/players', response_class=HTMLResponse)
@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    auth(request, "admin")
    store.settle_expired()
    with store.read_db() as db:
        players = db.execute("""SELECT p.*, t.name AS owner_name,u.player_active,u.username,
            EXISTS(SELECT 1 FROM auctions WHERE player_id=p.id AND status='open') AS listed
            FROM players p LEFT JOIN teams t ON t.id=p.owner_team_id
            LEFT JOIN users u ON u.id=p.user_id ORDER BY p.name""").fetchall()
        teams = db.execute("""SELECT t.*,u.username
            FROM teams t LEFT JOIN users u ON u.id=t.manager_id ORDER BY t.name""").fetchall()
        managers = db.execute("""SELECT u.id,u.username,u.manager_available,t.name AS team_name,t.id AS team_id
            FROM users u LEFT JOIN teams t ON t.manager_id=u.id
            WHERE u.manager_active=1 AND u.account_active=1 AND u.role!='admin' ORDER BY u.username""").fetchall()
        player_accounts = db.execute("""SELECT u.id,u.username FROM users u
            WHERE u.player_active=1 AND u.account_active=1 AND u.role!='admin' AND NOT EXISTS (SELECT 1 FROM players p WHERE p.user_id=u.id)
            ORDER BY u.username""").fetchall()
        open_auctions = auction_rows(db)
        recovery_auctions = auction_rows(db, 'failed')
        audit_entries = db.execute('''SELECT a.*, u.username AS actor_name FROM audit_log a
            LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 50''').fetchall()
        recent_games=game_rows(db,limit=12)
        requests=db.execute("""SELECT r.*,u.username FROM role_requests r JOIN users u ON u.id=r.user_id
            WHERE r.status='pending' AND u.account_active=1 ORDER BY r.created_at,r.id""").fetchall()
        invitations=db.execute("""SELECT i.*,u.username,t.name AS team_name FROM manager_invitations i
            JOIN users u ON u.id=i.manager_id JOIN teams t ON t.id=i.team_id
            WHERE i.status='pending' ORDER BY i.id DESC""").fetchall()
        game_total=db.execute('SELECT COUNT(*) FROM games').fetchone()[0]
        season_total=db.execute('SELECT COUNT(*) FROM seasons').fetchone()[0]
        account_total=db.execute("SELECT COUNT(*) FROM users WHERE role!='admin'").fetchone()[0]
        draft_seasons=db.execute("SELECT COUNT(*) FROM seasons WHERE status='draft'").fetchone()[0]
        awaiting_results=db.execute("SELECT COUNT(*) FROM games WHERE result='*' AND scheduled_at<?",(store.iso(store.now_utc()),)).fetchone()[0]
    pending_teams={invitation['team_id'] for invitation in invitations}
    unassigned_teams=sum(team['manager_id'] is None and team['id'] not in pending_teams for team in teams)
    attention_total=len(requests)+len(player_accounts)+unassigned_teams+len(recovery_auctions)+awaiting_results+draft_seasons
    template='admin_dashboard.html' if request.url.path=='/admin' else 'admin.html'
    return view(request, template, admin_section=request.url.path.rsplit("/",1)[-1], players=players, teams=teams, managers=managers,
                player_accounts=player_accounts, auctions=open_auctions, recent_games=recent_games,
                role_requests=requests,
                invitations=invitations,recovery_auctions=recovery_auctions,audit_entries=audit_entries,
                game_total=game_total,season_total=season_total,account_total=account_total,
                draft_seasons=draft_seasons,awaiting_results=awaiting_results,unassigned_teams=unassigned_teams,attention_total=attention_total)


@app.post("/admin/teams")
async def admin_create_team(request: Request):
    await run_in_threadpool(auth, request, "admin")
    data = await form_data(request)
    try:
        await run_in_threadpool(store.create_team, str(data.get("name", "")))
        flash(request, "Team created. You can appoint a manager at any time.", "success")
    except ValueError as exc:
        flash(request, str(exc), "error")
    return redirect("/admin/teams")


@app.post("/admin/teams/{team_id}/manager")
async def admin_assign_manager(request: Request, team_id: int):
    await run_in_threadpool(auth, request, 'admin')
    data=await form_data(request)
    try:
        manager_id=int(data.get('manager_id','0'))
        await run_in_threadpool(store.invite_manager, team_id, manager_id)
        flash(request,'Manager invitation sent. The manager must accept before the team is assigned.','success')
    except (TypeError,ValueError) as exc:
        flash(request,str(exc),'error')
    return redirect('/admin/teams')


@app.post('/admin/teams/{team_id}/remove-manager')
async def admin_remove_manager(request: Request,team_id: int):
    await run_in_threadpool(auth, request, 'admin')
    data=await form_data(request)
    if data.get('confirmation')!='REMOVE':
        flash(request,'Confirm removal by typing REMOVE.','error')
        return redirect('/admin/teams')
    try:
        await run_in_threadpool(store.assign_manager, team_id, None)
        flash(request,'Manager removed; history retained.','success')
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect('/admin/teams')


@app.post('/admin/invitations/{invitation_id}/cancel')
async def admin_cancel_invitation(request: Request, invitation_id: int):
    await run_in_threadpool(auth, request, 'admin')
    await form_data(request)
    try:
        await run_in_threadpool(store.cancel_invitation, invitation_id)
        flash(request,'Pending invitation cancelled.','success')
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect('/admin/teams')


@app.post('/admin/role-requests/{request_id}/review')
async def admin_review_role(request: Request, request_id: int):
    admin=await run_in_threadpool(auth, request, 'admin')
    data=await form_data(request)
    if data.get('decision') not in ('approve','reject'):
        raise HTTPException(400,'Invalid decision')
    try:
        await run_in_threadpool(store.review_role_request, admin['id'], request_id, data.get('decision')=='approve')
        flash(request,'Role request reviewed.','success')
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect('/admin/roles#role-requests')


@app.post("/admin/players")
async def admin_add_player(request: Request):
    await run_in_threadpool(auth, request, "admin")
    data = await form_data(request)
    name = str(data.get("name", "")).strip()
    club = str(data.get("club", "")).strip()
    rating_raw = str(data.get("rating", "")).strip()
    try:
        if not 2 <= len(name) <= 80:
            raise ValueError("Player name must be 2–80 characters.")
        if len(club) > 80:
            raise ValueError("Club name is too long.")
        rating = int(rating_raw) if rating_raw else None
        if rating is not None and not 0 <= rating <= 3500:
            raise ValueError("Rating must be between 0 and 3500.")
        user_id = int(data.get("user_id")) if str(data.get("user_id", "")).strip() else None
        await run_in_threadpool(store.create_player, name, club, rating, user_id)
        flash(request, f"Activated {name} in the player pool.", "success",
              key='Activated {name} in the player pool.', values={'name':name})
    except (ValueError, OverflowError) as exc:
        flash(request, str(exc), "error")
    return redirect("/admin/players")


@app.post("/admin/auctions")
async def admin_start_auction(request: Request):
    await run_in_threadpool(auth, request, "admin")
    data = await form_data(request)
    try:
        await run_in_threadpool(store.create_auction, int(data.get("player_id", 0)), int(data.get("starting_price", 0)), int(data.get("duration_hours", 0)))
        flash(request, "Transfer auction created! Managers can now bid.", "success")
    except (ValueError, TypeError, sqlite3.IntegrityError) as exc:
        flash(request, str(exc), "error")
    return redirect("/admin/players")


@app.post("/admin/auctions/{auction_id}/close")
async def admin_close_auction(request: Request, auction_id: int):
    administrator = await run_in_threadpool(auth, request, "admin")
    data = await form_data(request)
    try:
        if not await run_in_threadpool(close_auction_safely, auction_id, administrator['id'],
                                      str(data.get('reason','')).strip() or 'Auction closed by administrator'):
            flash(request, 'Auction settlement failed. Use the recovery panel to review it.', 'error')
        else:
            flash(request, "Auction closed; winning player transferred automatically.", "success")
    except ValueError as exc:
        flash(request, str(exc), 'error')
    return redirect("/admin/players")


@app.post('/admin/auctions/{auction_id}/cancel')
async def admin_cancel_auction(request: Request, auction_id: int):
    administrator = await run_in_threadpool(auth, request, 'admin')
    data = await form_data(request)
    try:
        await run_in_threadpool(store.cancel_auction, auction_id, administrator['id'], str(data.get('reason','')).strip())
        flash(request, 'Auction cancelled. Reserved credits have been released.', 'success')
    except ValueError as exc:
        flash(request, str(exc), 'error')
    return redirect('/admin/players#auction-recovery')


@app.post('/admin/auctions/{auction_id}/retry')
async def admin_retry_auction(request: Request, auction_id: int):
    administrator = await run_in_threadpool(auth, request, 'admin')
    data = await form_data(request)
    try:
        completed = await run_in_threadpool(store.retry_auction, auction_id, administrator['id'], str(data.get('reason','')).strip())
        flash(request, 'Auction recovered and settled.' if completed else
              'Auction still needs attention. Review the failure reason.', 'success' if completed else 'error')
    except ValueError as exc:
        flash(request, str(exc), 'error')
    return redirect('/admin/players#auction-recovery')


@app.post("/admin/players/{player_id}/points")
async def admin_update_points(request: Request, player_id: int):
    administrator = await run_in_threadpool(auth, request, "admin")
    data = await form_data(request)
    try:
        adjustment = int(data.get('adjustment', ''))
        await run_in_threadpool(store.adjust_player_points, player_id, adjustment, administrator['id'], str(data.get('reason','')).strip())
        flash(request, 'Point adjustment recorded with an audit trail.', 'success')
    except (TypeError, ValueError) as exc:
        flash(request, str(exc), "error")
    return redirect("/admin/players#player-list")



@app.get('/account/settings', response_class=HTMLResponse)
def account_settings(request: Request):
    user=auth(request)
    profile=accounts.account(user['id'])
    return view(request,'account_settings.html',profile=profile,error=None,**country_field(profile['country']))


@app.post('/account/settings', response_class=HTMLResponse)
async def save_account_settings(request: Request):
    user=await run_in_threadpool(auth,request)
    data=await form_data(request)
    try:
        changed=await run_in_threadpool(accounts.update_profile,user['id'],data.get('name'),data.get('country'),data.get('fide_id'),
            email=data.get('email'),current_password=data.get('current_password'))
        if changed:
            from fide_ratings import wake_rating_worker
            wake_rating_worker()
        flash(request,'Account settings saved.','success')
        return redirect('/account/settings')
    except ValueError as exc:
        profile=await run_in_threadpool(accounts.account,user['id'])
        return await run_in_threadpool(view,request,'account_settings.html',profile=profile,error=str(exc),**country_field(profile['country']))


@app.post('/account/deactivate')
async def deactivate_account(request: Request):
    user=await run_in_threadpool(auth,request)
    data=await form_data(request)
    try:
        if data.get('confirmation')!='DEACTIVATE':
            raise ValueError('Confirm deactivation by typing DEACTIVATE.')
        await run_in_threadpool(accounts.set_account_active,user['id'],False,actor_id=user['id'],password=data.get('current_password'))
        request.session.clear()
        flash(request,'Account deactivated. Only an administrator can reactivate it.','success')
        return redirect('/login')
    except ValueError as exc:
        flash(request,str(exc),'error')
        return redirect('/account/settings')


@app.get('/forgot-password', response_class=HTMLResponse)
def forgot_password(request: Request):
    return view(request,'password_recovery.html',mode='request',sent=False,error=None,token='')


@app.post('/forgot-password', response_class=HTMLResponse)
async def request_password_recovery(request: Request, background_tasks: BackgroundTasks):
    data=await form_data(request)
    background_tasks.add_task(accounts.send_recovery,str(data.get('username','')),str(data.get('email','')))
    return await run_in_threadpool(view,request,'password_recovery.html',mode='request',sent=True,error=None,token='')


@app.get('/reset-password', response_class=HTMLResponse)
def reset_password_form(request: Request, token: str=''):
    return view(request,'password_recovery.html',mode='reset',sent=False,error=None,token=token[:100])


@app.post('/reset-password', response_class=HTMLResponse)
async def recover_password(request: Request):
    data=await form_data(request)
    token=str(data.get('token',''))
    try:
        if data.get('password')!=data.get('confirm_password'):
            raise ValueError('New passwords do not match.')
        await run_in_threadpool(accounts.reset_password,token,str(data.get('password','')))
    except ValueError as exc:
        return await run_in_threadpool(view,request,'password_recovery.html',mode='reset',sent=False,error=str(exc),token=token[:100])
    request.session.clear()
    flash(request,'Password reset. Sign in with your new password.','success')
    return redirect('/login')


@app.get('/admin/accounts', response_class=HTMLResponse)
def admin_accounts(request: Request):
    auth(request,'admin')
    with store.read_db() as db:
        members=[dict(row) for row in db.execute('SELECT id,username,name,country,fide_id,fide_id_locked,account_active,role FROM users ORDER BY username COLLATE NOCASE')]
    return view(request,'admin_accounts.html',members=members,admin_section='accounts')


@app.post('/admin/users/{user_id}/profile')
async def admin_edit_account(request: Request,user_id: int):
    actor=await run_in_threadpool(auth,request,'admin')
    data=await form_data(request)
    try:
        changed=await run_in_threadpool(accounts.update_profile,user_id,data.get('name'),data.get('country'),data.get('fide_id'),
            actor_id=actor['id'],fide_id_locked=data.get('fide_id_locked')=='1')
        if changed:
            from fide_ratings import wake_rating_worker
            wake_rating_worker()
        flash(request,'Account profile updated.','success')
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect('/admin/accounts')


@app.post('/admin/users/{user_id}/activation')
async def admin_account_activation(request: Request,user_id: int):
    actor=await run_in_threadpool(auth,request,'admin')
    data=await form_data(request)
    try:
        active=data.get('active')=='1'
        if data.get('confirmation')!='CONFIRM':
            raise ValueError('Confirm the account activation change.')
        # Admin actions use administrator authority, including self-deactivation.
        password=None
        if user_id==actor['id'] and not active:
            raise ValueError('Use account settings to deactivate your own account.')
        await run_in_threadpool(accounts.set_account_active,user_id,active,actor_id=actor['id'],password=password)
        flash(request,'Account activation updated.','success')
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect('/admin/accounts')


@app.get('/admin/seasons', response_class=HTMLResponse)
def season_setup(request: Request, season_id: int | None=None):
    auth(request,'admin')
    with store.read_db() as db:
        rows=[dict(row) for row in db.execute('SELECT * FROM seasons ORDER BY start_year DESC')]
        selected=next((row for row in rows if row['id']==season_id),rows[0] if rows else None)
        rounds=[dict(row) for row in db.execute('SELECT * FROM season_rounds WHERE season_id=? ORDER BY number',(selected['id'],))] if selected else []
        matches=seasons.match_rows(db,selected['id']) if selected else []
        teams=[dict(row) for row in db.execute('SELECT id,name FROM teams ORDER BY name')]
    return view(request,'admin_seasons.html',seasons=rows,selected=selected,rounds=rounds,matches=matches,teams=teams,admin_section='seasons')


@app.post('/admin/seasons')
@app.post('/admin/seasons/{season_id}/edit')
async def admin_save_season(request: Request,season_id: int | None=None):
    actor=await run_in_threadpool(auth,request,'admin')
    data=await form_data(request)
    try:
        season_id=await run_in_threadpool(seasons.save_season,data.get('start_year'),data.get('start_date'),data.get('end_date'),data.get('round_count'),actor['id'],season_id)
        flash(request,'Season setup saved. Review and publish the complete schedule.','success')
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect('/admin/seasons'+(f'?season_id={season_id}' if season_id else ''))


@app.post('/admin/seasons/{season_id}/publish')
async def admin_publish_season(request: Request,season_id: int):
    actor=await run_in_threadpool(auth,request,'admin')
    await form_data(request)
    try:
        await run_in_threadpool(seasons.publish_season,season_id,actor['id'])
        flash(request,'Season schedule published.','success')
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect(f'/admin/seasons?season_id={season_id}')


@app.post('/admin/seasons/{season_id}/matches')
@app.post('/admin/matches/{match_id}/edit')
async def admin_save_match(request: Request,season_id: int | None=None,match_id: int | None=None):
    actor=await run_in_threadpool(auth,request,'admin')
    data=await form_data(request)
    try:
        match_id=await run_in_threadpool(seasons.save_match,data.get('round_id'),data.get('home_team_id'),data.get('away_team_id'),data.get('scheduled_at'),data.get('location'),actor['id'],match_id)
        flash(request,'Match schedule saved.','success')
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect('/admin/seasons'+(f'?season_id={season_id}' if season_id else ''))


@app.get('/seasons', response_class=HTMLResponse)
def season_calendar(request: Request, season: str='current', round_number: str=Query('all',alias='round')):
    viewer=session_user(request)
    with store.read_db() as db:
        context=seasons.calendar_view(db,season,bool(viewer and viewer['role']=='admin'))
    if context is None:
        raise HTTPException(404,'Season not found.')
    if round_number!='all':
        if not round_number.isascii() or not round_number.isdigit() or not 1<=int(round_number)<=(context['season']['round_count'] or 0):
            raise HTTPException(400,'Invalid round.')
        context['rounds']=[rnd for rnd in context['rounds'] if rnd['number']==int(round_number)]
    return view(request,'seasons.html',round_selection=round_number,**context)


@app.get('/rounds/{round_id}', response_class=HTMLResponse)
def round_match_list(request: Request, round_id: int):
    if not 0 < round_id < 2**63:
        raise HTTPException(404,'Round not found.')
    viewer=session_user(request)
    with store.read_db() as db:
        rnd=db.execute('SELECT season_id,number FROM season_rounds WHERE id=?',(round_id,)).fetchone()
        if rnd is None:
            raise HTTPException(404,'Round not found.')
        context=seasons.calendar_view(db,str(rnd['season_id']),bool(viewer and viewer['role']=='admin'))
    selected=next((r for r in context['rounds'] if r['number']==rnd['number']),None)
    if selected is None:
        raise HTTPException(404,'Round not found.')
    return view(request,'round_detail.html',season=context['season'],round=selected)


@app.get('/matches/{match_id}', response_class=HTMLResponse)
def team_match_detail(request: Request,match_id: int):
    viewer=session_user(request)
    with store.read_db() as db:
        match=next((row for row in seasons.match_rows(db) if row['id']==match_id),None)
        if not match:
            raise HTTPException(404,'Match not found.')
        team=get_team(db,viewer) if viewer and viewer['manager_active'] else None
        player_team=db.execute('SELECT owner_team_id FROM players WHERE user_id=?',(viewer['id'],)).fetchone() if viewer and viewer['player_active'] else None
        player_team_id=player_team['owner_team_id'] if player_team else None
        if match['season_status']!='published' and not (viewer and (viewer['role']=='admin' or player_team_id in (match['home_team_id'],match['away_team_id']) or (team and team['id'] in (match['home_team_id'],match['away_team_id'])))):
            raise HTTPException(404,'Match not found.')
        own_team=team if team and team['id'] in (match['home_team_id'],match['away_team_id']) else None
        deadline_passed=seasons._datetime(match['scheduled_at'])<=store.now_utc()
        visible_team_ids={match['home_team_id'],match['away_team_id']} if deadline_passed else set()
        if own_team:
            visible_team_ids.add(own_team['id'])
        if player_team_id in (match['home_team_id'],match['away_team_id']):
            visible_team_ids.add(player_team_id)
        eligible=seasons.eligible_players(db,own_team['id']) if own_team else []
        lineups=[dict(row) for row in db.execute('''SELECT lp.*,p.name,p.rating,t.name AS team_name FROM lineup_players lp
            JOIN players p ON p.id=lp.player_id JOIN teams t ON t.id=lp.team_id
            WHERE match_id=? AND lp.team_id IN (?,?) ORDER BY team_id,board''',
            (match_id,match['home_team_id'] if match['home_team_id'] in visible_team_ids else None,
             match['away_team_id'] if match['away_team_id'] in visible_team_ids else None))]
        selected={row['board']:row['player_id'] for row in lineups if own_team and row['team_id']==own_team['id']}
        games=[dict(row) for row in db.execute('''SELECT mg.board,g.id,g.result,g.white_team_id,wp.name AS white_name,bp.name AS black_name
            FROM match_games mg JOIN games g ON g.id=mg.game_id JOIN players wp ON wp.id=g.white_player_id
            JOIN players bp ON bp.id=g.black_player_id WHERE mg.match_id=? ORDER BY board''',(match_id,))] if deadline_passed else []
    return view(request,'team_match.html',match=match,own_team=own_team,eligible=eligible,lineups=lineups,
                selected_players=selected,board_games=games,deadline_passed=deadline_passed,visible_lineup_team_ids=visible_team_ids)


@app.post('/matches/{match_id}/lineup')
async def manager_lineup(request: Request,match_id: int):
    manager=await run_in_threadpool(auth,request,'manager')
    data=await form_data(request)
    try:
        await run_in_threadpool(seasons.submit_lineup,match_id,manager['id'],[data.get(f'player_{board}') for board in range(1,5)])
        flash(request,'Four-player lineup submitted.','success')
    except ValueError as exc:
        flash(request,str(exc),'error')
    return redirect(f'/matches/{match_id}')


@app.get("/health")
def health():
    try:
        status = store.readiness()
        return {'status':'ok', **status}
    except sqlite3.DatabaseError:
        return JSONResponse({'status':'unavailable', 'detail':'Database or schema is not ready.'}, status_code=503)


@app.get('/health/live')
def liveness():
    return {'status':'alive'}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "8000")))
