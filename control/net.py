"""Bounded HTTP, no credential forwarding across redirects."""
from __future__ import annotations
import json
import urllib.request
import urllib.error
from urllib.parse import urlsplit

class APIError(RuntimeError):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(f"HTTP {status}: {message[:400]}")

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(method, url, *, headers=None, body=None, limit=24*1024*1024, timeout=60, binary=False, _redirects=0):
    data = None if body is None else json.dumps(body).encode()
    hdr = dict(headers or {})
    if data is not None:
        hdr['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=hdr, method=method)
    # Explicitly disable ambient HTTP proxy environment configuration.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as res:
            content = res.read(limit + 1)
            if len(content) > limit:
                raise ValueError('Response exceeds configured size limit')
            return content if binary else (json.loads(content) if content else {})
    except urllib.error.HTTPError as exc:
        if binary and exc.code in (301, 302, 303, 307, 308):
            if _redirects >= 5:
                raise ValueError('Too many download redirects') from None
            location = exc.headers.get('Location', '')
            parsed = urlsplit(location)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('Unsafe download redirect') from None
            # New request deliberately has NO Authorization header.
            return request('GET', location, limit=limit, timeout=timeout, binary=True, _redirects=_redirects+1)
        raw = exc.read(4096)
        try:
            msg = json.loads(raw).get('message', 'Request failed')
        except (ValueError, AttributeError):
            msg = 'Request failed'
        raise APIError(exc.code, str(msg)) from None
    except urllib.error.URLError:
        raise RuntimeError('Network request failed; check service connectivity') from None
