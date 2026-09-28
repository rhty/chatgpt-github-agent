"""Bounded downloads, large imports, and resumable preparation; no live GitHub calls."""
from __future__ import annotations
import base64
import contextlib
import hashlib
import io
import os
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'control'),str(ROOT/'worker'),str(ROOT/'tests')]
from net import request
from github_api import GitHub
from repository import Repositories
from worker_api import Worker
from test_agent import Fixture, archive

MIB=1024*1024

class Response(io.BytesIO):
    def __init__(self,data,headers=None):
        super().__init__(data)
        self.headers=headers or {}
        self.read_sizes=[]
    def read(self,n=-1):
        self.read_sizes.append(n)
        if n<0 or n>256*1024:
            raise AssertionError('Streaming response used an unbounded read')
        return super().read(n)

class DownloadTests(unittest.TestCase):
    def test_stream_to_file_in_bounded_chunks(self):
        data=b'x'*(2*MIB+11);response=Response(data,{'Content-Length':str(len(data))})
        with tempfile.TemporaryFile() as sink, patch('net.urllib.request.build_opener',return_value=Mock(open=Mock(return_value=response))):
            self.assertEqual(request('GET','https://api.github.com/test',binary=True,sink=sink,limit=len(data)),len(data))
            sink.seek(0);self.assertEqual(sink.read(),data)
        self.assertTrue(response.closed)
        self.assertLessEqual(max(response.read_sizes),256*1024)
    def test_missing_content_length_cannot_bypass_cap(self):
        response=Response(b'a'*11)
        with io.BytesIO() as sink,patch('net.urllib.request.build_opener',return_value=Mock(open=Mock(return_value=response))):
            with self.assertRaisesRegex(ValueError,'archive.*11 bytes.*10 bytes'):
                request('GET','https://api.github.com/test',binary=True,sink=sink,limit=10,label='archive')
    def test_declared_oversize_rejected_before_read(self):
        response=Response(b'x',{'Content-Length':'11'})
        with io.BytesIO() as sink,patch('net.urllib.request.build_opener',return_value=Mock(open=Mock(return_value=response))):
            with self.assertRaisesRegex(ValueError,'11 bytes.*10 bytes'):
                request('GET','https://api.github.com/test',binary=True,sink=sink,limit=10)
        self.assertEqual(response.read_sizes,[])
    def test_truncation_is_not_success(self):
        response=Response(b'x',{'Content-Length':'10'})
        with io.BytesIO() as sink,patch('net.urllib.request.build_opener',return_value=Mock(open=Mock(return_value=response))):
            with self.assertRaisesRegex(RuntimeError,'truncated'):
                request('GET','https://api.github.com/test',binary=True,sink=sink,limit=10)
    def test_redirect_drops_auth_but_retains_sink_and_limit(self):
        err=urllib.error.HTTPError('https://api.github.com/test',302,'redirect',
                                  {'Location':'https://codeload.github.com/test?token=private'},io.BytesIO())
        opener=Mock();opener.open.side_effect=[err,Response(b'abc')]
        with io.BytesIO() as sink,patch('net.urllib.request.build_opener',return_value=opener):
            self.assertEqual(request('GET','https://api.github.com/test',headers={'Authorization':'Bearer test'},
                                     binary=True,sink=sink,limit=3),3)
            self.assertEqual(sink.getvalue(),b'abc')
            first,second=[call.args[0] for call in opener.open.call_args_list]
            self.assertEqual(first.get_header('Authorization'),'Bearer test')
            self.assertIsNone(second.get_header('Authorization'))
    def test_redirect_error_does_not_disclose_signed_url(self):
        err=urllib.error.HTTPError('https://api.github.com/test',302,'redirect',
                                  {'Location':'https://codeload.github.com/test?token=private'},io.BytesIO())
        opener=Mock();opener.open.side_effect=[err,Response(b'abcd')]
        with io.BytesIO() as sink,patch('net.urllib.request.build_opener',return_value=opener):
            with self.assertRaises(ValueError) as caught:
                request('GET','https://api.github.com/test',binary=True,sink=sink,limit=3,label='Repository archive')
            self.assertNotIn('private',str(caught.exception))
            self.assertIn('Repository archive',str(caught.exception))
    def test_archive_limit_is_operator_configurable(self):
        gh=GitHub('123',Path('/unused'),['owner/repo'])
        with patch.dict(os.environ,{'SOURCE_MAX_ARCHIVE_MIB':'123'}),patch.object(gh,'call',return_value=10) as call,io.BytesIO() as sink:
            self.assertEqual(gh.download_source('owner/repo','a'*40,sink),10)
            self.assertEqual(call.call_args.kwargs['limit'],123*MIB)
            self.assertIs(call.call_args.kwargs['sink'],sink)
    def test_invalid_limits_fail_closed(self):
        gh=GitHub('123',Path('/unused'),['owner/repo'])
        for value in ('0','-1','unlimited'):
            with self.subTest(value=value),patch.dict(os.environ,{'SOURCE_MAX_ARCHIVE_MIB':value}),patch.object(gh,'call') as call:
                with self.assertRaisesRegex(ValueError,'SOURCE_MAX_ARCHIVE_MIB'):
                    gh.download_source('owner/repo','a'*40,io.BytesIO())
                call.assert_not_called()

class PreparationTests(Fixture):
    def test_failed_download_is_inspectable_and_resumes_same_task(self):
        with patch.object(self.gh,'download_source',side_effect=ValueError('archive limit exceeded')):
            with self.assertRaises(ValueError):self.task()
        failed=self.c.get_task_status('example')
        self.assertEqual(failed['status'],'preparing')
        self.assertEqual(failed['preparation_stage'],'download')
        self.assertEqual(failed['preparation_error'],'archive limit exceeded')
        self.assertEqual(self.gh.prs,{})
        self.assertEqual(list((self.root/'control/source-downloads').iterdir()),[])
        with patch.object(self.gh,'download_source',wraps=self.gh.download_source) as download:
            complete=self.task()
        self.assertEqual(complete['status'],'ready')
        self.assertEqual(complete['base_sha'],failed['base_sha'])
        self.assertEqual(download.call_args.args[1],failed['base_sha'])
        self.assertIsNone(complete['preparation_error'])
    def test_worker_failure_does_not_discard_preparing_task(self):
        with patch.object(self.w,'prepare_archive',side_effect=ValueError('expanded limit exceeded')):
            with self.assertRaises(ValueError):self.task()
        failed=self.c.get_task_status('example')
        self.assertEqual(failed['preparation_stage'],'worker_import')
        self.assertGreater(failed['source_archive_bytes'],0)
        self.assertEqual(list((self.root/'control/source-downloads').iterdir()),[])
        self.assertEqual(self.task()['status'],'ready')
    def test_large_untouched_file_is_imported_but_not_exported(self):
        data=b'x'*(9*MIB)
        t=self.w.repos.prepare_archive('large',io.BytesIO(archive({'large.dat':data,'README.md':'Original'})))
        p=Path(t['path']);self.assertEqual((p/'large.dat').stat().st_size,len(data))
        (p/'new.md').write_text('document\n')
        diff=self.w.repos.changes('large',t['snapshot_sha'])
        self.assertEqual([x['path'] for x in diff['changes']],['new.md'])
        with (p/'large.dat').open('ab') as f:f.write(b'x')
        with self.assertRaises(ValueError):self.w.repos.changes('large',t['snapshot_sha'])
    def test_file_limit_includes_path_and_cleans_partial_import(self):
        self.w.repos.max_source_file=5
        with self.assertRaisesRegex(ValueError,'large.dat.*SOURCE_MAX_FILE_MIB'):
            self.w.repos.prepare_archive('large',io.BytesIO(archive({'large.dat':'123456'})))
        taskdir=self.w.repos.path('large').parent
        self.assertEqual(list(taskdir.iterdir()),[])
    def test_expanded_limit_remains_enforced(self):
        self.w.repos.max_source_total=5
        with self.assertRaisesRegex(ValueError,'SOURCE_MAX_TOTAL_MIB'):
            self.w.repos.prepare_archive('large',io.BytesIO(archive({'a':'123','b':'456'})))
    def test_compressed_limit_remains_enforced(self):
        self.w.repos.max_archive=10
        with self.assertRaisesRegex(ValueError,'SOURCE_MAX_ARCHIVE_MIB'):
            self.w.repos.prepare_archive('large',io.BytesIO(archive({'a':'123'})))
    def test_large_limit_does_not_enable_symlinks_or_traversal(self):
        for entries in ({'../escape':'bad'},{'link':None}):
            with self.subTest(entries=entries),self.assertRaises(ValueError):
                self.w.repos.prepare_archive('large',io.BytesIO(archive(entries)))
    def test_default_branch_snapshot_uses_diff_free_git_api(self):
        self.task()
        self.assertFalse(any(path.startswith('/commits/') for _,path,_ in self.gh.calls))
        self.assertTrue(any(path.startswith('/git/commits/') for _,path,_ in self.gh.calls))

class LargeHTTPTests(unittest.TestCase):
    @contextlib.contextmanager
    def worker(self,tmp,**extra):
        with socket.socket() as s:
            s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        env={**os.environ,'WORKER_PORT':str(port),'WORKSPACE_ROOT':str(tmp/'workspace'),
             'JOB_STATE_DIR':str(tmp/'jobs'),'PYTHONDONTWRITEBYTECODE':'1',**extra}
        proc=subprocess.Popen([sys.executable,str(ROOT/'worker/server.py')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        w=Worker(f'http://127.0.0.1:{port}')
        try:
            for _ in range(120):
                try:
                    if w.health()['ok']:break
                except OSError:pass
                if proc.poll() is not None:self.fail('Worker failed: '+proc.stderr.read().decode())
                time.sleep(.025)
            else:self.fail('Worker unreachable')
            yield w
        finally:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
            proc.stderr.close()
    def test_real_binary_upload_larger_than_old_48_mib_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp=Path(directory);large=tmp/'large.dat';block=os.urandom(MIB)
            with large.open('wb') as out:
                for _ in range(49):out.write(block)
            archive_path=tmp/'source.tar.gz'
            # Compression level zero makes this a real >48 MiB transfer, not a tiny zip-bomb fixture.
            with tarfile.open(archive_path,'w:gz',compresslevel=0) as tar:
                tar.add(large,arcname='owner-repo-sha/large.dat')
            self.assertGreater(archive_path.stat().st_size,48*MIB)
            with self.worker(tmp) as w,archive_path.open('rb') as source:
                t=w.prepare_archive('large-http',source)
                p=Path(t['path']);self.assertEqual((p/'large.dat').stat().st_size,49*MIB)
                with (p/'large.dat').open('rb') as f:
                    for _ in range(49):self.assertEqual(f.read(MIB),block)
                w.call('write_file',path=str(p/'note.md'),content='ready\n')
                diff=w.call('changes',task_id='large-http',snapshot_sha=t['snapshot_sha'])
                self.assertEqual([x['path'] for x in diff['changes']],['note.md'])
                self.assertEqual(list((tmp/'source-imports').iterdir()),[])
                # Repeating the upload must not overwrite the existing working copy.
                again=w.prepare_archive('large-http',source)
                self.assertTrue(again['reused']);self.assertEqual((p/'note.md').read_text(),'ready\n')
    def test_real_http_file_limit_error_and_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp=Path(directory)
            with self.worker(tmp,SOURCE_MAX_FILE_MIB='1') as w:
                with self.assertRaisesRegex(RuntimeError,'large.dat.*SOURCE_MAX_FILE_MIB'):
                    w.prepare_archive('retry',io.BytesIO(archive({'large.dat':b'x'*(2*MIB)})))
                self.assertEqual(list((tmp/'source-imports').iterdir()),[])
                t=w.prepare_archive('retry',io.BytesIO(archive({'README.md':'ok'})))
                self.assertEqual((Path(t['path'])/'README.md').read_text(),'ok')

if __name__=='__main__':unittest.main()
