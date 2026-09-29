"""Real HTTP MCP recovery checks with the pinned SDK and a credential-free fake controller.

Run with control/requirements.txt installed. No GitHub/OpenAI calls are made.
The extra delayed tool exists only in the test subprocess, not in production.
"""
from __future__ import annotations
import concurrent.futures
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
HAS_MCP = importlib.util.find_spec('mcp') is not None

SERVER = r'''
import sys, types, asyncio
sys.path.insert(0, sys.argv[1])
fake = types.ModuleType('app')
class Controller:
    def system_status(self):
        return {'worker': {'ok': True}, 'transport_test': True}
fake.create_controller = Controller
sys.modules['app'] = fake
from mcp_http_server import mcp
mcp.settings.port = int(sys.argv[2])
@mcp.tool()
async def transport_test_delay(label: str, seconds: float = 0) -> dict:
    await asyncio.sleep(seconds)
    return {'label': label}
mcp.run(transport='streamable-http')
'''


@unittest.skipUnless(HAS_MCP, 'install control/requirements.txt for real HTTP MCP tests')
class HTTPRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import httpx
        cls.httpx = httpx
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        log = open(Path(cls.temp.name)/'server.log', 'w+')
        cls.addClassCleanup(log.close)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        cls.url = f'http://127.0.0.1:{port}'
        cls.server = subprocess.Popen([sys.executable, '-c', SERVER, str(ROOT/'control'), str(port)],
                                      stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        cls.addClassCleanup(cls.stop_server)
        for _ in range(150):
            if cls.server.poll() is not None:
                log.seek(0)
                raise AssertionError('Test MCP failed to start:\n'+log.read())
            try:
                with urllib.request.urlopen(cls.url+'/livez', timeout=0.2) as r:
                    if r.read() == b'github-agent-mcp-live':
                        return
            except OSError:
                pass
            time.sleep(0.1)
        raise AssertionError('Test MCP startup timed out')

    @classmethod
    def stop_server(cls):
        if cls.server.poll() is None:
            cls.server.terminate()
            try:
                cls.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.server.kill()
                cls.server.wait()

    def rpc(self, method, params=None, request_id=1, timeout=5, headers=None):
        with self.httpx.Client(timeout=timeout, trust_env=False) as client:
            return client.post(self.url+'/mcp', json={
                'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params or {},
            }, headers={'Content-Type': 'application/json',
                        'Accept': 'application/json, text/event-stream',
                        'MCP-Protocol-Version': '2025-06-18', **(headers or {})})

    def tool_result(self, response):
        response.raise_for_status()
        result = response.json()['result']
        self.assertFalse(result.get('isError', False), result)
        if 'structuredContent' in result:
            return result['structuredContent']
        return json.loads(''.join(item['text'] for item in result['content'] if item['type'] == 'text'))

    def test_live_smoke_initializes_and_lists_actual_tools(self):
        spec = importlib.util.spec_from_file_location('live_smoke', ROOT/'control/http_smoke_test.py')
        smoke = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(smoke)
        self.assertGreaterEqual(smoke.check(self.url+'/mcp'), 16)

    def test_caller_timeout_does_not_kill_server_or_poison_next_call(self):
        with self.assertRaises(self.httpx.ReadTimeout):
            self.rpc('tools/call', {'name': 'transport_test_delay',
                'arguments': {'label': 'old', 'seconds': 1}}, timeout=0.05)
        self.assertIsNone(self.server.poll())
        # Reuse the ID from the disconnected request, as a different ChatGPT call might.
        response = self.rpc('tools/call', {'name': 'transport_test_delay',
            'arguments': {'label': 'new'}})
        response.raise_for_status()
        self.assertEqual(self.tool_result(response), {'label': 'new'})
        self.assertIsNone(response.headers.get('mcp-session-id'))
        time.sleep(1.1)
        self.assertIsNone(self.server.poll())
        status = self.rpc('tools/call', {'name': 'system_status', 'arguments': {}})
        status.raise_for_status()
        self.assertTrue(self.tool_result(status)['worker']['ok'])

    def test_independent_clients_reusing_rpc_id_get_their_own_responses(self):
        def call(label):
            r = self.rpc('tools/call', {'name': 'transport_test_delay',
                'arguments': {'label': label, 'seconds': 0.05}})
            r.raise_for_status()
            return self.tool_result(r)['label']
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(call, ['one', 'two'])), ['one', 'two'])

    def test_dns_rebinding_host_rejected(self):
        r = self.rpc('tools/list', headers={'Host': 'untrusted.invalid'})
        self.assertEqual(r.status_code, 421)
