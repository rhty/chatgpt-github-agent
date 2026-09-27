from __future__ import annotations
import json
import urllib.request
import urllib.error

class Worker:
    def __init__(self,url='http://worker:8080'):
        # The target is an operator configuration, never supplied by an MCP tool.
        self.url=url.rstrip('/')
    def health(self):
        with urllib.request.urlopen(self.url+'/healthz',timeout=5) as r:
            return json.loads(r.read(16384))
    def call(self, action, **args):
        data=json.dumps({'action':action,'args':args}).encode()
        req=urllib.request.Request(self.url+'/rpc',data=data,headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=100) as r:
                payload=r.read(24*1024*1024+1)
                if len(payload)>24*1024*1024:
                    raise ValueError('Worker result is too large')
                return json.loads(payload)['result']
        except urllib.error.HTTPError as exc:
            try: msg=json.loads(exc.read(4096)).get('error','Worker error')
            except ValueError: msg='Worker error'
            raise RuntimeError(str(msg)) from None
        except urllib.error.URLError:
            raise RuntimeError('Worker is unreachable. Retry; if still unavailable, run start.sh on the Mac.') from None
