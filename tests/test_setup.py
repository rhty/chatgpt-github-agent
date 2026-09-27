"""Regression tests for explicit repository selection during setup."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ConfigureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'scripts').mkdir()
        shutil.copy2(ROOT / 'scripts/configure.sh', self.root / 'scripts/configure.sh')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        # Avoid the macOS file dialog; these tests do not validate real keys.
        for name, script in [('uname', '#!/bin/sh\nprintf "Linux\\n"\n'),
                             ('openssl', '#!/bin/sh\nexit 0\n')]:
            target = self.bin / name
            target.write_text(script)
            target.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(self.bin) + os.pathsep + os.environ['PATH']}

    def run_configure(self, text):
        return subprocess.run(
            ['bash', str(self.root / 'scripts/configure.sh')], input=text,
            text=True, capture_output=True, env=self.env, timeout=10,
        )

    def test_empty_repository_does_not_select_a_default(self):
        result = self.run_configure('123456\n\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / '.env').exists())
        self.assertFalse((self.root / 'secrets').exists())

    def test_invalid_repository_is_rejected(self):
        result = self.run_configure('123456\nnot-a-repository\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / '.env').exists())

    def test_explicit_repository_is_saved(self):
        key = self.root / 'test.pem'
        key.write_text('test-only fixture; openssl is mocked\n')
        tunnel = 'tunnel_' + '0' * 32
        result = self.run_configure(f'123456\nexample-owner/test-repo\n{tunnel}\n{key}\ntest-only-token\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('CONFIG_SAVED', result.stdout)
        self.assertIn('ALLOWED_REPOS=example-owner/test-repo\n', (self.root / '.env').read_text())
        self.assertEqual((self.root / 'secrets/tunnel-api-key').read_text(), 'test-only-token')
        self.assertNotIn('test-only-token', result.stdout + result.stderr)

    def test_existing_configuration_is_not_overwritten(self):
        config = self.root / '.env'
        config.write_text('ALLOWED_REPOS=existing/repository\n')
        result = self.run_configure('')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(config.read_text(), 'ALLOWED_REPOS=existing/repository\n')


if __name__ == '__main__':
    unittest.main()
