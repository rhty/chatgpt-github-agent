"""Source snapshots and change export. Never executes outside the worker."""
from __future__ import annotations
import base64
import io
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import threading
from pathlib import Path, PurePosixPath

MAX_FILE = 8*1024*1024
MAX_TOTAL = 160*1024*1024
ID = re.compile(r'[a-z0-9][a-z0-9-]{0,47}\Z')

def safe_path(raw):
    p = PurePosixPath(raw)
    if not raw or raw.startswith('/') or '\\' in raw or any(x in ('.','..','.git') for x in raw.split('/')):
        raise ValueError('Unsafe repository path')
    if any(ord(c)<32 for c in raw):
        raise ValueError('Control characters in path')
    return p

class Repositories:
    def __init__(self, root: Path, jobs):
        self.root, self.jobs = root, jobs
        self.lock = threading.RLock()

    def path(self, task_id):
        if not isinstance(task_id,str) or not ID.fullmatch(task_id):
            raise ValueError('task_id: 1..48 lowercase letters/digits/hyphens')
        return self.root / 'tasks' / task_id / 'repo'

    def git(self, p, *args):
        env = {'PATH':os.getenv('PATH','/usr/bin:/bin'), 'HOME':'/tmp', 'LANG':'C.UTF-8',
               'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','GIT_TERMINAL_PROMPT':'0'}
        proc = subprocess.run(['git','-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false',
                               '-c','core.autocrlf=false','-C',str(p),*args],
                              env=env, capture_output=True, timeout=60)
        if proc.returncode:
            raise RuntimeError('Worker Git operation failed: '+proc.stderr.decode(errors='replace')[:500])
        return proc.stdout

    def busy(self):
        with self.jobs.lock:
            return bool(self.jobs.processes)

    def prepare(self, task_id, archive_base64):
        with self.lock:
            p = self.path(task_id)
            if p.is_dir():
                return {'path':str(p),'reused':True, 'snapshot_sha':(p.parent / 'snapshot-sha').read_text().strip()}
            if self.busy():
                raise ValueError('Finish running commands before preparing another task')
            blob = base64.b64decode(archive_base64, validate=True)
            if len(blob)>48*1024*1024:
                raise ValueError('Compressed source archive is too large')
            p.parent.mkdir(parents=True,exist_ok=True)
            tmp = Path(tempfile.mkdtemp(prefix='import-',dir=p.parent))
            total = 0
            names = set()
            try:
                with tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz') as tar:
                    for n,m in enumerate(tar):
                        if n>=25000:
                            raise ValueError('Source archive has too many entries')
                        parts = PurePosixPath(m.name).parts
                        if len(parts)<=1:
                            continue
                        raw = '/'.join(parts[1:])
                        safe_path(raw)
                        if raw in names:
                            raise ValueError('Duplicate archive member')
                        names.add(raw)
                        dest = tmp / raw
                        if m.isdir():
                            dest.mkdir(parents=True,exist_ok=True)
                            continue
                        if not m.isfile():
                            raise ValueError('This starter does not import symlinks, submodules, or special files')
                        total += m.size
                        if m.size>MAX_FILE or total>MAX_TOTAL:
                            raise ValueError('Source exceeds starter size limits')
                        if raw=='.gitmodules':
                            raise ValueError('Git submodules are not supported by this starter')
                        stream = tar.extractfile(m)
                        if stream is None:
                            raise ValueError('Missing archive member')
                        data = stream.read(MAX_FILE+1)
                        if len(data)!=m.size:
                            raise ValueError('Truncated source file')
                        if data.startswith(b'version https://git-lfs.github.com/spec/v1\n'):
                            raise ValueError('Git LFS pointers require a separate import implementation')
                        dest.parent.mkdir(parents=True,exist_ok=True)
                        dest.write_bytes(data)
                        dest.chmod(0o755 if m.mode & 0o111 else 0o644)
                self.git(tmp,'init','-q')
                # The GitHub archive contains tracked files even when .gitignore matches them.
                self.git(tmp,'add','--all','--force')
                self.git(tmp,'-c','user.name=Local Snapshot','-c','user.email=snapshot@localhost',
                         'commit','-q','--allow-empty','-m','Source snapshot (not pushed)')
                sha = self.git(tmp,'rev-parse','HEAD').decode().strip()
                (p.parent / 'snapshot-sha').write_text(sha)
                os.replace(tmp,p)
            finally:
                if tmp.exists():
                    shutil.rmtree(tmp)
            return {'path':str(p),'reused':False,'source_bytes':total,'snapshot_sha':sha}

    def changes(self, task_id, snapshot_sha):
        with self.lock:
            if self.busy():
                raise ValueError('Commands are running; wait or cancel before exporting changes')
            p = self.path(task_id)
            if not re.fullmatch(r'[0-9a-f]{40}', snapshot_sha):
                raise ValueError('Invalid snapshot commit')
            tracked = self.git(p,'diff','--no-renames','--name-only','-z',snapshot_sha,'--').split(b'\0')
            new = self.git(p,'ls-files','--others','--exclude-standard','-z').split(b'\0')
            names = sorted({x.decode('utf-8') for x in tracked+new if x})
            if len(names)>200:
                raise ValueError('More than 200 changed files; split the task')
            entries=[]
            total=0
            for raw in names:
                safe_path(raw)
                f=p/raw
                if f.is_symlink():
                    raise ValueError('Publishing symlinks is not supported')
                if not f.exists():
                    entries.append({'path':raw,'deleted':True})
                    continue
                resolved=f.resolve()
                if not resolved.is_relative_to(p.resolve()) or not f.is_file():
                    raise ValueError('Export must remain inside the task repository')
                size=f.stat().st_size
                total+=size
                if size>MAX_FILE or total>12*1024*1024:
                    raise ValueError('Changes exceed starter size limits')
                data=f.read_bytes()
                entries.append({'path':raw,'deleted':False,
                                'mode':'100755' if f.stat().st_mode & 0o111 else '100644',
                                'base64':base64.b64encode(data).decode()})
            return {'changes':entries,'total_bytes':total}
