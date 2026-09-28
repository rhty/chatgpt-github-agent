"""Bounded HTTP, no credential forwarding across redirects."""
from __future__ import annotations
import json
from http.client import IncompleteRead
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


def request(method, url, *, headers=None, body=None, limit=24*1024*1024, timeout=60,
            binary=False, sink=None, label='HTTP response', _redirects=0):
    """Return a bounded response, or copy binary data to sink in bounded chunks.

    Labels must not contain signed URLs or credentials; they are shown to the user.
    """
    if sink is not None and not binary:
        raise ValueError('Streaming is only supported for binary responses')
    data = None if body is None else json.dumps(body).encode()
    hdr = dict(headers or {})
    if data is not None:
        hdr['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=hdr, method=method)
    # Explicitly disable ambient HTTP proxy environment configuration.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as res:
            declared = res.headers.get('Content-Length')
            expected = int(declared) if declared is not None else None
            if expected is not None and (expected < 0 or expected > limit):
                raise ValueError(f'{label}: response size {expected} bytes exceeds limit {limit} bytes')
            if sink is None:
                content = res.read(limit + 1)
                if len(content) > limit:
                    raise ValueError(f'{label}: received more than {limit} bytes')
                if expected is not None and len(content) != expected:
                    raise RuntimeError(f'{label}: truncated response')
                return content if binary else (json.loads(content) if content else {})
            total = 0
            while True:
                chunk = res.read(min(256*1024, limit-total+1))
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ValueError(f'{label}: received at least {total} bytes; limit {limit} bytes')
                sink.write(chunk)
            if expected is not None and total != expected:
                raise RuntimeError(f'{label}: truncated response ({total}/{expected} bytes)')
            return total
    except urllib.error.HTTPError as exc:
        if binary and exc.code in (301, 302, 303, 307, 308):
            if _redirects >= 5:
                raise ValueError('Too many download redirects') from None
            location = exc.headers.get('Location', '')
            parsed = urlsplit(location)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('Unsafe download redirect') from None
            # New request deliberately has NO Authorization header.
            exc.close()
            return request('GET', location, limit=limit, timeout=timeout, binary=True,
                           sink=sink, label=label, _redirects=_redirects+1)
        raw = exc.read(4096)
        try:
            msg = json.loads(raw).get('message', 'Request failed')
        except (ValueError, AttributeError):
            msg = 'Request failed'
        raise APIError(exc.code, str(msg)) from None
    except (IncompleteRead, TimeoutError):
        raise RuntimeError(f'{label}: download interrupted; retry the same task_id') from None
    except urllib.error.URLError:
        raise RuntimeError('Network request failed; check service connectivity') from None
