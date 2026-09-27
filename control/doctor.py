"""Read-only setup checks. No secrets are printed."""
import json
import sys
from urllib.parse import quote
from app import create_controller

def main():
    c=create_controller()
    result=c.system_status()
    result['repositories']=[]
    ok=result.get('github_app',{}).get('ok') and result.get('worker',{}).get('ok')
    worker=result.get('worker',{})
    if any(worker.get(k) for k in ('github_key_present','tunnel_key_present','docker_socket_present')):
        ok=False
        result['isolation_error']='A secret or Docker socket is visible to the worker'
    for repo in c.gh.allowed.values():
        try:
            info=c.gh.call(repo,'GET','')
            c.gh.call(repo,'GET','/commits/'+quote(info['default_branch'],safe=''))
            result['repositories'].append({'repo':repo,'ok':True,'default_branch':info['default_branch']})
        except Exception as e:
            result['repositories'].append({'repo':repo,'ok':False,'error':str(e)[:500]});ok=False
    print(json.dumps(result,ensure_ascii=False,indent=2))
    print('SETUP_CHECK_OK' if ok else 'SETUP_CHECK_FAILED')
    return 0 if ok else 1
if __name__=='__main__':
    try: sys.exit(main())
    except Exception as e:
        print('SETUP_CHECK_FAILED:',str(e)[:500]);sys.exit(1)
