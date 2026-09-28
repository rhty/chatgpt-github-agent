"""GitHub App authentication. No tokens ever cross into the worker."""
from __future__ import annotations
import base64
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import quote, urlencode
from net import request

PERMISSIONS = {'contents':'write', 'pull_requests':'write', 'issues':'write',
               'actions':'read', 'checks':'read', 'statuses':'read', 'metadata':'read'}
REPO_RE = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z')

def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip('=')

class GitHub:
    def __init__(self, app_id: str, key_file: Path, allowed: list[str]):
        if not app_id.isdigit():
            raise ValueError('GITHUB_APP_ID must be the numeric App ID, not Client ID')
        if not allowed or any(not REPO_RE.fullmatch(r) for r in allowed):
            raise ValueError('ALLOWED_REPOS must contain owner/repository values')
        self.app_id, self.key_file = app_id, key_file
        self.allowed = {r.lower():r for r in allowed}
        self.tokens = {}

    def validate(self, repo: str) -> str:
        if repo.lower() not in self.allowed:
            raise ValueError('Repository is not in ALLOWED_REPOS')
        return self.allowed[repo.lower()]

    def jwt(self) -> str:
        now = int(time.time())
        message = (b64url(b'{"alg":"RS256","typ":"JWT"}') + '.' +
                   b64url(json.dumps({'iat':now-60,'exp':now+480,'iss':self.app_id},
                                     separators=(',',':')).encode()))
        proc = subprocess.run(['openssl','dgst','-sha256','-sign',str(self.key_file)],
                              input=message.encode(), capture_output=True, timeout=10)
        if proc.returncode:
            raise RuntimeError('GitHub App private key could not be read or used to sign')
        return message + '.' + b64url(proc.stdout)

    @staticmethod
    def headers(token):
        return {'Authorization':f'Bearer {token}', 'Accept':'application/vnd.github+json',
                'X-GitHub-Api-Version':'2022-11-28', 'User-Agent':'chatgpt-github-agent-local'}

    def app(self):
        return request('GET','https://api.github.com/app', headers=self.headers(self.jwt()))

    def token(self, repo):
        repo = self.validate(repo)
        cached = self.tokens.get(repo)
        if cached and cached[1] > time.time():
            return cached[0]
        headers = self.headers(self.jwt())
        install = request('GET',f'https://api.github.com/repos/{repo}/installation', headers=headers)
        issued = request('POST', f'https://api.github.com/app/installations/{install["id"]}/access_tokens',
                         headers=headers, body={'repositories':[repo.split('/')[1]], 'permissions':PERMISSIONS})
        self.tokens[repo] = (issued['token'], time.time()+3000)
        return issued['token']

    def call(self, repo, method, path, body=None, *, binary=False, limit=24*1024*1024,
             sink=None, label='GitHub API response', timeout=60):
        repo = self.validate(repo)
        if (path and not path.startswith('/')) or '://' in path:
            raise ValueError('Expected repository-relative API path')
        return request(method, f'https://api.github.com/repos/{repo}{path}',
                       headers=self.headers(self.token(repo)), body=body, binary=binary, limit=limit,
                       sink=sink, label=label, timeout=timeout)

    def page(self, repo, path, page=1):
        if not isinstance(page,int) or not 1 <= page <= 1000:
            raise ValueError('page must be 1..1000')
        sep = '&' if '?' in path else '?'
        data = self.call(repo,'GET',path+sep+urlencode({'per_page':50,'page':page}))
        if not isinstance(data,list):
            raise ValueError('Expected a list response')
        return {'items':data, 'next_page':page+1 if len(data)==50 else None}

    def download_source(self, repo, sha, destination):
        if not re.fullmatch(r'[0-9a-f]{40}',sha):
            raise ValueError('Invalid source commit SHA')
        try:
            mib = int(os.getenv('SOURCE_MAX_ARCHIVE_MIB', '512'))
        except ValueError:
            raise ValueError('SOURCE_MAX_ARCHIVE_MIB must be a positive integer') from None
        if mib <= 0:
            raise ValueError('SOURCE_MAX_ARCHIVE_MIB must be a positive integer')
        return self.call(repo,'GET',f'/tarball/{sha}', binary=True, limit=mib*1024*1024,
                         sink=destination, timeout=600,
                         label=f'Repository archive {repo}@{sha[:12]} (SOURCE_MAX_ARCHIVE_MIB)')
