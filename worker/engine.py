"""Local execution primitives. Docker, NOT this module, is the security boundary.

Never run this execution engine on a host containing credentials. Commands have
all permissions of the container user. Job records are operational state, not a
tamper-proof audit trail. Only one server process may use a given state directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_RESULT_CHARS = 32000


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def resolve(self, path: str) -> Path:
        p = Path(path)
        p = (p if p.is_absolute() else self.root / p).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError("Path must remain inside /workspace, including symlink targets")
        return p

    def list_files(self, path: str = ".", limit: int = 200) -> dict[str, Any]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        p = self.resolve(path)
        if not p.is_dir():
            raise ValueError("Not a directory")
        entries = sorted(p.iterdir(), key=lambda x: x.name)
        return {"path": str(p.relative_to(self.root)), "total": len(entries),
                "truncated": len(entries) > limit,
                "entries": [{"name": x.name, "kind": "symlink" if x.is_symlink()
                             else "directory" if x.is_dir() else "file"}
                            for x in entries[:limit]]}

    def read_file(self, path: str, start_line: int = 1, max_lines: int = 300) -> dict[str, Any]:
        if start_line < 1 or not 1 <= max_lines <= 2000:
            raise ValueError("Invalid line range")
        p = self.resolve(path)
        if not p.is_file() or p.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Expected a regular file no larger than 4 MiB")
        data = p.read_bytes()
        text = data.decode("utf-8")
        if "\x00" in text:
            raise ValueError("Binary files are not supported by read_file")
        lines = text.splitlines(keepends=True)
        selected = "".join(lines[start_line - 1:start_line - 1 + max_lines])
        return {"path": str(p.relative_to(self.root)),
                "sha256": hashlib.sha256(data).hexdigest(),
                "start_line": start_line, "total_lines": len(lines),
                "content": selected[:MAX_RESULT_CHARS],
                "truncated": len(selected) > MAX_RESULT_CHARS or
                start_line - 1 + max_lines < len(lines)}

    def write_file(self, path: str, content: str,
                   expected_sha256: str | None = None) -> dict[str, Any]:
        data = content.encode("utf-8")
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("Maximum file size is 4 MiB")
        with self._lock:
            p = self.resolve(path)
            mode = 0o644
            if p.exists():
                if not p.is_file() or p.stat().st_size > MAX_FILE_BYTES:
                    raise ValueError("Expected a regular file no larger than 4 MiB")
                current = hashlib.sha256(p.read_bytes()).hexdigest()
                if expected_sha256 != current:
                    raise ValueError("Existing file changed or expected_sha256 missing; read it first")
                mode = p.stat().st_mode & 0o777
            elif expected_sha256 is not None:
                raise ValueError("File does not exist; expected_sha256 must be null")
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, temp = tempfile.mkstemp(prefix=".mcp-write-", dir=p.parent)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.chmod(temp, mode)
                os.replace(temp, p)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        return {"path": str(p.relative_to(self.root)), "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest()}


class JobManager:
    def __init__(self, workspace: Workspace, state: Path, *, max_jobs: int = 2,
                 max_log_bytes: int = 8 * 1024 * 1024, max_records: int = 200):
        self.workspace = workspace
        self.state = state.resolve()
        self.state.mkdir(parents=True, exist_ok=True)
        self.max_jobs = max_jobs
        self.max_log_bytes = max_log_bytes
        self.max_records = max_records
        self.lock = threading.RLock()
        self.records: dict[str, dict[str, Any]] = {}
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self.events: dict[str, threading.Event] = {}
        self.threads: list[threading.Thread] = []
        self.closed = False
        # Completed results survive container recreation. A running process does not.
        for p in sorted(self.state.glob("*.json")):
            try:
                record = json.loads(p.read_text())
                job_id = record["job_id"]
                if not self.valid_id(job_id) or p.stem != job_id:
                    continue
                if record["status"] == "running":
                    record.update(status="interrupted", finished_at=time.time(),
                                  interruption="Server restarted; do not infer command success")
                self.records[job_id] = record
                self._save(job_id)
            except (OSError, ValueError, KeyError, TypeError):
                continue

    @staticmethod
    def valid_id(value: str) -> bool:
        return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value) is not None

    def _save(self, job_id: str) -> None:
        tmp = self.state / f"{job_id}.json.tmp"
        tmp.write_text(json.dumps(self.records[job_id], ensure_ascii=False))
        os.replace(tmp, self.state / f"{job_id}.json")

    @staticmethod
    def _kill_group(proc: subprocess.Popen[bytes], sig: int) -> None:
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass

    def _collect_output(self, job_id: str, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stdout is not None
        remaining = self.max_log_bytes
        try:
            with (self.state / f"{job_id}.log").open("wb") as f:
                while True:
                    data = os.read(proc.stdout.fileno(), 65536)
                    if not data:
                        break
                    written = min(len(data), remaining)
                    if written:
                        f.write(data[:written])
                        f.flush()
                        remaining -= written
                    if written < len(data):
                        with self.lock:
                            self.records[job_id]["log_truncated"] = True
        finally:
            proc.stdout.close()

    def _watch(self, job_id: str, proc: subprocess.Popen[bytes], timeout: int,
               reader: threading.Thread) -> None:
        status = "finished"
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            status = "timed_out"
            self._kill_group(proc, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._kill_group(proc, signal.SIGKILL)
                proc.wait()
        finally:
            # Background children in the same group must not outlive the command.
            self._kill_group(proc, signal.SIGKILL)
            reader.join(timeout=4)
            with self.lock:
                record = self.records[job_id]
                if record.get("cancel_requested"):
                    status = "cancelled"
                if record.get("shutdown_requested"):
                    status = "interrupted"
                record.update(status=status, exit_code=proc.returncode,
                              finished_at=time.time())
                self.processes.pop(job_id, None)
                self._save(job_id)
                self.events[job_id].set()

    def start(self, request_id: str, command: str, cwd: str = "repo",
              timeout_seconds: int = 1800, wait_seconds: int = 2) -> dict[str, Any]:
        if not self.valid_id(request_id):
            raise ValueError("request_id must be 1-80 ASCII letters, digits, underscores or hyphens")
        if not command.strip() or len(command) > 64000:
            raise ValueError("command must be nonempty and at most 64000 characters")
        if not 1 <= timeout_seconds <= 7200 or not 0 <= wait_seconds <= 8:
            raise ValueError("timeout_seconds: 1-7200; wait_seconds: 0-8")
        directory = self.workspace.resolve(cwd)
        if not directory.is_dir():
            raise ValueError("cwd must be an existing workspace directory")
        identity = {"command": command, "cwd": str(directory), "timeout_seconds": timeout_seconds}
        fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        with self.lock:
            if self.closed:
                raise ValueError("Server is shutting down")
            if request_id in self.records:
                if self.records[request_id]["fingerprint"] != fingerprint:
                    raise ValueError("request_id already belongs to a different command")
            else:
                if len(self.processes) >= self.max_jobs:
                    raise ValueError("Too many running jobs; inspect or cancel an existing job first")
                if len(self.records) >= self.max_records:
                    raise ValueError("Job record cap reached; stop the stack and archive/reset job state")
                # Deliberately no host/OpenAI/GitHub credentials in the child environment.
                allowed = ("PATH", "HOME", "LANG", "LC_ALL", "TERM", "TMPDIR", "GOPATH",
                           "GOCACHE", "GOMODCACHE", "GOTOOLCHAIN", "NPM_CONFIG_CACHE",
                           "COREPACK_HOME", "CI", "PYTHONDONTWRITEBYTECODE")
                env = {k: os.environ[k] for k in allowed if k in os.environ}
                env.setdefault("PATH", "/usr/local/go/bin:/usr/local/bin:/usr/bin:/bin")
                env["GIT_TERMINAL_PROMPT"] = "0"
                env["PYTHONUNBUFFERED"] = "1"
                proc = subprocess.Popen(["/bin/bash", "--noprofile", "--norc", "-c", command],
                                        cwd=directory, env=env, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        start_new_session=True)
                self.records[request_id] = dict(job_id=request_id, **identity,
                                               fingerprint=fingerprint, status="running",
                                               started_at=time.time(), exit_code=None,
                                               log_truncated=False)
                self.processes[request_id] = proc
                self.events[request_id] = threading.Event()
                self._save(request_id)
                reader = threading.Thread(target=self._collect_output,
                                          args=(request_id, proc), daemon=True)
                watcher = threading.Thread(target=self._watch,
                                           args=(request_id, proc, timeout_seconds, reader), daemon=True)
                self.threads.extend([reader, watcher])
                reader.start()
                watcher.start()
        return self.get(request_id, wait_seconds=wait_seconds)

    def get(self, job_id: str, offset: int = 0, max_bytes: int = 16000,
            wait_seconds: int = 0) -> dict[str, Any]:
        if not self.valid_id(job_id) or offset < 0 or not 1 <= max_bytes <= 64000 or not 0 <= wait_seconds <= 8:
            raise ValueError("Invalid job_id, byte range, or wait_seconds")
        with self.lock:
            if job_id not in self.records:
                raise ValueError("Unknown job_id")
            event = self.events.get(job_id)
        if event and wait_seconds:
            event.wait(wait_seconds)
        with self.lock:
            result = dict(self.records[job_id])
        log = self.state / f"{job_id}.log"
        data = b""
        size = 0
        if log.is_file():
            with log.open("rb") as f:
                size = os.fstat(f.fileno()).st_size
                f.seek(offset)
                data = f.read(max_bytes)
        result.pop("fingerprint", None)
        result.update(output=data.decode("utf-8", errors="replace"), offset=offset,
                      next_offset=offset + len(data), log_bytes=size,
                      has_more_output=offset + len(data) < size)
        return result

    def list(self, limit: int = 20) -> dict[str, Any]:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be 1-200")
        with self.lock:
            records = sorted(self.records.values(), key=lambda r: r["started_at"], reverse=True)
            keys = ("job_id", "command", "cwd", "status", "exit_code", "started_at")
            return {"jobs": [{k: r.get(k) for k in keys} for r in records[:limit]],
                    "total": len(records), "max_records": self.max_records}

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            if job_id not in self.records:
                raise ValueError("Unknown job_id")
            proc = self.processes.get(job_id)
            if proc:
                self.records[job_id]["cancel_requested"] = True
                self._kill_group(proc, signal.SIGKILL)
        return self.get(job_id, wait_seconds=2)

    def close(self) -> None:
        with self.lock:
            self.closed = True
            for job_id, proc in list(self.processes.items()):
                self.records[job_id]["shutdown_requested"] = True
                self._kill_group(proc, signal.SIGKILL)
        for t in self.threads:
            t.join(timeout=5)
