"""Bounded request parsing and safe recovery for browser authentication failures.

The body middleware verifies the whole request before handing it to multipart
parsing. Its per-request memory use is bounded by ``max_bytes``; an oversized
stream therefore cannot create upload spool files or send a partial success.
"""
from __future__ import annotations

from collections.abc import Callable, Collection
from html import escape
import inspect
import re
import secrets
from urllib.parse import parse_qsl, quote, urlsplit

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BoundedRequestBodyMiddleware:
    """Cap both declared and received bytes, including chunked HTTP requests.

    Install this as an outer middleware, before request/form parsing. Empty-body
    requests do not allocate a body buffer. Uploaded forms are closed when the
    ASGI response finishes, including when a handler raises an exception.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = 8 * 1024 * 1024,
                 request_limit: Callable[[Scope], int] | None = None):
        if max_bytes < 1:
            raise ValueError('max_bytes must be positive')
        self.app = app
        self.max_bytes = max_bytes
        self.request_limit = request_limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        limit = self.max_bytes
        if self.request_limit is not None:
            requested = self.request_limit(scope)
            if not isinstance(requested, int) or isinstance(requested, bool) or requested < 1:
                raise ValueError('request_limit must return a positive integer')
            limit = min(limit, requested)
        lengths = [value for name, value in scope.get('headers', [])
                   if name.lower() == b'content-length']
        if lengths:
            if len(lengths) != 1 or not lengths[0].isdigit():
                await PlainTextResponse('Invalid Content-Length.', status_code=400)(scope, receive, send)
                return
            # Avoid parsing an arbitrarily long integer supplied in a header.
            significant_length = lengths[0].lstrip(b'0') or b'0'
            if (len(significant_length) > len(str(limit))
                    or int(significant_length) > limit):
                await PlainTextResponse('Request too large.', status_code=413)(scope, receive, send)
                return

        chunks: list[bytes] = []
        pending = bytearray()
        total = 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            if message['type'] != 'http.request':
                continue
            chunk = message.get('body', b'')
            total += len(chunk)
            if total > limit:
                await PlainTextResponse('Request too large.', status_code=413)(scope, receive, send)
                return
            if chunk:
                # Coalesce tiny incoming chunks so Python object/list overhead
                # is bounded too; byte-at-a-time traffic must not create
                # millions of retained objects under the nominal byte cap.
                if pending:
                    pending.extend(chunk)
                    if len(pending) >= 64 * 1024:
                        chunks.append(bytes(pending))
                        pending.clear()
                elif len(chunk) >= 64 * 1024:
                    chunks.append(chunk)
                else:
                    pending.extend(chunk)
            if not message.get('more_body', False):
                break
        if pending:
            chunks.append(bytes(pending))
            pending.clear()

        index = 0

        async def bounded_receive() -> Message:
            nonlocal index
            if index < len(chunks):
                chunk = chunks[index]
                index += 1
                return {'type': 'http.request', 'body': chunk,
                        'more_body': index < len(chunks)}
            if not chunks and index == 0:
                index += 1
                return {'type': 'http.request', 'body': b'', 'more_body': False}
            return await receive()

        try:
            await self.app(scope, bounded_receive, send)
        finally:
            for form in scope.pop('_league_open_forms', []):
                await form.close()


def website_request_limit(scope: Scope) -> int:
    """Limit buffering to the upload size needed by this website endpoint.

    File contents retain their stricter validation in photo/PGN handlers. Small
    forms and unknown endpoints never allocate the global upload allowance.
    """
    path = scope.get('path', '')
    if path == '/my/player/photo':
        return 6 * 1024 * 1024
    if re.fullmatch(r'/admin/games/[0-9]+/(pgn|result)', path):
        return 384 * 1024
    return 64 * 1024


async def parse_secure_form(
        request: Request, csrf_token: Callable[[Request], str], *,
        allowed_files: Collection[str] = (), allowed_fields: Collection[str] | None = None,
        max_fields: int = 32, max_part_size: int = 1024 * 1024) -> FormData:
    """Parse a bounded form, reject unexpected files, and verify its CSRF token.

    ``allowed_files`` defaults to no uploads; photo routes explicitly allow
    ``('photo',)``. ``max_part_size`` caps individual text parts, while the body
    middleware limits file bytes before any multipart parsing. The middleware
    owns successful form cleanup; validation failures close immediately.
    """
    content_type = request.headers.get('content-type', '').split(';', 1)[0].lower().strip()
    if content_type == 'application/x-www-form-urlencoded':
        body = await request.body()
        if len(body) > max_part_size:
            raise HTTPException(413, 'Form data is too large.')
        try:
            pairs = parse_qsl(body.decode('utf-8'), keep_blank_values=True,
                              max_num_fields=max_fields)
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(400, 'Invalid form data or too many fields.') from exc
        form = FormData(pairs)
    else:
        form = await request.form(max_files=len(allowed_files), max_fields=max_fields,
                                  max_part_size=max_part_size)
    try:
        if len(form.multi_items()) > max_fields + len(allowed_files):
            raise HTTPException(400, 'Too many form fields.')
        uploaded = set()
        for name, value in form.multi_items():
            if isinstance(value, UploadFile):
                if name not in allowed_files or name in uploaded:
                    raise HTTPException(400, 'Unexpected uploaded file.')
                uploaded.add(name)
            elif allowed_fields is not None and name not in allowed_fields and name != 'csrf':
                raise HTTPException(400, 'Unexpected form field.')
        tokens = form.getlist('csrf')
        token = tokens[0] if len(tokens) == 1 and isinstance(tokens[0], str) else ''
        if not token or not secrets.compare_digest(token.encode('utf-8'), csrf_token(request).encode('utf-8')):
            raise HTTPException(403, 'Your form has expired. Refresh the page and try again.')
    except BaseException:
        await form.close()
        raise
    request.scope.setdefault('_league_open_forms', []).append(form)
    return form


def safe_return_path(value: object, default: str = '/dashboard') -> str:
    """Accept only root-relative navigation paths on this application.

    Reject protocol-relative URLs, encoded separators/control characters, and
    backslashes, which browsers and proxies may interpret as URL separators.
    Query strings are preserved so filtered pages survive re-authentication.
    """
    if not isinstance(value, str) or not value or len(value) > 2048:
        return default
    if not value.startswith('/') or value.startswith('//'):
        return default
    # Check repeated URL decoding: browsers, proxies and routers may decode at
    # different stages. A valid local path must remain local at every stage.
    from urllib.parse import unquote
    candidate = value
    for _ in range(8):
        if (not candidate.startswith('/') or candidate.startswith('//')
                or '\\' in candidate or any(ord(char) < 32 or ord(char) == 127 for char in candidate)):
            return default
        parsed = urlsplit(candidate)
        if parsed.scheme or parsed.netloc:
            return default
        decoded = unquote(candidate)
        if decoded == candidate:
            return value
        candidate = decoded
    return default


def login_redirect(request: Request) -> RedirectResponse:
    path = request.url.path
    if request.url.query:
        path += '?' + request.url.query
    return RedirectResponse('/login?next=' + quote(safe_return_path(path), safe=''), status_code=303)


def browser_request(request: Request) -> bool:
    """Keep explicit API/JSON requests machine-readable."""
    accept = request.headers.get('accept', '').lower()
    return 'text/html' in accept and not request.url.path.startswith('/api/')


def browser_http_exception_handler(render_error: Callable | None = None):
    """Create a Starlette HTTPException handler with useful browser recovery.

    Optional renderer signature: ``render_error(request, status, detail,
    recovery_url)``; it must return a response with the supplied status. Browser
    401s redirect to login with a validated local return URL. JSON clients retain
    the original HTTP status and structured ``detail`` field.
    """
    async def handler(request: Request, exc: HTTPException):
        if not browser_request(request):
            return JSONResponse({'detail': exc.detail}, status_code=exc.status_code,
                                headers=exc.headers)
        if exc.status_code == 401:
            return login_redirect(request)
        detail = str(exc.detail)
        recovery_url = '/'
        referer = request.headers.get('referer', '')
        try:
            parsed = urlsplit(referer)
            if parsed.netloc == request.url.netloc and parsed.scheme == request.url.scheme:
                recovery_url = safe_return_path(parsed.path + ('?' + parsed.query if parsed.query else ''), '/')
        except ValueError:
            pass
        if render_error is not None:
            response = await run_in_threadpool(render_error, request, exc.status_code, detail, recovery_url)
            if inspect.isawaitable(response):
                response = await response
            return response
        title = 'Refresh and try again' if exc.status_code == 403 else 'Unable to open this page'
        body = (f'<!doctype html><html lang="en"><meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{title}</title><main><h1>{title}</h1><p>{escape(detail)}</p>'
                f'<p><a href="{escape(recovery_url, quote=True)}">Return to the page</a></p></main></html>')
        return HTMLResponse(body, status_code=exc.status_code, headers=exc.headers)
    return handler
