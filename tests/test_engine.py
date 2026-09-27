from __future__ import annotations

import json
import shlex
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from engine import JobManager, Workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ws = Workspace(self.root / "workspace")

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_read_and_hash_guard(self):
        first = self.ws.write_file("repo/a.txt", "hello\nworld\n")
        self.assertEqual(self.ws.read_file("repo/a.txt")["sha256"], first["sha256"])
        with self.assertRaises(ValueError):
            self.ws.write_file("repo/a.txt", "oops")
        second = self.ws.write_file("repo/a.txt", "changed", first["sha256"])
        self.assertNotEqual(first["sha256"], second["sha256"])
        with self.assertRaises(ValueError):
            self.ws.write_file("repo/a.txt", "stale", first["sha256"])

    def test_traversal_and_symlink_rejected(self):
        with self.assertRaises(ValueError):
            self.ws.write_file("../outside.txt", "bad")
        outside = self.root / "secret.txt"
        outside.write_text("secret")
        (self.ws.root / "link").symlink_to(outside)
        with self.assertRaises(ValueError):
            self.ws.read_file("link")
        with self.assertRaises(ValueError):
            self.ws.write_file("link", "bad")
        self.assertEqual(outside.read_text(), "secret")

    def test_lines_and_directory_limit(self):
        self.ws.write_file("repo/a.txt", "a\nb\nc\n")
        self.ws.write_file("repo/b.txt", "b")
        got = self.ws.read_file("repo/a.txt", 2, 1)
        self.assertEqual(got["content"], "b\n")
        self.assertTrue(got["truncated"])
        self.assertEqual(self.ws.list_files("repo", 1)["total"], 2)

    def test_missing_hash_and_binary(self):
        with self.assertRaises(ValueError):
            self.ws.write_file("missing", "x", "bad")
        self.ws.write_file("binary", "a\x00b")
        with self.assertRaises(ValueError):
            self.ws.read_file("binary")


class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ws = Workspace(self.root / "workspace")
        (self.ws.root / "repo").mkdir()
        self.state = self.root / "state"
        self.manager = JobManager(self.ws, self.state, max_jobs=2, max_log_bytes=1024)

    def tearDown(self):
        self.manager.close()
        self.tmp.cleanup()

    @staticmethod
    def command(code):
        return shlex.quote(sys.executable) + " -c " + shlex.quote(code)

    def finish(self, job_id):
        for _ in range(12):
            result = self.manager.get(job_id, wait_seconds=1)
            if result["status"] != "running":
                return result
        self.fail("job failed to finish")

    def test_success_and_nonzero_exit(self):
        self.manager.start("good", "printf hello", wait_seconds=0)
        got = self.finish("good")
        self.assertEqual((got["status"], got["exit_code"], got["output"]), ("finished", 0, "hello"))
        self.manager.start("bad", "printf error; exit 7", wait_seconds=0)
        self.assertEqual(self.finish("bad")["exit_code"], 7)

    def test_deduplicates_and_rejects_changed_arguments(self):
        cmd = "printf one >> count.txt"
        self.manager.start("unique", cmd, wait_seconds=0)
        self.finish("unique")
        self.manager.start("unique", cmd)
        self.assertEqual((self.ws.root / "repo/count.txt").read_text(), "one")
        with self.assertRaises(ValueError):
            self.manager.start("unique", "printf two")

    def test_async_and_cancel(self):
        got = self.manager.start("long", "sleep 20", wait_seconds=0)
        self.assertEqual(got["status"], "running")
        self.assertEqual(self.manager.cancel("long")["status"], "cancelled")

    def test_timeout(self):
        self.manager.start("timeout", "sleep 20", timeout_seconds=1, wait_seconds=0)
        self.assertEqual(self.finish("timeout")["status"], "timed_out")

    def test_log_cap_and_pagination(self):
        self.manager.start("noisy", self.command("print('x'*3000)"), wait_seconds=0)
        got = self.finish("noisy")
        self.assertEqual(got["log_bytes"], 1024)
        self.assertTrue(got["log_truncated"])
        chunk = self.manager.get("noisy", max_bytes=100)
        self.assertEqual(chunk["next_offset"], 100)
        self.assertTrue(chunk["has_more_output"])
        self.assertEqual(len(self.manager.get("noisy", offset=100)["output"]), 924)

    def test_concurrency_limit(self):
        self.manager.start("first", "sleep 20", wait_seconds=0)
        self.manager.start("second", "sleep 20", wait_seconds=0)
        with self.assertRaises(ValueError):
            self.manager.start("third", "true", wait_seconds=0)
        self.manager.cancel("first")
        self.manager.cancel("second")

    def test_recovery_deduplicates_completed(self):
        cmd = "printf once >> count.txt"
        self.manager.start("persist", cmd, wait_seconds=0)
        self.finish("persist")
        self.manager.close()
        self.manager = JobManager(self.ws, self.state)
        self.manager.start("persist", cmd)
        self.assertEqual((self.ws.root / "repo/count.txt").read_text(), "once")

    def test_shutdown_and_restart_status(self):
        self.manager.start("interrupted", "sleep 20", wait_seconds=0)
        self.manager.close()
        self.manager = JobManager(self.ws, self.state)
        self.assertEqual(self.manager.get("interrupted")["status"], "interrupted")
        # Simulate a process killed before persisting its terminal state.
        path = self.state / "interrupted.json"
        record = json.loads(path.read_text())
        record["status"] = "running"
        path.write_text(json.dumps(record))
        self.manager.close()
        self.manager = JobManager(self.ws, self.state)
        self.assertEqual(self.manager.get("interrupted")["status"], "interrupted")

    def test_record_limit_and_invalid_request(self):
        self.manager.max_records = 1
        self.manager.start("only", "true", wait_seconds=0)
        self.finish("only")
        with self.assertRaises(ValueError):
            self.manager.start("second", "true")
        with self.assertRaises(ValueError):
            self.manager.start("../bad", "true")
        with self.assertRaises(ValueError):
            self.manager.start("out", "true", cwd="../")


if __name__ == "__main__":
    unittest.main()
