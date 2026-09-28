"""Private worker RPC. No host port, no GitHub/OpenAI credentials, no Docker socket."""
from __future__ import annotations
import json
import os
import time
import signal
import tempfile
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from engine import Workspace, JobManager
from repository import Repositories

workspace=Workspace(Path(os.getenv('WORKSPACE_ROOT','/workspace')))
jobs=JobManager(workspace,Path(os.getenv('JOB_STATE_DIR','/state/jobs')),
                max_jobs=1,max_log_bytes=2*1024*1024,max_records=1200)
repos=Repositories(workspace.root,jobs)

def prune():
    """Bound disk use without asking the operator to open Docker."""
    with jobs.lock:
        finished=sorted((r for r in jobs.records.values() if r['status']!='running'),
                        key=lambda r:r.get('started_at',0))
        remove=finished[:max(0,len(jobs.records)-999)]
        remove += [r for r in finished if r.get('started_at',0)<time.time()-7*86400]
        for r in {r['job_id']:r for r in remove}.values():
            jid=r['job_id']
            jobs.records.pop(jid,None)
            jobs.events.pop(jid,None)
            for ext in ('.json','.log'):
                (jobs.state/(jid+ext)).unlink(missing_ok=True)

def dispatch(action,args):
    if action=='prepare': return repos.prepare(**args)
    if action=='changes': return repos.changes(**args)
    if action=='list_files': return workspace.list_files(**args)
    if action=='read_file': return workspace.read_file(**args)
    if action=='write_file': return workspace.write_file(**args)
    if action=='start_command':
        prune()
        return jobs.start(**args)
    if action=='get_job': return jobs.get(**args)
    if action=='list_jobs': return jobs.list(**args)
    if action=='cancel_job': return jobs.cancel(**args)
    raise ValueError('Unsupported worker operation')

class Handler(BaseHTTPRequestHandler):
    def log_message(self,format,*args):
        # Never log bodies, source contents or command arguments.
        pass
    def send_json(self,status,obj):
        data=json.dumps(obj,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        if self.path!='/healthz':
            self.send_json(404,{'error':'Not found'}); return
        self.send_json(200,{'ok':True,'running_jobs':len(jobs.processes),
                            'workspace':str(workspace.root),
                            'github_key_present':Path('/run/secrets/github_app_key').exists(),
                            'tunnel_key_present':Path('/run/secrets/tunnel_api_key').exists(),
                            'docker_socket_present':Path('/var/run/docker.sock').exists()})
    def receive_archive(self):
        task_id=self.path.removeprefix('/prepare/')
        repos.path(task_id)  # Validate before creating a temporary file or reading the body.
        if self.headers.get('Transfer-Encoding'):
            raise ValueError('Binary archive upload requires Content-Length, not chunked transfer')
        size=int(self.headers.get('Content-Length','0'))
        if not 0 < size <= repos.max_archive:
            raise ValueError(f'Compressed source upload: {size} bytes; '
                             f'SOURCE_MAX_ARCHIVE_MIB limit {repos.max_archive} bytes')
        with repos.lock:
            if repos.busy():
                raise ValueError('Finish running commands before preparing another task')
            staging=jobs.state.parent/'source-imports'
            staging.mkdir(mode=0o700,exist_ok=True)
            self.connection.settimeout(120)
            with tempfile.TemporaryFile(dir=staging) as source:
                remaining=size
                while remaining:
                    data=self.rfile.read(min(256*1024,remaining))
                    if not data:
                        raise ValueError('Truncated source upload; retry the same task_id')
                    source.write(data)
                    remaining-=len(data)
                source.seek(0)
                return repos.prepare_archive(task_id,source)

    def do_POST(self):
        if self.path.startswith('/prepare/'):
            try:
                self.send_json(200,{'result':self.receive_archive()})
            except (ValueError,KeyError,TypeError,RuntimeError,OSError) as exc:
                self.send_json(400,{'error':str(exc)[:1200]})
            except Exception:
                self.send_json(500,{'error':'Source import failed unexpectedly'})
            return
        if self.path!='/rpc':
            self.send_json(404,{'error':'Not found'}); return
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=72*1024*1024:
                raise ValueError('Invalid request size')
            body=json.loads(self.rfile.read(size))
            result=dispatch(body['action'],body.get('args',{}))
            self.send_json(200,{'result':result})
        except (ValueError,KeyError,TypeError,RuntimeError,OSError) as exc:
            self.send_json(400,{'error':str(exc)[:1200]})
        except Exception:
            self.send_json(500,{'error':'Worker operation failed unexpectedly'})

if __name__=='__main__':
    server=ThreadingHTTPServer(('0.0.0.0',int(os.getenv('WORKER_PORT','8080'))),Handler)
    try:
        server.serve_forever()
    finally:
        jobs.close()
        server.server_close()
