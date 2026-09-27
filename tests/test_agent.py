from __future__ import annotations
import base64
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote,urlsplit,parse_qs
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'control'),str(ROOT/'worker')]
from controller import Controller,path_ok,publish_path_ok
from store import Store
from github_api import GitHub,PERMISSIONS
from net import APIError
from engine import Workspace,JobManager
from repository import Repositories


def archive(entries):
    out=io.BytesIO()
    with tarfile.open(fileobj=out,mode='w:gz') as t:
        for name,value in entries.items():
            m=tarfile.TarInfo('owner-repo-sha/'+name)
            if value is None:
                m.type=tarfile.SYMTYPE;m.linkname='/etc/passwd';t.addfile(m)
            else:
                if isinstance(value,str): value=value.encode()
                m.size=len(value);m.mode=0o644;t.addfile(m,io.BytesIO(value))
    return out.getvalue()

def digest(v):
    return hashlib.sha1(json.dumps(v,sort_keys=True).encode()).hexdigest()

class FakeGitHub:
    def __init__(self):
        self.allowed={'owner/repo':'owner/repo'}
        self.calls=[];self.refs={};self.prs={};self.comments=[]
        base={'README.md':{'content':'# Original\n','mode':'100644'},'old.txt':{'content':'old','mode':'100644'}}
        self.base_tree=digest(base);self.trees={self.base_tree:base}
        self.base_sha='a'*40;self.commits={self.base_sha:{'tree':self.base_tree,'parents':[]}}
        self.lose_ref_response=False;self.lose_reply_response=False
    def validate(self,repo):
        if repo.lower() not in self.allowed: raise ValueError('Not allowed')
        return 'owner/repo'
    def app(self): return {'id':123,'slug':'test-agent'}
    def download_source(self,repo,sha): return archive({'README.md':'# Original\n','old.txt':'old'})
    def page(self,repo,path,page=1):
        data=self.call(repo,'GET',path)
        return {'items':data[(page-1)*50:page*50],'next_page':page+1 if len(data)>=page*50 else None}
    def call(self,repo,method,path,body=None,**kw):
        self.validate(repo);self.calls.append((method,path,copy.deepcopy(body)))
        raw=unquote(urlsplit(path).path)
        if method=='GET' and path=='': return {'default_branch':'main','full_name':repo}
        if method=='GET' and raw=='/commits/main': return {'sha':self.base_sha,'commit':{'tree':{'sha':self.base_tree}}}
        if raw.startswith('/git/ref/heads/') and method=='GET':
            branch=raw[len('/git/ref/heads/'):]
            if branch not in self.refs: raise APIError(404,'Not found')
            return {'object':{'sha':self.refs[branch]}}
        if raw=='/git/trees' and method=='POST':
            tree=copy.deepcopy(self.trees[body['base_tree']])
            for x in body['tree']:
                if 'sha' in x and x['sha'] is None: tree.pop(x['path'],None)
                else: tree[x['path']]={k:x[k] for k in ('content','sha','mode') if k in x}
            sha=digest(tree);self.trees[sha]=tree;return {'sha':sha}
        if raw=='/git/blobs' and method=='POST': return {'sha':digest(body)}
        if raw=='/git/commits' and method=='POST':
            sha=digest(body);self.commits[sha]=copy.deepcopy(body);return {'sha':sha}
        if (raw=='/git/refs' and method=='POST') or (raw.startswith('/git/refs/heads/') and method=='PATCH'):
            branch=(body['ref'].removeprefix('refs/heads/') if method=='POST' else raw.removeprefix('/git/refs/heads/'))
            if method=='PATCH':
                assert body['force'] is False
                if self.refs[branch] not in self.commits[body['sha']]['parents']: raise APIError(422,'Not fast-forward')
            elif branch in self.refs: raise APIError(422,'Already exists')
            self.refs[branch]=body['sha']
            if self.lose_ref_response:
                self.lose_ref_response=False;raise RuntimeError('Lost ref response')
            return {'ref':'refs/heads/'+branch,'object':{'sha':body['sha']}}
        if raw=='/pulls' and method=='POST':
            n=len(self.prs)+1
            p={'number':n,'html_url':f'https://github.com/{repo}/pull/{n}','state':'open',**body,
               'head':{'ref':body['head'],'repo':{'full_name':repo}}}
            self.prs[n]=p;return copy.deepcopy(p)
        if raw=='/pulls' and method=='GET': return [copy.deepcopy(p) for p in self.prs.values() if p['state']=='open']
        if raw=='/pulls/1':
            p=self.prs[1]
            if method=='PATCH': p.update(body)
            result=copy.deepcopy(p);result['head']['sha']=self.refs[p['head']['ref']]
            return result
        if raw in ('/issues/1/comments','/pulls/1/comments') and method=='GET': return copy.deepcopy(self.comments)
        if raw=='/issues/1/comments' and method=='POST':
            c={'id':len(self.comments)+1,'body':body['body'],'html_url':'https://example.invalid/comment'}
            self.comments.append(c)
            if self.lose_reply_response:
                self.lose_reply_response=False;raise RuntimeError('Lost reply response')
            return copy.deepcopy(c)
        if raw.startswith('/pulls/comments/') and method=='GET':
            return {'id':4,'pull_request_url':f'https://api.github.com/repos/{repo}/pulls/1'}
        if raw=='/pulls/1/comments/4/replies' and method=='POST':
            c={'id':len(self.comments)+1,'body':body['body'],'html_url':'https://example.invalid/inline'}
            self.comments.append(c);return copy.deepcopy(c)
        raise AssertionError((method,path,body))

class DirectWorker:
    def __init__(self,root):
        self.ws=Workspace(root/'workspace');self.jobs=JobManager(self.ws,root/'jobs',max_jobs=1)
        self.repos=Repositories(self.ws.root,self.jobs)
    def health(self): return {'ok':True,'running_jobs':len(self.jobs.processes)}
    def call(self,action,**args):
        if action=='prepare':return self.repos.prepare(**args)
        if action=='changes':return self.repos.changes(**args)
        if action in ('list_files','read_file','write_file'):return getattr(self.ws,action)(**args)
        methods={'start_command':'start','get_job':'get','list_jobs':'list','cancel_job':'cancel'}
        return getattr(self.jobs,methods[action])(**args)
    def close(self):self.jobs.close()

class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.gh=FakeGitHub();self.w=DirectWorker(self.root)
        self.c=Controller(self.gh,self.w,Store(self.root/'control'))
    def tearDown(self):self.w.close();self.tmp.cleanup()
    def task(self):return self.c.start_task('owner/repo','example')
    def changed(self):
        t=self.task();self.c.write_file('example','hello.txt','hello\n');return t
    def publish(self):return self.c.publish_pr('example','Add hello','Tested locally','Add hello')

class FlowTests(Fixture):
    def test_prepare_reuse(self):
        t=self.task();self.assertTrue(Path(t['path']).exists())
        self.assertEqual(self.task()['path'],t['path']);self.assertEqual(self.gh.prs,{})
    def test_repo_allowlist(self):
        with self.assertRaises(ValueError):self.c.start_task('other/repo','example')
    def test_publish_creates_only_ai_branch(self):
        self.changed();p=self.publish()
        self.assertEqual(p['pr_number'],1);self.assertEqual(set(self.gh.refs),{'ai/example'})
        self.assertTrue(p['new_commit_created'])
    def test_publish_no_duplicate_commit_or_pr(self):
        self.changed();a=self.publish();count=len(self.gh.commits)
        b=self.publish();self.assertFalse(b['new_commit_created'])
        self.assertEqual(len(self.gh.commits),count);self.assertEqual(a['pr_url'],b['pr_url'])
    def test_second_commit_follows_parent_and_cumulative_tree(self):
        self.changed();first=self.publish()
        self.c.write_file('example','second.txt','second')
        second=self.publish()
        self.assertEqual(self.gh.commits[second['head_sha']]['parents'],[first['head_sha']])
        tree=self.gh.trees[self.gh.commits[second['head_sha']]['tree']]
        self.assertIn('hello.txt',tree);self.assertIn('second.txt',tree)
    def test_revert_published_change(self):
        t=self.changed();self.publish();(Path(t['path'])/'hello.txt').unlink()
        second=self.publish()
        self.assertEqual(self.gh.commits[second['head_sha']]['tree'],self.gh.base_tree)
    def test_external_advance_stops_publication(self):
        self.changed();self.publish();self.gh.refs['ai/example']='f'*40
        before=len(self.gh.calls)
        with self.assertRaises(ValueError):self.publish()
        self.assertFalse(any(m in ('PATCH','POST') for m,_,_ in self.gh.calls[before:]))
    def test_lost_ref_response_recovers(self):
        self.changed();self.gh.lose_ref_response=True
        with self.assertRaises(RuntimeError):self.publish()
        result=self.publish();self.assertEqual(result['pr_number'],1)
        self.assertEqual(len(self.gh.commits),2)
    def test_closed_pr_stops(self):
        self.changed();self.publish();self.gh.prs[1]['state']='closed'
        with self.assertRaises(ValueError):self.publish()
    def test_empty_pr_rejected(self):
        self.task()
        with self.assertRaises(ValueError):self.publish()
        self.assertFalse(self.gh.refs)
    def test_no_workflow_publication_even_via_shell(self):
        t=self.task();p=Path(t['path'])/'.github/workflows/test.yml';p.parent.mkdir(parents=True);p.write_text('name: bad')
        with self.assertRaises(ValueError):self.publish()
        self.assertFalse(self.gh.refs)
    def test_reply_deduplication(self):
        self.changed();self.publish()
        a=self.c.reply('example','reply-1','Done');b=self.c.reply('example','reply-1','Done')
        self.assertEqual(a['id'],b['id']);self.assertEqual(len(self.gh.comments),1)
        with self.assertRaises(ValueError):self.c.reply('example','reply-1','Different')
    def test_lost_reply_recovers(self):
        self.changed();self.publish();self.gh.lose_reply_response=True
        with self.assertRaises(RuntimeError):self.c.reply('example','reply-1','Done')
        self.c.reply('example','reply-1','Done');self.assertEqual(len(self.gh.comments),1)
    def test_inline_reply(self):
        self.changed();self.publish();self.c.reply('example','inline-1','Fixed',4)
        self.assertEqual(self.gh.comments[0]['html_url'],'https://example.invalid/inline')
    def test_tasks_survive_controller_restart(self):
        self.changed();p=self.publish()
        c2=Controller(self.gh,self.w,Store(self.root/'control'))
        self.assertEqual(c2.list_tasks()['tasks'][0]['pr_url'],p['pr_url'])
    def test_commands_and_logs(self):
        self.task();j=self.c.start_command('example','echo-1','printf tested')
        r=self.c.get_job('example',j['job_id'],wait_seconds=3)
        self.assertEqual(r['exit_code'],0);self.assertIn('tested',r['output'])
        with self.assertRaises(ValueError):self.c.start_command('example','echo-1','printf changed')
    def test_path_validation(self):
        self.task()
        for p in ('../key','/etc/passwd','a/../../secret','.git/config','x\\y'):
            with self.subTest(p=p), self.assertRaises(ValueError):self.c.read_file('example',p)
    def test_credential_file_publish_guard(self):
        for p in ('.env','x/private.pem','.aws/config','.env.production','.ssh/id_ed25519'):
            with self.subTest(p=p),self.assertRaises(ValueError):publish_path_ok(p)
        for p in ('src/app.py','.env.example','config/public.json'):publish_path_ok(p)

class RepositoryTests(Fixture):
    def prepare(self,entries):
        return self.w.repos.prepare('example',base64.b64encode(archive(entries)).decode())
    def test_symlink_archive_rejected(self):
        with self.assertRaises(ValueError):self.prepare({'link':None})
    def test_traversal_archive_rejected(self):
        with self.assertRaises(ValueError):self.prepare({'../escape':'bad'})
    def test_submodule_and_lfs_rejected(self):
        for data in ({'.gitmodules':'[submodule x]'},{'asset':'version https://git-lfs.github.com/spec/v1\n'}):
            with self.assertRaises(ValueError):self.prepare(data)
    def test_tracked_file_matching_gitignore_is_preserved(self):
        r=self.prepare({'.gitignore':'tracked.txt\n','tracked.txt':'old'})
        p=Path(r['path']);(p/'tracked.txt').write_text('new')
        diff=self.w.repos.changes('example',r['snapshot_sha'])['changes']
        self.assertEqual([v['path'] for v in diff],['tracked.txt'])

    def test_rename_exports_delete_and_add(self):
        r=self.prepare({'old':'old'});p=Path(r['path']);(p/'old').rename(p/'new')
        diff=self.w.repos.changes('example',r['snapshot_sha'])['changes']
        self.assertEqual({v['path'] for v in diff},{'old','new'})
        self.assertTrue(next(v for v in diff if v['path']=='old')['deleted'])
    def test_local_commit_does_not_hide_changes(self):
        r=self.prepare({'old':'old'});p=Path(r['path']);(p/'new').write_text('new')
        self.w.repos.git(p,'add','--all')
        self.w.repos.git(p,'-c','user.name=Test','-c','user.email=test@localhost','commit','-m','Local commit')
        diff=self.w.repos.changes('example',r['snapshot_sha'])['changes']
        self.assertEqual([v['path'] for v in diff],['new'])
    def test_binary_and_executable_export(self):
        r=self.prepare({'old':'old'});p=Path(r['path']);(p/'script').write_bytes(b'\0binary');(p/'script').chmod(0o755)
        row=self.w.repos.changes('example',r['snapshot_sha'])['changes'][0]
        self.assertEqual(row['mode'],'100755');self.assertEqual(base64.b64decode(row['base64']),b'\0binary')

class AuthTests(unittest.TestCase):
    def test_token_scoped_to_one_allowlisted_repo(self):
        gh=GitHub('123',Path('/not-used'),['owner/repo'])
        with patch.object(gh,'jwt',return_value='signed'),patch('github_api.request') as req:
            req.side_effect=[{'id':456},{'token':'temporary-test-token'}]
            self.assertEqual(gh.token('owner/repo'),'temporary-test-token')
            body=req.call_args.kwargs['body']
            self.assertEqual(body['repositories'],['repo']);self.assertEqual(body['permissions'],PERMISSIONS)
            self.assertEqual(gh.token('owner/repo'),'temporary-test-token');self.assertEqual(req.call_count,2)
    def test_jwt_signing(self):
        with tempfile.TemporaryDirectory() as d:
            key=Path(d)/'test.pem'
            subprocess.run(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:2048','-out',str(key)],check=True,capture_output=True)
            gh=GitHub('123',key,['owner/repo']);token=gh.jwt();parts=token.split('.')
            payload=json.loads(base64.urlsafe_b64decode(parts[1]+'=='))
            self.assertEqual(payload['iss'],'123');self.assertEqual(len(parts),3)
            sig=Path(d)/'sig';sig.write_bytes(base64.urlsafe_b64decode(parts[2]+'=='))
            pub=Path(d)/'pub';pub.write_bytes(subprocess.check_output(['openssl','pkey','-in',str(key),'-pubout']))
            check=subprocess.run(['openssl','dgst','-sha256','-verify',str(pub),'-signature',str(sig)],
                                 input='.'.join(parts[:2]).encode(),capture_output=True)
            self.assertEqual(check.returncode,0)

if __name__=='__main__':unittest.main()
