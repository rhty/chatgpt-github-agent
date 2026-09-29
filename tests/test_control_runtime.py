"""Control supervisor tests; no Docker, keys, or external services needed."""
import importlib.util
from pathlib import Path
import subprocess
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('agent_runtime_test', ROOT/'control/runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class RuntimeTests(unittest.TestCase):
    def test_transport_is_loopback_and_legacy_command_removed(self):
        env = runtime.child_environment({'MCP_COMMAND': 'legacy', 'KEEP': 'yes'})
        self.assertNotIn('MCP_COMMAND', env)
        self.assertEqual(env['MCP_SERVER_URL'], 'http://127.0.0.1:8081/mcp')
        self.assertEqual(env['KEEP'], 'yes')

    def test_failed_http_start_never_starts_tunnel(self):
        server = Mock()
        server.poll.return_value = 1
        with patch.object(runtime.subprocess, 'Popen', return_value=server) as spawn:
            self.assertEqual(runtime.run([], threading.Event()), 1)
        self.assertEqual(spawn.call_count, 1)

    def test_shutdown_during_http_start_never_starts_tunnel(self):
        event = threading.Event()
        event.set()
        server = Mock()
        server.poll.return_value = None
        with patch.object(runtime.subprocess, 'Popen', return_value=server) as spawn:
            self.assertEqual(runtime.run([], event), 0)
        self.assertEqual(spawn.call_count, 1)
        server.terminate.assert_called_once()

    def test_tunnel_exit_stops_http_and_returns_failure(self):
        server, tunnel = Mock(), Mock()
        server.poll.return_value = None
        tunnel.poll.return_value = 0
        with patch.object(runtime.subprocess, 'Popen', side_effect=[server, tunnel]), \
             patch.object(runtime, 'wait_for_mcp'):
            self.assertEqual(runtime.run(['--log.level=info'], threading.Event()), 1)
        server.terminate.assert_called_once()

    def test_http_exit_stops_tunnel_and_returns_failure(self):
        server, tunnel = Mock(), Mock()
        server.poll.return_value = 1
        tunnel.poll.return_value = None
        with patch.object(runtime.subprocess, 'Popen', side_effect=[server, tunnel]), \
             patch.object(runtime, 'wait_for_mcp'):
            self.assertEqual(runtime.run([], threading.Event()), 1)
        tunnel.terminate.assert_called_once()

    def test_stuck_child_is_killed_after_grace(self):
        child = Mock()
        child.poll.return_value = None
        child.wait.side_effect = [subprocess.TimeoutExpired('child', 5), 0]
        runtime.stop_children([child])
        child.terminate.assert_called_once()
        child.kill.assert_called_once()

    def test_startup_timeout_is_reported_without_starting_tunnel(self):
        server = Mock()
        server.poll.return_value = None
        with patch.object(runtime, 'live', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'startup timed out'):
                runtime.wait_for_mcp(server, threading.Event(), timeout=0)

    def test_healthy_http_child_allows_start(self):
        server = Mock()
        server.poll.return_value = None
        with patch.object(runtime, 'live', return_value=True):
            runtime.wait_for_mcp(server, threading.Event(), timeout=1)

    def test_docker_entrypoint_does_not_use_shared_stdio(self):
        dockerfile = (ROOT/'control/Dockerfile').read_text()
        self.assertIn('"/opt/control/runtime.py"', dockerfile)
        self.assertIn('MCP_SERVER_URL="http://127.0.0.1:8081/mcp"', dockerfile)
        self.assertNotIn('MCP_COMMAND=', dockerfile)
        self.assertNotIn('stdio-send-initialized-notification', dockerfile)

    def test_live_http_handshake_precedes_ready_message(self):
        script = (ROOT/'scripts/start.sh').read_text()
        self.assertLess(script.index('/opt/control/http_smoke_test.py'), script.index('AGENT_READY'))
