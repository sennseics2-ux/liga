"""Regression tests for streaming limits, upload cleanup and browser recovery."""
import asyncio
import tempfile

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse

from web_security import (BoundedRequestBodyMiddleware, browser_http_exception_handler,
                          parse_secure_form, safe_return_path)


@pytest.mark.parametrize('headers', [[], [(b'content-length', b'4')],
                                    [(b'transfer-encoding', b'chunked')]])
def test_actual_stream_cap_before_application(headers):
    called = []
    sent = []
    pending = iter([{'type': 'http.request', 'body': b'abcde', 'more_body': True},
                    {'type': 'http.request', 'body': b'123456', 'more_body': False}])

    async def app(scope, receive, send):
        called.append(True)

    async def receive():
        return next(pending)

    async def send(message):
        sent.append(message)

    middleware = BoundedRequestBodyMiddleware(app, max_bytes=10)
    asyncio.run(middleware({'type': 'http', 'headers': headers}, receive, send))
    assert not called
    starts = [item for item in sent if item['type'] == 'http.response.start']
    assert len(starts) == 1 and starts[0]['status'] == 413


@pytest.mark.parametrize('length,status', [(b'11', 413), (b'9' * 5000, 413),
                                         (b'-1', 400), (b'invalid', 400)])
def test_declared_limit_rejects_without_receiving(length, status):
    sent = []

    async def unexpected(*args):
        pytest.fail('Rejected Content-Length must not call app or read the body')

    async def send(message):
        sent.append(message)

    asyncio.run(BoundedRequestBodyMiddleware(unexpected, 10)(
        {'type': 'http', 'headers': [(b'content-length', length)]}, unexpected, send))
    assert sent[0]['status'] == status


def make_form_app(*, allowed_files=(), max_bytes=4 * 1024 * 1024, captured=None,
                  fail_after_parse=False, allowed_fields=None):
    app = FastAPI()
    app.add_middleware(BoundedRequestBodyMiddleware, max_bytes=max_bytes)

    @app.post('/form')
    async def form(request: Request):
        data = await parse_secure_form(request, lambda _: 'correct-token',
                                       allowed_files=allowed_files, allowed_fields=allowed_fields)
        if captured is not None and 'photo' in data:
            captured.append(data['photo'])
        if fail_after_parse:
            raise RuntimeError('test handler failed')
        return PlainTextResponse('accepted')

    return app


def test_oversized_multipart_does_not_start_parser(monkeypatch):
    from starlette.formparsers import MultiPartParser

    async def unexpected_parser(self):
        pytest.fail('Oversized body must never reach multipart parsing')

    monkeypatch.setattr(MultiPartParser, 'parse', unexpected_parser)
    with TestClient(make_form_app(allowed_files=('photo',), max_bytes=1024)) as client:
        response = client.post('/form', content=iter([
            b'--boundary\r\nContent-Disposition: form-data; name="photo"; filename="x.png"\r\n\r\n',
            b'x' * 1200, b'\r\n--boundary--\r\n']),
            headers={'content-type': 'multipart/form-data; boundary=boundary'})
    assert response.status_code == 413


@pytest.mark.parametrize('fail_after_parse', [False, True])
def test_upload_spool_closed_after_success_or_handler_exception(fail_after_parse):
    captured = []
    app = make_form_app(allowed_files=('photo',), captured=captured,
                        fail_after_parse=fail_after_parse)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post('/form', data={'csrf': 'correct-token'},
                               files={'photo': ('photo.png', b'x' * (1100 * 1024), 'image/png')})
    assert response.status_code == (500 if fail_after_parse else 200)
    assert len(captured) == 1
    assert captured[0].file.closed


def test_unexpected_upload_is_closed(monkeypatch):
    opened = []
    original = tempfile.SpooledTemporaryFile

    def capture(*args, **kwargs):
        file = original(*args, **kwargs)
        opened.append(file)
        return file

    monkeypatch.setattr('starlette.formparsers.SpooledTemporaryFile', capture)
    with TestClient(make_form_app(allowed_files=('photo',))) as client:
        response = client.post('/form', data={'csrf': 'correct-token'},
                               files={'other': ('unexpected.bin', b'x' * (1100 * 1024))})
    assert response.status_code == 400
    assert opened and all(file.closed for file in opened)


def test_non_upload_routes_reject_files():
    with TestClient(make_form_app()) as client:
        response = client.post('/form', data={'csrf': 'correct-token'},
                               files={'photo': ('photo.png', b'x')})
    assert response.status_code == 400


@pytest.mark.parametrize('csrf', ['wrong', '', 'ação'])
def test_bad_csrf_is_403(csrf):
    with TestClient(make_form_app()) as client:
        response = client.post('/form', data={'csrf': csrf})
    assert response.status_code == 403


def test_duplicate_csrf_rejected():
    with TestClient(make_form_app()) as client:
        response = client.post('/form', content='csrf=wrong&csrf=correct-token',
                               headers={'content-type': 'application/x-www-form-urlencoded'})
    assert response.status_code == 403


def test_urlencoded_field_count_bounded():
    with TestClient(make_form_app()) as client:
        response = client.post('/form', data={'csrf': 'correct-token',
                                             **{f'field{i}': 'x' for i in range(32)}})
    assert response.status_code == 400


def test_declared_allowed_fields_reject_unknown_fields():
    with TestClient(make_form_app(allowed_fields=('name',))) as client:
        assert client.post('/form', data={'csrf': 'correct-token', 'name': 'Alice'}).status_code == 200
        assert client.post('/form', data={'csrf': 'correct-token', 'unknown': 'x'}).status_code == 400


@pytest.mark.parametrize('value', ['/games?page=2', '/players/Alice', '/'])
def test_safe_return_path_preserves_local_paths(value):
    assert safe_return_path(value) == value


@pytest.mark.parametrize('value', [None, '', 'https://evil.test', '//evil.test',
                                  '/\\evil.test', '/%5cevil.test', '/%2fevil.test',
                                  '/%252fevil.test', '/\x00evil', '/%00evil',
                                  '/%250aevil', 'javascript:alert(1)', '/x\r\nLocation:y',
                                  '/x' + 'a' * 2048])
def test_safe_return_path_rejects_external_or_ambiguous_paths(value):
    assert safe_return_path(value) == '/dashboard'


def recovery_app():
    app = FastAPI()
    app.add_exception_handler(HTTPException, browser_http_exception_handler())

    @app.get('/private')
    async def private():
        raise HTTPException(401, 'Log in to continue.')

    @app.post('/form')
    async def form():
        raise HTTPException(403, '<script>untrusted detail</script>')

    @app.get('/api/private')
    async def api_private():
        raise HTTPException(401, 'Log in to continue.')

    return app


def test_browser_login_redirect_preserves_filtered_page():
    with TestClient(recovery_app()) as client:
        response = client.get('/private?page=2', headers={'accept': 'text/html'},
                              follow_redirects=False)
    assert response.status_code == 303
    assert response.headers['location'] == '/login?next=%2Fprivate%3Fpage%3D2'


def test_api_auth_remains_json():
    with TestClient(recovery_app()) as client:
        response = client.get('/api/private', headers={'accept': 'text/html'})
    assert response.status_code == 401
    assert response.json() == {'detail': 'Log in to continue.'}


def test_browser_form_failure_is_html_and_escapes_detail():
    with TestClient(recovery_app()) as client:
        response = client.post('/form', headers={'accept': 'text/html',
                                               'referer': 'http://testserver/private?page=2'})
    assert response.status_code == 403
    assert response.headers['content-type'].startswith('text/html')
    assert '&lt;script&gt;' in response.text and '<script>' not in response.text
    assert 'href="/private?page=2"' in response.text


def test_browser_error_does_not_link_external_referer():
    with TestClient(recovery_app()) as client:
        response = client.post('/form', headers={'accept': 'text/html',
                                               'referer': 'https://evil.test/phishing'})
    assert 'href="/"' in response.text
    assert 'evil.test' not in response.text


@pytest.mark.parametrize('async_renderer', [False, True])
def test_error_renderer_supports_async_and_sync_callbacks(async_renderer):
    import threading
    threads = []

    def render(request, status, detail, recovery):
        threads.append(threading.current_thread().name)
        return PlainTextResponse('rendered', status_code=status)

    async def render_async(request, status, detail, recovery):
        return render(request, status, detail, recovery)

    app = recovery_app()
    app.add_exception_handler(HTTPException, browser_http_exception_handler(
        render_async if async_renderer else render))
    with TestClient(app) as client:
        response = client.post('/form', headers={'accept': 'text/html'})
    assert response.status_code == 403 and response.text == 'rendered'
    assert threads
    if not async_renderer:
        assert 'worker' in threads[0].lower()


def test_real_app_rejects_streamed_oversized_logout_before_csrf(tmp_path, monkeypatch):
    import database as store
    from deploy.security import MAX_REQUEST_BYTES
    from main import app

    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'request-limits.sqlite3')
    with TestClient(app) as client:
        response = client.post('/logout', content=iter([b'x' * (1024 * 1024)] * 8 + [b'x']),
                               headers={'content-type': 'application/x-www-form-urlencoded'})
        declared = client.post('/logout', content=b'csrf=x',
                               headers={'content-length': str(MAX_REQUEST_BYTES + 1)})
    assert response.status_code == 413
    assert declared.status_code == 413


def test_tiny_stream_chunks_are_coalesced_to_bound_object_overhead():
    received = []
    sent = []
    remaining = 20000

    async def app(scope, receive, send):
        while True:
            message = await receive()
            received.append(message['body'])
            if not message.get('more_body', False):
                break
        await PlainTextResponse('ok')(scope, receive, send)

    async def receive():
        nonlocal remaining
        remaining -= 1
        return {'type': 'http.request', 'body': b'x', 'more_body': remaining > 0}

    async def send(message):
        sent.append(message)

    asyncio.run(BoundedRequestBodyMiddleware(app, max_bytes=20000)(
        {'type': 'http', 'headers': []}, receive, send))
    assert len(received) == 1
    assert received[0] == b'x' * 20000
    assert sent[0]['status'] == 200


def test_real_app_browser_reauth_and_csrf_recovery(tmp_path, monkeypatch):
    import re
    import database as store
    from main import app

    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'browser-recovery.sqlite3')
    with TestClient(app) as client:
        private = client.get('/account/security', headers={'accept': 'text/html'}, follow_redirects=False)
        assert private.status_code == 303
        assert private.headers['location'] == '/login?next=%2Faccount%2Fsecurity'
        assert client.get('/account/security').status_code == 401
        expired = client.post('/logout', data={'csrf': 'expired'}, headers={
            'accept': 'text/html', 'referer': 'http://testserver/login'})
        assert expired.status_code == 403
        assert 'text/html' in expired.headers['content-type']
        assert 'Your form has expired.' in expired.text
        assert 'href="/login"' in expired.text

        store.create_account('web-recovery', 'ValidPassphrase123!', 'player')
        form = client.get('/login?next=/games%3Fpage%3D2')
        csrf = re.search(r'name="csrf" value="([^"]+)"', form.text).group(1)
        signed_in = client.post('/login', data={'csrf': csrf, 'username': 'web-recovery',
            'password': 'ValidPassphrase123!', 'next': '/games?page=2'}, follow_redirects=False)
        assert signed_in.status_code == 303
        assert signed_in.headers['location'] == '/games?page=2'

        client.cookies.clear()
        form = client.get('/login?next=//evil.test')
        csrf = re.search(r'name="csrf" value="([^"]+)"', form.text).group(1)
        safe = client.post('/login', data={'csrf': csrf, 'username': 'web-recovery',
            'password': 'ValidPassphrase123!', 'next': '/%252fevil.test'}, follow_redirects=False)
        assert safe.status_code == 303
        assert safe.headers['location'] == '/dashboard'


@pytest.mark.parametrize('declared', [False, True])
def test_per_endpoint_body_limit_rejects_smaller_overflow(declared):
    app = FastAPI()
    called = []
    app.add_middleware(BoundedRequestBodyMiddleware, max_bytes=1000,
                       request_limit=lambda scope: 10 if scope['path'] == '/small' else 1000)

    @app.post('/small')
    @app.post('/large')
    async def endpoint(request: Request):
        called.append(request.url.path)
        return PlainTextResponse(str(len(await request.body())))

    body = b'x' * 11 if declared else iter([b'x' * 5, b'x' * 6])
    with TestClient(app) as client:
        small = client.post('/small', content=body)
        large = client.post('/large', content=b'x' * 11)
    assert small.status_code == 413
    assert large.status_code == 200 and large.text == '11'
    assert called == ['/large']


def test_request_limit_cannot_increase_global_maximum():
    app = FastAPI()
    app.add_middleware(BoundedRequestBodyMiddleware, max_bytes=10, request_limit=lambda _: 1000)

    @app.post('/form')
    async def form():
        pytest.fail('Oversized body should not reach endpoint')

    with TestClient(app) as client:
        assert client.post('/form', content=b'x' * 11).status_code == 413


def test_lower_limit_rejects_unknown_file_before_parser(monkeypatch):
    from starlette.formparsers import MultiPartParser

    async def unexpected(self):
        pytest.fail('Unexpected large upload must be rejected before multipart parsing')

    monkeypatch.setattr(MultiPartParser, 'parse', unexpected)
    app = FastAPI()
    app.add_middleware(BoundedRequestBodyMiddleware, max_bytes=8 * 1024 * 1024,
                       request_limit=lambda _: 1024)

    @app.post('/logout')
    async def logout(request: Request):
        return await parse_secure_form(request, lambda _: 'correct-token')

    with TestClient(app) as client:
        response = client.post('/logout', data={'csrf': 'correct-token'},
                               files={'unexpected': ('large.bin', b'x' * 2048)})
    assert response.status_code == 413


def test_website_request_limits_fit_photos_and_pgn_only():
    from web_security import website_request_limit
    assert website_request_limit({'path': '/my/player/photo'}) == 6 * 1024 * 1024
    assert website_request_limit({'path': '/admin/games/123/pgn'}) == 384 * 1024
    assert website_request_limit({'path': '/admin/games/123/result'}) == 384 * 1024
    for path in ['/login', '/logout', '/unknown', '/my/player/photo/remove',
                 '/admin/games/123/pgn/remove', '/api/auctions/snapshot']:
        assert website_request_limit({'path': path}) == 64 * 1024
