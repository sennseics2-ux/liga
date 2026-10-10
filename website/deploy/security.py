"""Small, single-process HTTP request limits for the public deployment.

This is defense-in-depth rather than a substitute for reverse-proxy abuse protection.
Uses the verified client IP set by Uvicorn from the reverse proxy. With more than
one worker, counts would not be shared; V13 intentionally uses one worker.
"""
from collections import defaultdict, deque
from threading import Lock
from time import monotonic

_lock = Lock()
_attempts = defaultdict(deque)

# The website is currently small; fail closed for heavy request bodies before parsing.
MAX_REQUEST_BYTES = 8 * 1024 * 1024


def allowed(ip, path):
    if path == '/login':
        limit, window = 20, 10 * 60
    elif path == '/register':
        limit, window = 6, 60 * 60
    elif path == '/account/security':
        limit, window = 15, 10 * 60
    else:
        return True
    now = monotonic()
    key = (ip or 'unknown', path)
    with _lock:
        bucket = _attempts[key]
        while bucket and bucket[0] <= now - window:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        # Avoid holding entries forever on a public instance.
        if len(_attempts) > 5000:
            expired = [old_key for old_key, attempts in _attempts.items()
                       if not attempts or attempts[-1] < now - 3600]
            for old_key in expired:
                _attempts.pop(old_key, None)
            if len(_attempts) > 5000:
                oldest = sorted(_attempts, key=lambda k: _attempts[k][-1])[:1000]
                for old_key in oldest:
                    _attempts.pop(old_key, None)
        return True
