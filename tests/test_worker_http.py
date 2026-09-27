"""Real loopback HTTP worker test; GitHub and MCP are NOT exercised here."""
import base64
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'control'),str(ROOT/'tests')]
from worker_api import Worker
from test_agent import archive

class WorkerHTTPTests(unittest.TestCase):
    def test_real_http_task_write_execute_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            with socket.socket() as s:
                s.bind(('127.0.0.1',0));port=s.getsockname()[1]
            env={**os.environ,'WORKER_PORT':str(port),'WORKSPACE_ROOT':tmp+'/workspace',
                 'JOB_STATE_DIR':tmp+'/jobs','PYTHONDONTWRITEBYTECODE':'1'}
            proc=subprocess.Popen([sys.executable,str(ROOT/'worker/server.py')],env=env,
                                  stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            w=Worker(f'http://127.0.0.1:{port}')
            try:
                for _ in range(80):
                    try:
                        if w.health()['ok']:break
                    except OSError:pass
                    if proc.poll() is not None:self.fail('Worker did not start: '+proc.stderr.read().decode())
                    time.sleep(.025)
                else:self.fail('Worker did not become reachable')
                data=base64.b64encode(archive({'README.md':'original'})).decode()
                task=w.call('prepare',task_id='http-test',archive_base64=data)
                w.call('write_file',path=task['path']+'/hello.txt',content='hello\n')
                j=w.call('start_command',request_id='http-job-1',command="test -f hello.txt && printf HTTP_OK",cwd=task['path'],timeout_seconds=10,wait_seconds=2)
                result=w.call('get_job',job_id=j['job_id'],wait_seconds=2)
                self.assertEqual(result['exit_code'],0)
                exported=w.call('changes',task_id='http-test',snapshot_sha=task['snapshot_sha'])
                self.assertEqual([r['path'] for r in exported['changes']],['hello.txt'])
            finally:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
                proc.stderr.close()
