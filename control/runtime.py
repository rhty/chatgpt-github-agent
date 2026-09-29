"""Supervise a loopback HTTP MCP server and the official tunnel client.

A disconnected HTTP request has no ownership of the MCP process or shared stdio.
No model API is called. Neither requests nor commands are automatically replayed.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

MCP_URL = 'http://127.0.0.1:8081/mcp'
LIVE_URL = 'http://127.0.0.1:8081/livez'
MCP_COMMAND = ['/opt/venv/bin/python', '/opt/control/mcp_http_server.py']


def child_environment(source=None):
    env = dict(os.environ if source is None else source)
    # A legacy image/operator environment must not select two main transports.
    env.pop('MCP_COMMAND', None)
    env['MCP_SERVER_URL'] = MCP_URL
    return env


def live():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(LIVE_URL, timeout=1) as response:
            return response.status == 200 and response.read(64) == b'github-agent-mcp-live'
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def wait_for_mcp(process, stopped, timeout=60):
    deadline = time.monotonic() + timeout
    while not stopped.is_set() and time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('HTTP MCP process exited before startup completed')
        if live():
            if process.poll() is not None:
                raise RuntimeError('HTTP MCP process exited during startup')
            return
        stopped.wait(0.1)
    if not stopped.is_set():
        raise RuntimeError('HTTP MCP startup timed out')


def stop_children(children):
    # Signal both first, then wait/kill with one shared bound under Docker's grace.
    active = [p for p in reversed(children) if p.poll() is None]
    for p in active:
        try:
            p.terminate()
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5
    for p in active:
        try:
            p.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                p.kill()
            except ProcessLookupError:
                pass
            p.wait()


def run(arguments, stopped):
    children = []
    try:
        env = child_environment()
        server = subprocess.Popen(MCP_COMMAND, env=env, stdin=subprocess.DEVNULL)
        children.append(server)
        wait_for_mcp(server, stopped)
        if stopped.is_set():
            return 0
        tunnel = subprocess.Popen(
            ['/usr/bin/tunnel-client', 'run', *arguments],
            env=env, stdin=subprocess.DEVNULL,
        )
        children.append(tunnel)
        while not stopped.wait(0.1):
            if any(p.poll() is not None for p in children):
                print('Control child exited; stopping its peer for container recovery.',
                      file=sys.stderr, flush=True)
                return 1
        return 0
    except (OSError, RuntimeError) as exc:
        # Fixed local process paths only; never print environment/argv/key content.
        print(f'Control runtime failed: {type(exc).__name__}', file=sys.stderr, flush=True)
        return 1
    finally:
        stop_children(children)


def main():
    stopped = threading.Event()
    def stop(signum, frame):
        stopped.set()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop)
    return run(sys.argv[1:], stopped)


if __name__ == '__main__':
    raise SystemExit(main())
