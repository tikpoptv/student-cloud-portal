from pathlib import Path
import json
import os
import subprocess
import zipfile
import io
import requests
from requests.structures import CaseInsensitiveDict
from unittest.mock import patch
import pytest
from app import create_app
import repo_review
from repo_review import inspect_files,normalize_repo,fetch_snapshot,get_bytes

REF=Path(__file__).parents[1]/'reference-kit'

def fixture_files():
    return {'deploy/deploy.sh':(REF/'deploy.sh').read_text(),
            'deploy/release.sh':(REF/'release.sh').read_text(),
            '.github/workflows/deploy.yml':(REF/'deploy.yml').read_text(),
            '.github/workflows/ci-docker.yml':'name: CI\n',
            'deploy/smoke_test.py':'# student smoke test\n', 'Dockerfile':'FROM sample\n',
            'deploy/teardown.sh':'#!/usr/bin/env bash\necho old\n',
            'deploy/tests/test_deploy_stub.sh':'# old infra tests\n',
            'deploy/tests/test_release_stub.sh':'#!/usr/bin/env bash\necho toktickit\n'}


def test_preserves_stack_and_ci_and_changes_only_original_paths(tmp_path):
    files=fixture_files();files['deploy/deploy.sh']=files['deploy/deploy.sh'].replace('--port 3000','--port 8080').replace('npx prisma migrate deploy && npm run prisma:seed','python -m alembic upgrade head')
    report=inspect_files('team/app','a'*40,files,'demo437')
    assert report['status']=='prepared',report
    changed={c['path']:c['after'] for c in report['changes']}
    assert '.github/workflows/ci-docker.yml' not in changed
    assert set(changed).issubset(files)
    assert not any('course-app' in p for p in changed)
    script=changed['deploy/deploy.sh']
    assert '--port 8080' in script and 'python -m alembic upgrade head' in script
    assert 'gcloud builds submit' not in script
    assert 'run_cmd gcloud run jobs update' in script
    assert 'run_cmd gcloud run services update' in script
    assert 'run_cmd gcloud sql' not in script and 'run_cmd gcloud services enable' not in script
    assert 'PROJECT_ID="${PROJECT_ID:-cpe-se-course-2026}"' in script
    assert 'SECRET_DB_URL="demo437-database-url"' in script
    assert 'before' not in report['findings'][0]
    file=tmp_path/'deploy.sh';file.write_text(script)
    subprocess.run(['bash','-n',str(file)],check=True)
    fake=tmp_path/'bin';fake.mkdir()
    for command in ['gcloud','docker','git']:
        exe=fake/command;exe.write_text('#!/bin/sh\nexit 99\n');exe.chmod(0o755)
    result=subprocess.run(['bash',str(file)],env={**os.environ,'PATH':str(fake)+':'+os.environ['PATH'],'DRY_RUN':'1'},capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert '[DRY_RUN]' in result.stdout
    blocked=subprocess.run(['bash',str(file)],env={**os.environ,'PATH':str(fake)+':'+os.environ['PATH'],'DRY_RUN':'0'},capture_output=True,text=True)
    assert blocked.returncode!=0 and 'preview' in blocked.stderr
    assert 'Verify course handoff readiness' in changed['.github/workflows/deploy.yml']
    for gate in ['needs: test','id-token: write','environment: demo','cancel-in-progress: false']:
        assert gate in changed['.github/workflows/deploy.yml']


def test_live_migration_failure_prevents_service_update(tmp_path):
    report=inspect_files('team/app','a'*40,fixture_files(),'demo437',preview=False)
    assert report['status']=='prepared'
    script=next(c['after'] for c in report['changes'] if c['path']=='deploy/deploy.sh')
    path=tmp_path/'deploy.sh';path.write_text(script)
    bin=tmp_path/'bin';bin.mkdir();log=tmp_path/'calls'
    scripts={'git':'''#!/bin/sh
if [ "$1" = branch ]; then echo main; else echo aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; fi
''','docker':'#!/bin/sh\necho "docker $*" >> "$CALLS"\n',
    'gcloud':'''#!/bin/sh
echo "gcloud $*" >> "$CALLS"
if [ "$1 $2 $3" = "artifacts docker images" ]; then echo "asia-southeast1-docker.pkg.dev/cpe-se-course-2026/demo437/demo437@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"; fi
if [ "$1 $2 $3" = "run jobs execute" ]; then exit 17; fi
'''}
    for name,text in scripts.items():
        p=bin/name;p.write_text(text);p.chmod(0o755)
    result=subprocess.run(['bash',str(path)],env={**os.environ,'PATH':str(bin)+':'+os.environ['PATH'],'CALLS':str(log),'DRY_RUN':'0'},capture_output=True,text=True)
    assert result.returncode!=0
    called=log.read_text()
    assert 'run jobs execute' in called
    assert 'run services update ' not in called and 'update-traffic' not in called
    assert 'add-iam' not in called and 'services enable' not in called


def test_unknown_layout_never_generates_partial_patch():
    files=fixture_files();files['deploy/deploy.sh']=files['deploy/deploy.sh'].replace('# 9. Build & Push Unified Container Image via Cloud Build','# custom workflow')
    r=inspect_files('team/app','a'*40,files,'demo437')
    assert r['status']=='needs_review' and not r['changes']
    del files['Dockerfile']
    assert not inspect_files('team/app','a'*40,files,'demo437')['changes']
    files=fixture_files();files['deploy/deploy.sh']+='\nDB="postgresql://user:private@host/db"\n'
    with pytest.raises(ValueError):inspect_files('team/app','a'*40,files,'demo437')


def test_remote_urls_are_fixed_and_commit_pinned():
    calls=[]
    def fetch(url,limit,**kw):
        calls.append(url)
        if url.startswith('https://api.github.com/'):return b'b'*40
        return b'# file\n'
    with patch('repo_review.get_bytes',side_effect=fetch):
        sha,files=fetch_snapshot('owner/repo')
    assert sha=='b'*40
    assert all('/'+sha+'/' in url for url in calls if 'raw.githubusercontent' in url)
    for repo in ['http://localhost/a/b','https://evil.test/a/b','a/b?ref=x','a/../../foo','a/b\nheader:foo']:
        with pytest.raises(ValueError):normalize_repo(repo)


def test_review_endpoints_are_scoped_and_download_patch_not_config(tmp_path):
    app=create_app({'DATABASE':str(tmp_path/'db'),'SECRET_KEY':'test','TESTING':True,'PREVIEW':True})
    c=app.test_client();c.get('/')
    assert c.get('/api/repo-review').status_code==401
    with c.session_transaction() as s:s['team_id']='preview';csrf=s['csrf']
    with patch('repo_review.fetch_snapshot',return_value=('a'*40,fixture_files())):
        r=c.post('/api/repo-review',json={'repo':'https://github.com/team/app'},headers={'X-CSRF-Token':csrf})
    assert r.status_code==200 and r.json['review']['status']=='prepared',r.json
    assert c.get('/api/repo-patch').status_code==200
    archive=zipfile.ZipFile(io.BytesIO(c.get('/api/repo-patch?format=zip').data))
    assert not any('course-app' in p or 'course-team.json' in p for p in archive.namelist())
    assert 'lab5-demo437.patch' in archive.namelist()
    with app.db() as db:db.execute("INSERT INTO teams VALUES('other','Other','other@gmail.com','other123',1,NULL,0)")
    with c.session_transaction() as s:s['team_id']='other'
    assert c.get('/api/repo-review?team_id=preview').json=={'review':None}
    assert c.get('/api/repo-patch?team_id=preview').status_code==409


def test_patch_applies_to_exact_snapshot_and_ci_remains_unchanged(tmp_path):
    from repo_review import patch_bytes
    files=fixture_files();report=inspect_files('team/app','a'*40,files,'demo437')
    for p,text in files.items():
        dest=tmp_path/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(text)
    subprocess.run(['git','init','--quiet',str(tmp_path)],check=True)
    p=tmp_path/'proposal.patch';p.write_bytes(patch_bytes(report))
    subprocess.run(['git','apply','--check',str(p)],cwd=tmp_path,check=True,capture_output=True)
    subprocess.run(['git','apply',str(p)],cwd=tmp_path,check=True,capture_output=True)
    assert (tmp_path/'.github/workflows/ci-docker.yml').read_text()==files['.github/workflows/ci-docker.yml']
    result=subprocess.run(['bash','deploy/tests/test_deploy_stub.sh'],cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    for f in ['deploy/deploy.sh','deploy/release.sh','deploy/teardown.sh']:
        subprocess.run(['bash','-n',str(tmp_path/f)],check=True)


class FakeRes:
    def __init__(self,status=200,chunks=(b'x',),headers=None):
        self.status_code=status;self.chunks=chunks;self.headers=CaseInsensitiveDict(headers or {})
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def iter_content(self,n):return iter(self.chunks)


def fake_get(responder,calls):
    def get(url,**kw):
        calls.append((url,kw))
        return responder(url)
    return get


def test_sha_lookup_uses_sha_media_type_and_small_limit():
    calls=[]
    def responder(url):
        if url.startswith('https://api.github.com/'):return FakeRes(chunks=[b'c'*40])
        return FakeRes(404)
    with patch('repo_review.requests.get',side_effect=fake_get(responder,calls)):
        sha,files=fetch_snapshot('owner/repo')
    assert sha=='c'*40 and files=={}
    url,kw=calls[0]
    assert url=='https://api.github.com/repos/owner/repo/commits/main'
    assert kw['headers']['Accept']=='application/vnd.github.sha'


def test_oversized_commit_details_body_is_not_read_as_sha():
    big=[b'{"files":"'+b'a'*16000]+[b'a'*16384]*22  # ~357 KB commit details
    def responder(url):return FakeRes(chunks=big)
    with patch('repo_review.requests.get',side_effect=fake_get(responder,[])):
        with pytest.raises(ValueError) as e:fetch_snapshot('owner/repo')
    assert 'อ่านข้อมูล commit' in str(e.value) and 'ไฟล์ใหญ่เกิน' not in str(e.value)


def test_student_file_too_large_keeps_file_message():
    with patch('repo_review.requests.get',return_value=FakeRes(chunks=[b'a'*16384]*10)):
        with pytest.raises(ValueError,match='ไฟล์ใหญ่เกิน'):get_bytes('https://raw.githubusercontent.com/o/r/'+'a'*40+'/Dockerfile',150000)


def test_non_hex_sha_rejected():
    with patch('repo_review.requests.get',return_value=FakeRes(chunks=[b'{"sha":"x"}'])):
        with pytest.raises(ValueError,match='ยืนยัน Git commit'):fetch_snapshot('owner/repo')


@pytest.mark.parametrize('status,headers,rate',[
    (429,{},True),(403,{'X-RateLimit-Remaining':'0'},True),(403,{'Retry-After':'30'},True),
    (403,{'X-RateLimit-Remaining':'12'},False),(403,{},False)])
def test_403_only_rate_limit_when_signalled(status,headers,rate):
    with patch('repo_review.requests.get',return_value=FakeRes(status,headers=headers)):
        with pytest.raises(ValueError) as e:get_bytes('https://api.github.com/x',10)
    assert ('จำกัดการอ่าน' in str(e.value))==rate


def test_token_only_sent_to_api_github(monkeypatch):
    seen={}
    def run(url):
        with patch('repo_review.requests.get',side_effect=lambda u,**kw:(seen.__setitem__('h',kw['headers']),FakeRes())[1]):
            get_bytes(url,100)
        return seen['h']
    monkeypatch.delenv('GITHUB_API_TOKEN',raising=False)
    assert 'Authorization' not in run('https://api.github.com/repos/o/r/commits/main')
    monkeypatch.setenv('GITHUB_API_TOKEN','tok123')
    assert run('https://api.github.com/repos/o/r/commits/main')['Authorization']=='Bearer tok123'
    assert 'Authorization' not in run('https://raw.githubusercontent.com/o/r/sha/Dockerfile')
    assert 'Authorization' not in run('https://api.github.com.evil.test/x')
    with patch('repo_review.requests.get',return_value=FakeRes(500)):
        with pytest.raises(ValueError) as e:get_bytes('https://api.github.com/x',10)
    assert 'tok123' not in str(e.value)


def test_overall_deadline_stops_slow_drip():
    t=[0.0]
    def slow():
        for _ in range(100):
            t[0]+=1;yield b'a'
    class Slow(FakeRes):
        def iter_content(self,n):return slow()
    with patch('repo_review.time.monotonic',side_effect=lambda:t[0]),\
         patch('repo_review.requests.get',return_value=Slow()):
        with pytest.raises(ValueError,match='ช้าเกิน'):fetch_snapshot('owner/repo')
    assert t[0]<60


def test_deadline_checked_between_files():
    t=[0.0]
    def responder(url):
        t[0]+=30
        return FakeRes(chunks=[b'd'*40]) if url.startswith('https://api.github.com/') else FakeRes(chunks=[b'x'])
    with patch('repo_review.time.monotonic',side_effect=lambda:t[0]),\
         patch('repo_review.requests.get',side_effect=fake_get(responder,[])):
        with pytest.raises(ValueError,match='ช้าเกิน'):fetch_snapshot('owner/repo')


@pytest.mark.parametrize('repo',['a/..','a/.','a/../','owner/..'])
def test_dot_segments_rejected(repo):
    with pytest.raises(ValueError):normalize_repo(repo)


@pytest.mark.parametrize('status',[301,302,307,308])
def test_redirect_gives_moved_repo_message(status):
    with patch('repo_review.requests.get',return_value=FakeRes(status)):
        with pytest.raises(ValueError,match='ย้ายหรือเปลี่ยนชื่อ'):fetch_snapshot('owner/repo')


@pytest.mark.parametrize('value',[
    'owner/repo','https://github.com/owner/repo','github.com/owner/repo','http://github.com/owner/repo','www.github.com/owner/repo',
    'https://www.github.com/owner/repo/','https://github.com/owner/repo.git','github.com/owner/repo/tree/main','https://github.com/owner/repo/issues/3',
    'https://github.com/owner/repo?tab=readme-ov-file','https://github.com/owner/repo#readme','git@github.com:owner/repo.git','  GitHub.com/owner/repo  ',
])
def test_pasted_github_links_normalize_to_owner_repo(value):
    assert normalize_repo(value)=='owner/repo'


@pytest.mark.parametrize('value',[
    'github.com.evil.test/owner/repo','https://gitlab.com/owner/repo','https://evil.test/github.com/owner/repo','github.com/owner','github.com/','github.com//repo',
    'https://github.com/owner/../repo','github.com/owner/repo\nheader:x','github.com/ow ner/repo','ftp://github.com/owner/repo','git@evil.test:owner/repo.git',
])
def test_other_hosts_and_malformed_links_still_rejected(value):
    with pytest.raises(ValueError):normalize_repo(value)
