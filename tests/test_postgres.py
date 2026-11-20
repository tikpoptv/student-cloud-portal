"""Run against the disposable local PostgreSQL container, never a hosted database."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
import pytest

@pytest.fixture
def postgres_app(tmp_path):
    url=os.environ.get('PORTAL_TEST_POSTGRES')
    if not url:pytest.skip('Set PORTAL_TEST_POSTGRES to a disposable local PostgreSQL database')
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict,make_conninfo
    params=conninfo_to_dict(url)
    assert params.get('host') in ('127.0.0.1','localhost'), 'Integration tests are local only'
    schema='portal_test_'+uuid.uuid4().hex
    with psycopg.connect(url,autocommit=True) as c:c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    from app import create_app
    config={'DATABASE':str(tmp_path/'unused.sqlite3'),'DATABASE_URL':make_conninfo(url,options='-c search_path='+schema),'PREVIEW':True,'AUTH_MODE':'demo','SECRET_KEY':'test','TESTING':True}
    try:yield create_app(config),config
    finally:
        with psycopg.connect(url,autocommit=True) as c:c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))

def test_postgres_activation_concurrency_and_restart(postgres_app):
    from app import create_app,work_once
    a,config=postgres_app
    def activate():
        c=a.test_client();c.get('/')
        with c.session_transaction() as s:s['team_id']='preview';csrf=s['csrf']
        return c.post('/api/activate',json={'repo':'test/app'},headers={'X-CSRF-Token':csrf}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _:activate(),range(2)))==[200,202]
    with a.db() as c:assert len(c.execute('SELECT * FROM activations').fetchall())==1
    for _ in range(6):assert work_once(a,0)
    restarted=create_app(config)
    with restarted.db() as c:
        row=c.execute("SELECT * FROM activations WHERE team_id=?",('preview',)).fetchone()
        assert row['status']=='ready' and row['step']==6
        assert len(c.execute('SELECT * FROM events').fetchall())==7

def test_postgres_admin_dashboard_and_credit_observation(postgres_app):
    import time
    from unittest.mock import patch
    a,_=postgres_app;a.config['TA_EMAILS']='ta@gmail.com'
    with a.db() as db:db.execute("INSERT INTO teams VALUES('real','Real team','real@gmail.com','real123',1,NULL,0)")
    client=a.test_client();client.get('/')
    with client.session_transaction() as s:s.update(admin_email='ta@gmail.com',admin_sub='verified-test-sub');csrf=s['csrf']
    with patch('admin_dashboard.collect_cloud',return_value={'services':[],'jobs':[],'sql':[],'registry':[],'requests':{},'collected_at':123,'errors':{}}):
        result=client.get('/api/admin/overview');assert result.status_code==200
        assert result.json['teams'][0]['name']=='Real team'
        r=client.post('/api/admin/credit-observation',json={'amount':'123.45','currency':'USD','observed_at':int(time.time())},headers={'X-CSRF-Token':csrf})
        assert r.status_code==200
        assert client.get('/api/admin/overview').json['credit_observation']['amount']=='123.45'

def test_postgres_ta_membership_and_same_group_google_login(postgres_app):
    from app import create_app
    from tests.test_oauth_setup import callback
    a,config=postgres_app
    a=create_app({**config,'AUTH_MODE':'google','TA_EMAILS':'ta@gmail.com'})
    with a.db() as db:db.execute("INSERT INTO teams VALUES('real','Real team','real@gmail.com','real123',1,NULL,0)")
    client=a.test_client();assert callback(client,a,'ta@gmail.com').status_code==302
    with client.session_transaction() as s:headers={'X-CSRF-Token':s['csrf']}
    assert client.post('/api/admin/teams/real/members',json={'email':'partner@gmail.com','confirm':True},headers=headers).status_code==201
    assert client.post('/api/admin/teams',json={'name':'New team','email':'new.team@gmail.com'},headers=headers).status_code==201
    assert client.post('/api/admin/teams',json={'name':'Duplicate','email':'partner@gmail.com'},headers=headers).status_code==409
    assert callback(client,a,'partner@gmail.com','partner-sub').status_code==302
    assert client.get('/api/status').json['team']['prefix']=='real123'
    with a.db() as db:
        assert db.execute("SELECT google_sub FROM team_members WHERE email='partner@gmail.com'").fetchone()['google_sub']=='partner-sub'
        assert db.execute("SELECT google_sub FROM teams WHERE id='real'").fetchone()['google_sub'] is None

def test_postgres_resources_without_github_and_later_attach(postgres_app):
    from app import create_app
    from tests.test_oauth_setup import callback
    from unittest.mock import patch
    a,config=postgres_app
    a=create_app({**config,'PREVIEW':False,'AUTH_MODE':'google','BASE_URL':'https://example.test','LIVE_ACTIVATION_ENABLED':True,'WORKER_URL':'https://worker.test','ACTIVATE_MIN_INTERVAL':0})
    with a.db() as db:db.execute("INSERT INTO teams VALUES('real','Real team','real@gmail.com','real123',1,NULL,0)")
    c=a.test_client();assert callback(c,a,'real@gmail.com').status_code==302
    with c.session_transaction() as s:headers={'X-CSRF-Token':s['csrf']}
    with patch('activation.enqueue'),patch('activation.github_identity') as github:
        assert c.post('/api/activate',json={'resources_only':True},headers=headers).status_code==202
        github.assert_not_called()
    with a.db() as db:
        row=db.execute("SELECT * FROM activation_runtime WHERE team_id='real'").fetchone()
        assert row['repository_id']=='resources:real'
        db.execute("UPDATE activations SET status='ready',step=6 WHERE team_id='real'")
        db.execute('INSERT INTO repo_reviews VALUES(?,?,?,?)',('real','owner/repo','{"status":"prepared","repo":"owner/repo"}',0))
        db.execute('INSERT INTO repo_snapshots VALUES(?,?,?)',('real','a'*40,'{}'))
    with patch('activation.enqueue'),patch('activation.github_identity',return_value={'repo':'owner/repo','repository_id':'123','owner_id':'456'}):
        assert c.post('/api/activate',json={'repo':'owner/repo'},headers=headers).status_code==202
    with a.db() as db:
        row=db.execute("SELECT * FROM activations WHERE team_id='real'").fetchone();assert row['step']==6 and row['status']=='ready' and row['github_link_status']=='queued' and row['repo']=='owner/repo'


def test_postgres_chat_and_push_flow(postgres_app):
    """RETURNING, ON CONFLICT and the correlated unread queries must behave on PostgreSQL, not only SQLite."""
    from unittest.mock import patch
    from app import create_app
    from tests.test_oauth_setup import callback
    a,config=postgres_app
    a=create_app({**config,'AUTH_MODE':'google','TA_EMAILS':'ta@gmail.com','VAPID_PRIVATE_KEY':'p'*43,'VAPID_PUBLIC_KEY':'K'*87,'VAPID_SUBJECT':'mailto:ta@example.org'})
    with a.db() as db:db.execute("INSERT INTO teams VALUES('real','Real team','real@gmail.com','real123',1,NULL,0)")
    s=a.test_client();assert callback(s,a,'real@gmail.com').status_code==302
    ta=a.test_client();assert callback(ta,a,'ta@gmail.com').status_code==302
    def h(c):
        with c.session_transaction() as sess:return {'X-CSRF-Token':sess['csrf']}
    sub={'subscription':{'endpoint':'https://web.push.apple.com/ta1','keys':{'p256dh':'B'*87,'auth':'a'*22}}}
    assert ta.post('/api/push/subscribe',json=sub,headers=h(ta)).status_code==201
    assert ta.post('/api/push/subscribe',json=sub,headers=h(ta)).status_code==201  # upsert, not a duplicate-key error
    with patch('chat.webpush') as push:
        assert s.post('/api/chat',json={'body':'สวัสดี'},headers=h(s)).status_code==201
        assert s.post('/api/chat',json={'body':'สอง'},headers=h(s)).status_code in (201,429)
    assert push.call_count>=1
    assert ta.get('/api/admin/chat/summary').json['unread_total']>=1
    assert [m['body'] for m in ta.get('/api/admin/chat/real').json['messages']][0]=='สวัสดี'
    assert ta.get('/api/admin/chat/summary').json['unread_total']==0
    with patch('chat.webpush'):
        assert ta.post('/api/admin/chat/real',json={'body':'รับทราบ'},headers=h(ta)).status_code==201
    assert s.get('/api/chat/unread').json['unread']==1
    assert s.get('/api/chat').json['messages'][-1]['sender']=='TA'
    assert s.get('/api/chat/unread').json['unread']==0
    with a.db() as db:assert db.execute('SELECT COUNT(*) n FROM push_subscriptions').fetchone()['n']==1
