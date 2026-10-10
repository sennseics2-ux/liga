"""Docker internal health check uses the production-approved Host header."""
import os
import urllib.request

host = os.getenv('CHESS_ALLOWED_HOSTS', 'localhost').split(',')[0].strip()
request = urllib.request.Request('http://127.0.0.1:8000/health', headers={'Host': host})
try:
    with urllib.request.urlopen(request, timeout=5) as response:
        if response.status != 200:
            raise SystemExit(1)
except Exception:
    raise SystemExit(1)
