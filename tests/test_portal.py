import concurrent.futures
import json
import sqlite3
import time
from unittest.mock import patch
import pytest
from app import create_app, work_once, build_plan, normalize_email

@pytest.fixture
def app(tmp_path):
    return create_app({'DATABASE':str(tmp_path/'test.sqlite3'),'SECRET_KEY':'test-only', 'TESTING':True,'PREVIEW':True})


def login(client, tid='preview'):
    client.get('/')
    with client.session_transaction() as s:
        s['team_id']=tid
        return s['csrf']


def test_requires_auth_and_csrf(app):
    c=app.test_client()
    assert c.get('/api/status').status_code==401
    assert c.post('/api/activate',json={'repo':'test/app'}).status_code==403
    csrf=login(c)
    assert c.post('/api/activate',json={'repo':'test/app'},headers={'X-CSRF-Token':csrf}).status_code==202


def test_no_team_spoofing_or_command_injection(app):
    c=app.test_client(); csrf=login(c)
    for repo in ['a/b;touch /tmp/x','https://evil.test/a/b','a/$(id)','a/b\n--project=other','../x',42]:
        assert c.post('/api/activate',json={'repo':repo},headers={'X-CSRF-Token':csrf}).status_code==400
    r=c.post('/api/activate',json={'repo':'test/app','team_id':'other','prefix':'owned'},headers={'X-CSRF-Token':csrf})
    assert r.status_code==202
    for _ in range(6): work_once(app,0)
    body=c.get('/api/status').json
    assert body['team']['prefix']=='demo437'
    assert body['activation']['outputs']['created_in_google_cloud'] is False


def test_job_resumes_and_download_requires_completion(app):
    c=app.test_client(); csrf=login(c)
    assert c.get('/api/handoff').status_code==409
    c.post('/api/activate',json={'repo':'https://github.com/team/app.git'},headers={'X-CSRF-Token':csrf})
    work_once(app,0); work_once(app,0)
    restarted=create_app({**app.config,'DATABASE':app.config['DATABASE']})
    for _ in range(4): assert work_once(restarted,0)
    assert not work_once(restarted,0)
    assert c.get('/api/handoff').json['github_repository']=='team/app'
    assert c.get('/api/status').json['activation']['step']==6


def test_parallel_activate_creates_one_job(app):
    def activate(_):
        with app.test_client() as c:
            csrf=login(c)
            return c.post('/api/activate',json={'repo':'team/app'},headers={'X-CSRF-Token':csrf}).status_code
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        codes=list(pool.map(activate,range(8)))
    assert codes.count(202)==1 and codes.count(200)==7
    with app.db() as conn: assert conn.execute('SELECT count(*) FROM activations').fetchone()[0]==1


def test_parallel_workers_and_repository_freeze(app):
    c=app.test_client(); csrf=login(c)
    c.post('/api/activate',json={'repo':'team/app'},headers={'X-CSRF-Token':csrf})
    assert c.post('/api/activate',json={'repo':'other/repo'},headers={'X-CSRF-Token':csrf}).status_code==409
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _:work_once(app,0.03),range(6)))
    step=c.get('/api/status').json['activation']['step']
    assert 1<=step<=6
    with app.db() as conn:
        assert conn.execute("SELECT count(*) FROM events WHERE action='preview_step'").fetchone()[0]==step


def test_different_team_data_not_exposed(app):
    with app.db() as conn:
        conn.execute("INSERT INTO teams VALUES('second','Other','other@gmail.com','other123',1,NULL,0)")
    c=app.test_client(); csrf=login(c)
    c.post('/api/activate',json={'repo':'team/app'},headers={'X-CSRF-Token':csrf})
    with c.session_transaction() as s:s['team_id']='second'
    result=c.get('/api/status?team_id=preview').json
    assert result['team']['name']=='Other' and result['activation'] is None
    assert result['history']==[]
    assert c.get('/api/handoff?team_id=preview').status_code==409
    with app.db() as conn:conn.execute("UPDATE teams SET enabled=0 WHERE id='second'")
    assert c.get('/api/status').status_code==401


def test_expired_worker_lease_recovered(app):
    c=app.test_client(); csrf=login(c)
    c.post('/api/activate',json={'repo':'team/app'},headers={'X-CSRF-Token':csrf})
    with app.db() as conn:conn.execute("UPDATE activations SET status='running',lease_until=?",(int(time.time())-1,))
    assert work_once(app,0)
    step=c.get('/api/status').json['activation']['step']
    assert 1<=step<=6
    with app.db() as conn:
        assert conn.execute("SELECT count(*) FROM events WHERE action='preview_step'").fetchone()[0]==step


def test_security_headers_and_escape(app):
    c=app.test_client();login(c)
    with app.db() as conn:conn.execute("UPDATE teams SET name='<script>alert(1)</script>' WHERE id='preview'")
    r=c.get('/')
    assert b'<script>alert(1)</script>' not in r.data
    assert r.headers['Cache-Control']=='no-store'
    assert "frame-ancestors 'none'" in r.headers['Content-Security-Policy']


def test_preview_disabled_in_production(tmp_path):
    a=create_app({'DATABASE':str(tmp_path/'prod.sqlite3'),'SECRET_KEY':'test','TESTING':True,'PREVIEW':False,'BASE_URL':'https://example.test'})
    c=a.test_client();c.get('/')
    with c.session_transaction() as s:csrf=s['csrf'];s['team_id']='preview'
    assert c.post('/preview/login',headers={'X-CSRF-Token':csrf}).status_code==404
    assert c.get('/auth/callback').status_code==400
    assert c.get('/api/status').status_code==401
    with a.db() as conn:conn.execute("INSERT INTO teams VALUES('real','Team','real@gmail.com','real123',1,NULL,0)")
    with c.session_transaction() as s:s['team_id']='real'
    assert c.post('/api/activate',json={'repo':'team/app'},headers={'X-CSRF-Token':csrf}).status_code==503
    assert c.get('/api/status').json['activation'] is None


def test_oidc_rejects_replay_and_unverified_email(tmp_path):
    a=create_app({'DATABASE':str(tmp_path/'p.sqlite3'),'SECRET_KEY':'test','TESTING':True,'PREVIEW':False,'BASE_URL':'https://example.test'})
    import hashlib
    c=a.test_client();c.get('/')
    with a.db() as conn:
        conn.execute('INSERT INTO oauth_states VALUES(?,?)',(hashlib.sha256(b'state').hexdigest(),int(time.time())+60))
    with patch('authlib.integrations.flask_client.apps.FlaskOAuth2App.authorize_access_token', return_value={'userinfo':{'email':'x@gmail.com','sub':'id','email_verified':False}}):
        assert c.get('/auth/callback?state=state').status_code==403
        assert c.get('/auth/callback?state=state').status_code==400


def test_normalization_and_roster():
    from import_roster import parse_roster
    assert normalize_email('\u200e A.B+class@gmail.com ')=='a.b+class@gmail.com'
    text='ignored\f,group,name,id,email\n0,Test,Contact,001,\u200fx@gmail.com\n'
    rows=parse_roster(text)
    assert len(rows)==1 and rows[0]['email']=='x@gmail.com'
    with pytest.raises(ValueError):parse_roster(text+'1,Other,Name,002,x@gmail.com\n')
    with pytest.raises(ValueError):parse_roster(text.replace('x@gmail.com','x@gmail.com / y@gmail.com'))


def test_invalid_prefix_rejected():
    with pytest.raises(ValueError):build_plan({'prefix':'a;rm'},'team/app')


def test_handoff_matches_original_kit_variable_names(app):
    c=app.test_client();csrf=login(c)
    c.post('/api/activate',json={'repo':'team/app'},headers={'X-CSRF-Token':csrf})
    for _ in range(6):work_once(app,0)
    handoff=c.get('/api/handoff').json
    resources=handoff['resources']
    assert resources['sql_connection_name']=='cpe-se-course-2026:asia-southeast1:demo437-pg'
    assert resources['image_repository']=='asia-southeast1-docker.pkg.dev/cpe-se-course-2026/demo437/demo437'
    assert resources['admin_password_secret']=='demo437-admin-password'
    assert resources['demo_password_secret']=='demo437-demo-password'
    assert resources['database_user']=='demo437'
    assert handoff['created_in_google_cloud'] is False
    variables=handoff['github_variables']
    assert set(variables)=={'GCP_PROJECT_ID','GCP_REGION','WIF_PROVIDER','WIF_SERVICE_ACCOUNT'}
    assert variables['GCP_PROJECT_ID']=='cpe-se-course-2026'
    assert c.get('/api/status').json['activation']['outputs']['github_variables']==variables


def test_retired_config_download_is_not_served(app):
    c=app.test_client()
    assert c.get('/api/student-kit').status_code==401
    login(c)
    assert c.get('/api/student-kit').status_code==410
    assert c.get('/api/student-guide').status_code==410
