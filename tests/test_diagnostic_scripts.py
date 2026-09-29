"""Run the shell scripts with Docker mocked; no daemon or credentials required."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DiagnosticScriptTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        scripts = self.root / 'scripts'
        scripts.mkdir()
        for name in ('doctor.sh', 'start.sh'):
            shutil.copy2(ROOT / 'scripts' / name, scripts / name)
        (self.root / '.env').write_text('# Test fixture: no secrets.\n')
        self.log = self.root / 'docker-calls.log'
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        docker = bin_dir / 'docker'
        docker.write_text(r'''#!/bin/sh
printf '%s\037' "$@" >> "$FAKE_DOCKER_LOG"
printf '\036' >> "$FAKE_DOCKER_LOG"
if [ "$*" = info ]; then
    [ "$FAKE_DOCKER_INFO_OK" = 1 ]
    exit $?
fi
case " $* " in
    *" /usr/bin/tunnel-client doctor "*)
        case " $* " in
            *" --health.listen-addr=127.0.0.1:0 "*)
                echo 'CHECK health_listener PASS ephemeral bind ok'
                exit 0 ;;
            *)
                echo 'CHECK health_listener FAIL address already in use'
                exit 2 ;;
        esac ;;
    *'/readyz'*)
        if [ "$FAKE_CONTROL_READY" != 1 ]; then
            echo LIVE_READINESS_FAILED >&2
            exit 1
        fi
        echo ready ;;
esac
exit 0
''')
        docker.chmod(0o755)
        sleep = bin_dir / 'sleep'
        sleep.write_text('#!/bin/sh\nexit 0\n')
        sleep.chmod(0o755)
        self.env = {
            **os.environ,
            'PATH': str(bin_dir) + os.pathsep + os.environ.get('PATH', ''),
            'FAKE_DOCKER_LOG': str(self.log),
            'FAKE_DOCKER_INFO_OK': '1',
            'FAKE_CONTROL_READY': '1',
        }

    def run_script(self, name, **env):
        return subprocess.run(
            ['bash', str(self.root / 'scripts' / name)],
            capture_output=True, text=True, timeout=20,
            env={**self.env, **env},
        )

    def calls(self):
        return [record.rstrip('\x1f').split('\x1f')
                for record in self.log.read_text().split('\x1e') if record]

    def preflights(self):
        return [args for args in self.calls()
                if '/usr/bin/tunnel-client' in args and 'doctor' in args]

    def test_doctor_uses_ephemeral_port_without_changing_live_daemon(self):
        result = self.run_script('doctor.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ephemeral bind ok', result.stdout)
        self.assertNotIn('address already in use', result.stdout)
        self.assertEqual(len(self.preflights()), 1)
        self.assertIn('--health.listen-addr=127.0.0.1:0', self.preflights()[0])
        self.assertIn('--control-plane.api-key=file:/run/secrets/tunnel_api_key',
                      self.preflights()[0])
        self.assertTrue(any('http://127.0.0.1:8080/readyz' in arg
                            for args in self.calls() for arg in args))
        for args in self.calls():
            self.assertFalse(set(args) & {'stop', 'restart', 'down', 'up', 'build'})

    def test_live_readiness_failure_remains_visible(self):
        result = self.run_script('doctor.sh', FAKE_CONTROL_READY='0')
        self.assertIn('LIVE_READINESS_FAILED', result.stderr)
        self.assertIn('ephemeral bind ok', result.stdout)
        self.assertIn('separate from live readiness', result.stdout)
        self.assertNotIn('AGENT_READY', result.stdout)

    def test_start_failure_diagnostic_does_not_mask_readiness_failure(self):
        result = self.run_script('start.sh', FAKE_CONTROL_READY='0')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('ephemeral bind ok', result.stdout)
        self.assertNotIn('AGENT_READY', result.stdout)
        self.assertEqual(len(self.preflights()), 1)
        self.assertIn('--health.listen-addr=127.0.0.1:0', self.preflights()[0])

    def test_successful_start_does_not_run_failure_diagnostic(self):
        result = self.run_script('start.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('AGENT_READY', result.stdout)
        self.assertEqual(self.preflights(), [])

    def test_unavailable_docker_stops_diagnostic(self):
        result = self.run_script('doctor.sh', FAKE_DOCKER_INFO_OK='0')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.calls(), [['info']])


if __name__ == '__main__':
    unittest.main()
