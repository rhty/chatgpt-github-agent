from __future__ import annotations
import fcntl
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path

ID=re.compile(r'[a-z0-9][a-z0-9-]{0,47}\Z')
class Store:
    def __init__(self,root:Path):
        self.root=root
        root.mkdir(parents=True,exist_ok=True)
    @staticmethod
    def validate(task_id):
        if not isinstance(task_id,str) or not ID.fullmatch(task_id):
            raise ValueError('task_id must be 1..48 lowercase letters, digits, hyphens')
    @contextmanager
    def lock(self):
        # Serialize state transitions across stdio processes/sessions.
        with (self.root/'controller.lock').open('a') as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(f,fcntl.LOCK_UN)
    def load(self,task_id):
        self.validate(task_id)
        p=self.root/(task_id+'.json')
        if not p.exists(): raise ValueError('Unknown task; call start_task or list_tasks first')
        return json.loads(p.read_text())
    def exists(self,task_id):
        self.validate(task_id)
        return (self.root/(task_id+'.json')).exists()
    def save(self,t):
        self.validate(t['task_id'])
        p=self.root/(t['task_id']+'.json')
        tmp=p.with_suffix('.tmp')
        tmp.write_text(json.dumps(t,ensure_ascii=False,indent=2))
        os.replace(tmp,p)
    def all(self):
        return [json.loads(p.read_text()) for p in sorted(self.root.glob('*.json'))]
