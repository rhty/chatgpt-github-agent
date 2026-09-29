"""Initialize and list tools on the running loopback HTTP MCP, not a new child."""
from __future__ import annotations
import json
import urllib.request

URL = 'http://127.0.0.1:8081/mcp'
VERSION = '2025-06-18'
EXPECTED = {'system_status', 'start_task', 'publish_pr', 'get_feedback', 'reply', 'get_job', 'ci_log'}


def rpc(method, params, request_id, url=URL):
    body = json.dumps({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params}).encode()
    req = urllib.request.Request(url, data=body, headers={
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
        'MCP-Protocol-Version': VERSION,
    })
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=10) as response:
        if response.headers.get('Mcp-Session-Id'):
            raise RuntimeError('Expected stateless HTTP MCP, got a session ID')
        raw = response.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise RuntimeError('MCP smoke response exceeded limit')
        result = json.loads(raw)
    if result.get('id') != request_id or 'error' in result:
        raise RuntimeError('MCP handshake/tool-list request failed')
    return result['result']


def check(url=URL):
    rpc('initialize', {'protocolVersion': VERSION, 'capabilities': {},
        'clientInfo': {'name': 'local-http-smoke', 'version': '1'}}, 1, url)
    # Stateless HTTP starts a new transport for each request; no persistent
    # initialized session or notification is required by this server mode.
    result = rpc('tools/list', {}, 2, url)
    names = {t['name'] for t in result['tools']}
    if not EXPECTED.issubset(names):
        raise RuntimeError('Missing expected MCP tools')
    return len(names)


if __name__ == '__main__':
    print('MCP_HTTP_CHECK_OK', check(), 'tools')
