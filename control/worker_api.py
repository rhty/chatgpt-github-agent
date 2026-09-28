from __future__ import annotations
import json
import urllib.request
import urllib.error
from urllib.parse import quote
from net import NoRedirect

class Worker:
    def __init__(self,url='http://worker:8080'):
        # The target is an operator configuration, never supplied by an MCP tool.
        self.url=url.rstrip('/')
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def health(self):
        with self.opener.open(self.url+'/healthz',timeout=5) as r:
            return json.loads(r.read(16384))
    def _post(self,path,data,headers,timeout=100):
        req=urllib.request.Request(self.url+path,data=data,headers=headers,method='POST')
        try:
            with self.opener.open(req,timeout=timeout) as r:
                payload=r.read(24*1024*1024+1)
                if len(payload)>24*1024*1024:
                    raise ValueError('Worker result is too large')
                return json.loads(payload)['result']
        except urllib.error.HTTPError as exc:
            try: msg=json.loads(exc.read(4096)).get('error','Worker error')
            except ValueError: msg='Worker error'
            finally: exc.close()
            raise RuntimeError(str(msg)) from None
        except urllib.error.URLError:
            raise RuntimeError('Worker is unreachable. Retry; if still unavailable, run start.sh on the Mac.') from None
    def call(self, action, **args):
        data=json.dumps({'action':action,'args':args}).encode()
        return self._post('/rpc',data,{'Content-Type':'application/json'})
    def prepare_archive(self,task_id,source):
        """Upload a seekable archive without materializing it as bytes or Base64."""
        source.seek(0,2)
        size=source.tell()
        source.seek(0)
        return self._post('/prepare/'+quote(task_id,safe=''),source,
                          {'Content-Type':'application/gzip','Content-Length':str(size)},timeout=600)
