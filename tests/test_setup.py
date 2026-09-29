"""Regression tests for explicit project/repository selection and setup isolation."""
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
        self.env.pop('COMPOSE_PROJECT_NAME', None)

    def run_configure(self, text, args=('--project-name', 'test-agent'), root=None):
        return subprocess.run(
            ['bash', str((root or self.root) / 'scripts/configure.sh'), *args], input=text,
            text=True, capture_output=True, env=self.env, timeout=10,
        )

    def valid_input(self, repositories='example-owner/test-repo', token='test-only-token'):
        key = self.root / 'test.pem'
        key.write_text('test-only fixture; openssl is mocked\n')
        tunnel = 'tunnel_' + '0' * 32
        return f'123456\n{repositories}\n{tunnel}\n{key}\n{token}\n'

    def assert_not_configured(self):
        self.assertFalse((self.root / '.env').exists())
        self.assertFalse((self.root / 'secrets').exists())

    def test_project_name_flag_is_saved(self):
        result = self.run_configure(self.valid_input(), args=('--project-name', 'team-b-agent'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('COMPOSE_PROJECT_NAME=team-b-agent\n', (self.root / '.env').read_text())
        self.assertIn('COMPOSE_PROJECT_NAME=team-b-agent', result.stdout)

    def test_project_name_equals_flag_is_saved(self):
        result = self.run_configure(self.valid_input(), args=('--project-name=team_b-2',))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('COMPOSE_PROJECT_NAME=team_b-2\n', (self.root / '.env').read_text())

    def test_interactive_project_name_is_saved(self):
        result = self.run_configure('team-b-agent\n' + self.valid_input(), args=())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('COMPOSE_PROJECT_NAME=team-b-agent\n', (self.root / '.env').read_text())

    def test_empty_interactive_project_name_has_no_silent_default(self):
        result = self.run_configure('\n', args=())
        self.assertNotEqual(result.returncode, 0)
        self.assert_not_configured()

    def test_invalid_project_names_are_rejected_before_secret_writes(self):
        for name in ('', 'Team-B', '-team', '_team', 'team.b', 'team b', '../team',
                     'team\nGITHUB_APP_ID=9', '$(touch marker)', 'équipe'):
            with self.subTest(name=name):
                result = self.run_configure('', args=('--project-name', name))
                self.assertNotEqual(result.returncode, 0)
                self.assert_not_configured()

    def test_invalid_arguments_are_rejected(self):
        for args in (('--project-name',), ('--unknown',), ('extra',),
                     ('--project-name', 'one', '--project-name=two')):
            with self.subTest(args=args):
                result = self.run_configure('', args=args)
                self.assertNotEqual(result.returncode, 0)
                self.assert_not_configured()

    def test_help_needs_no_keys_or_configuration(self):
        result = self.run_configure('', args=('--help',))
        self.assertEqual(result.returncode, 0)
        self.assertIn('--project-name', result.stdout)
        self.assert_not_configured()

    def test_conflicting_exported_project_name_is_rejected(self):
        self.env['COMPOSE_PROJECT_NAME'] = 'other-agent'
        result = self.run_configure(self.valid_input())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unset COMPOSE_PROJECT_NAME', result.stdout)
        self.assert_not_configured()

    def test_multiple_repositories_are_saved(self):
        repositories = 'example-owner/core,example-owner/console,example-owner/kiban'
        result = self.run_configure(self.valid_input(repositories))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'ALLOWED_REPOS={repositories}\n', (self.root / '.env').read_text())

    def test_invalid_repository_lists_are_rejected(self):
        for value in ('owner/core,', ',owner/core', 'owner/core,,owner/console',
                      'owner/core, owner/console', 'owner/core,invalid', 'owner/*'):
            with self.subTest(value=value):
                result = self.run_configure(f'123456\n{value}\n')
                self.assertNotEqual(result.returncode, 0)
                self.assert_not_configured()

    def test_existing_credentials_are_not_overwritten_without_env(self):
        secrets = self.root / 'secrets'
        secrets.mkdir()
        key = secrets / 'github-app.pem'
        key.write_text('existing-key')
        token = secrets / 'tunnel-api-key'
        token.write_text('existing-token')
        result = self.run_configure(self.valid_input())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(key.read_text(), 'existing-key')
        self.assertEqual(token.read_text(), 'existing-token')
        self.assertFalse((self.root / '.env').exists())
        self.assertNotIn('existing-key', result.stdout + result.stderr)
        self.assertNotIn('existing-token', result.stdout + result.stderr)

    def test_dangling_env_symlink_is_not_replaced(self):
        target = self.root / 'missing-config'
        (self.root / '.env').symlink_to(target)
        result = self.run_configure(self.valid_input())
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.root / '.env').is_symlink())
        self.assertFalse(target.exists())
        self.assertFalse((self.root / 'secrets').exists())

    def test_secrets_symlink_is_not_followed(self):
        target = self.root / 'other-secrets'
        target.mkdir()
        (self.root / 'secrets').symlink_to(target, target_is_directory=True)
        result = self.run_configure(self.valid_input())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(target.iterdir()), [])
        self.assertFalse((self.root / '.env').exists())

    def test_saved_configuration_and_keys_are_private(self):
        result = self.run_configure(self.valid_input())
        self.assertEqual(result.returncode, 0, result.stderr)
        for path in ('.env', 'secrets/github-app.pem', 'secrets/tunnel-api-key'):
            self.assertEqual((self.root / path).stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / 'secrets').stat().st_mode & 0o777, 0o700)

    def test_separate_roots_keep_distinct_configurations_and_keys(self):
        text = self.valid_input(token='token-a')
        result = self.run_configure(text, args=('--project-name', 'team-a-agent'))
        self.assertEqual(result.returncode, 0, result.stderr)
        before = {name: (self.root / name).read_bytes()
                  for name in ('.env', 'secrets/github-app.pem', 'secrets/tunnel-api-key')}
        other = self.root / 'other-clone'
        (other / 'scripts').mkdir(parents=True)
        shutil.copy2(self.root / 'scripts/configure.sh', other / 'scripts/configure.sh')
        second_key = self.root / 'second.pem'
        second_key.write_text('separate test key')
        tunnel = 'tunnel_' + '1' * 32
        result = self.run_configure(f'987654\nother-owner/core\n{tunnel}\n{second_key}\ntoken-b\n',
                                    args=('--project-name', 'team-b-agent'), root=other)
        self.assertEqual(result.returncode, 0, result.stderr)
        for name, content in before.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        config = (other / '.env').read_text()
        self.assertIn('COMPOSE_PROJECT_NAME=team-b-agent\n', config)
        self.assertIn('GITHUB_APP_ID=987654\n', config)
        self.assertIn('ALLOWED_REPOS=other-owner/core\n', config)
        self.assertIn(f'CONTROL_PLANE_TUNNEL_ID={tunnel}\n', config)
        self.assertEqual((other / 'secrets/github-app.pem').read_text(), 'separate test key')
        self.assertEqual((other / 'secrets/tunnel-api-key').read_text(), 'token-b')

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
