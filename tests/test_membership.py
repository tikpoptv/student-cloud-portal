import concurrent.futures,json,time
from unittest.mock import patch
import pytest
from tests.test_admin import app,admin_client
from tests.test_oauth_setup import callback
from membership import process_members
from live_provision import Provisioner,ProvisionError


def auth(c):
 with c.session_transaction() as s:return {'X-CSRF-Token':s['csrf']}


def test_only_ta_can_add_members_or_teams(app):
 c=app.test_client();c.get('/')
 assert c.post('/api/admin/teams',json={'name':'Group X','email':'xxxxxx@gmail.com'},headers=auth(c)).status_code==403
 callback(c,app,'one@gmail.com')
 assert c.post('/api/admin/teams/one/members',json={'email':'x@gmail.com'},headers=auth(c)).status_code==403
 c=admin_client(app)
 assert c.post('/api/admin/teams/one/members',json={'email':'x@gmail.com'}).status_code==403


def test_new_group_is_stable_scoped_and_does_not_create_cloud_resources(app):
 c=admin_client(app)
 with patch('membership.enqueue') as queue:
  r=c.post('/api/admin/teams',json={'name':' New Group ','email':' New.Member@GMAIL.COM ','prefix':'victim','team_id':'one'},headers=auth(c))
  assert r.status_code==201;tid=r.json['team_id'];assert tid!='one' and r.json['prefix']!='victim';queue.assert_not_called()
 assert callback(c,app,'new.member@gmail.com').status_code==302
 data=c.get('/api/status').json;assert data['team']['name']=='New Group' and data['activation'] is None
 with app.db() as db:assert db.execute('SELECT count(*) n FROM activations').fetchone()['n']==0


def test_duplicate_invalid_and_cross_group_emails_rejected(app):
 c=admin_client(app);headers=auth(c)
 for email in ('bad','x@example.com','x@gmail.com\n.evil','ta@gmail.com',None):
  assert c.post('/api/admin/teams/one/members',json={'email':email,'confirm':True},headers=headers).status_code==400
 with app.db() as db:db.execute("INSERT INTO teams VALUES('three','Team Three','third.team@gmail.com','thr123',1,NULL,0)")
 add=lambda team,email:c.post(f'/api/admin/teams/{team}/members',json={'email':email,'confirm':True},headers=headers).status_code
 assert add('one','third.team@gmail.com')==409
 assert add('one','thirdteam@gmail.com')==409
 assert add('one','partner@gmail.com')==201
 assert add('one','partner@gmail.com')==200
 assert add('two','partner@gmail.com')==409
 assert c.post('/api/admin/teams',json={'name':'Group X','email':'partner@gmail.com'},headers=headers).status_code==409


def test_member_login_pins_identity_and_keeps_original_owner(app):
 c=admin_client(app);c.post('/api/admin/teams/one/members',json={'email':'partner@gmail.com','confirm':True},headers=auth(c))
 assert callback(c,app,'partner@gmail.com','partner-sub').status_code==302
 assert c.get('/api/status').json['team']['prefix']=='one123'
 assert b'partner@gmail.com' in c.get('/').data
 assert c.get('/api/admin/overview').status_code==403
 assert callback(c,app,'partner@gmail.com','different-sub').status_code==403
 with app.db() as db:
  assert db.execute("SELECT google_sub FROM teams WHERE id='one'").fetchone()['google_sub'] is None
  db.execute("UPDATE teams SET enabled=0 WHERE id='one'")
 assert c.get('/api/status').status_code==401


def seed_ready(app):
 with app.db() as db:
  now=int(time.time());db.execute("INSERT INTO activations(team_id,repo,mode,status,step,created_at,updated_at) VALUES('one','owner/repo','live','ready',6,?,?)",(now,now))
  db.execute('INSERT INTO activation_runtime VALUES(?,?,?)',('one','1',json.dumps({'identity':{'repo':'owner/repo','repository_id':'1','owner_id':'2'},'operations':{}})))


def test_ready_member_sync_uses_private_queue_and_is_resumable(app):
 app.config['WORKER_URL']='https://worker.test';seed_ready(app);c=admin_client(app)
 with patch('membership.enqueue') as queue:
  r=c.post('/api/admin/teams/one/members',json={'email':'partner@gmail.com','confirm':True},headers=auth(c));assert r.json['cloud_status']=='pending'
  assert queue.call_args.kwargs['kind']=='members'
 with patch('membership.Provisioner') as provision:
  result,code=process_members(app,'one');assert code==200 and result['status']=='ready'
  assert provision.call_args.args[0]['member_emails']==['one@gmail.com','partner@gmail.com']
  provision.return_value.grant_members.assert_called_once()
 assert process_members(app,'one')[1]==200
 with app.db() as db:assert db.execute("SELECT cloud_status FROM team_members").fetchone()['cloud_status']=='ready'


def test_queue_failure_preserves_membership_and_retry(app):
 from live_provision import Pending
 seed_ready(app);c=admin_client(app)
 with patch('membership.enqueue',side_effect=Pending('do not leak')):
  r=c.post('/api/admin/teams/one/members',json={'email':'partner@gmail.com','confirm':True},headers=auth(c));assert r.status_code==201
 assert callback(c,app,'partner@gmail.com').status_code==302
 with patch('membership.Provisioner') as provision:
  provision.return_value.grant_members.side_effect=RuntimeError('secret-password')
  result,code=process_members(app,'one');assert code==503 and 'secret-password' not in json.dumps(result)
 with app.db() as db:assert 'secret-password' not in db.execute('SELECT cloud_error FROM team_members').fetchone()['cloud_error']


def test_grants_check_all_ownership_before_any_mutation_and_never_grant_admin():
 calls=[];team={'id':'one','prefix':'one123','email':'one@gmail.com','member_emails':['one@gmail.com','partner@gmail.com']}
 class API:
  def request(self,method,url,body=None,**kwargs):
   calls.append((method,url,body))
   if url.endswith(':getIamPolicy'):return {'bindings':[],'etag':'v1'}
   if method=='GET':
    if '/views/' in url or '/serviceAccounts/' in url:return {'description':'CPE334 portal group:one;prefix:one123;v1'}
    return {'labels':{'cpe334-team':'one'},'settings':{'userLabels':{'cpe334-team':'one'}}}
   return {}
 w=Provisioner(team,{}, {},lambda _:None,API());w.grant_members()
 mutations=[(u,b) for m,u,b in calls if u.endswith(':setIamPolicy')]
 assert len(mutations)==18  # 8 group grants + accessor and versionAdder on each of the 5 secret slots
 encoded=json.dumps(mutations);assert 'partner@gmail.com' in encoded and 'roles/owner' not in encoded and 'roles/editor' not in encoded
 assert 'database-url' not in encoded and 'database-password' not in encoded
 for url,body in mutations:
  for b in body['policy']['bindings']:
   if b['role']=='roles/cloudsql.client':assert "instances/one123-pg" in b['condition']['expression']
 calls.clear()
 class Foreign(API):
  def request(self,m,u,body=None,**kw):
   if '/views/' in u and m=='GET':return {'description':'other group'}
   return super().request(m,u,body,**kw)
 with pytest.raises(ProvisionError):Provisioner(team,{}, {},lambda _:None,Foreign()).grant_members()
 assert not any(u.endswith(':setIamPolicy') for m,u,b in calls)


def test_immediate_worker_dispatch_does_not_overwrite_completed_permissions(app):
 seed_ready(app);c=admin_client(app)
 def dispatch(*args,**kwargs):
  with patch('membership.Provisioner'):
   assert process_members(app,'one')[1]==200
 with patch('membership.enqueue',side_effect=dispatch):
  assert c.post('/api/admin/teams/one/members',json={'email':'partner@gmail.com','confirm':True},headers=auth(c)).status_code==201
 with app.db() as db:assert db.execute("SELECT cloud_status FROM team_members WHERE email='partner@gmail.com'").fetchone()['cloud_status']=='ready'


# ---- hardening: validation, per-member fallback, confirm, removal, identity, activation states ----
import os,uuid
from live_provision import CloudError,Pending

def add(c,team,email,confirm=True,**extra):
 return c.post(f'/api/admin/teams/{team}/members',json={'email':email,'confirm':confirm,**extra},headers=auth(c))

def statuses(app):
 with app.db() as db:return {r['email']:(r['cloud_status'],r['cloud_error']) for r in db.execute('SELECT email,cloud_status,cloud_error FROM team_members').fetchall()}

def test_gmail_local_part_rules_reject_characters_iam_would_refuse(app):
 c=admin_client(app)
 for bad in ('abcde@gmail.com','a'*31+'@gmail.com','abc{d}ef@gmail.com','abc|defg@gmail.com',"abc'defg@gmail.com",'abc/defg@gmail.com','abcdef+tag@gmail.com','.abcdef@gmail.com','abcdef.@gmail.com','abc..def@gmail.com','abc_def@gmail.com'):
  assert add(c,'one',bad).status_code==400,bad
 assert add(c,'one','Abc.Def9@GMAIL.com').status_code==201
 assert 'abc.def9@gmail.com' in statuses(app)


class Fake:
 """Provisioner double: Google refuses the whole policy when it contains the bad principal."""
 calls=[]
 def __init__(self,team,identity,state,save,api=None):self.students=['user:'+e for e in team['member_emails']]
 def grant_members(self,students=None):
  students=self.students if students is None else students;Fake.calls.append(list(students))
  if 'user:bad.person@gmail.com' in students:raise CloudError(400,'POST setIamPolicy')
 def revoke_members(self,students):Fake.revoked.append(list(students))
 revoked=[]

def test_one_bad_member_does_not_block_the_group_and_stops_retries(app):
 seed_ready(app);c=admin_client(app);Fake.calls=[]
 with patch('membership.enqueue'):
  for e in ('good.person@gmail.com','bad.person@gmail.com','other.person@gmail.com'):assert add(c,'one',e).status_code==201
 with patch('membership.Provisioner',Fake):
  result,code=process_members(app,'one')
 assert code==200,result
 s=statuses(app)
 assert s['good.person@gmail.com']==('ready',None) and s['other.person@gmail.com']==('ready',None)
 assert s['bad.person@gmail.com'][0]=='failed' and 'ตรวจตัวสะกด' in s['bad.person@gmail.com'][1]
 assert ['user:bad.person@gmail.com'] in Fake.calls
 overview={m['email']:m for t in c.get('/api/admin/overview').json['teams'] if t['id']=='one' for m in t['members']}
 assert overview['bad.person@gmail.com']['cloud_status']=='failed' and overview['bad.person@gmail.com']['cloud_error']
 with patch('membership.Provisioner',Fake):assert process_members(app,'one')[1]==200  # nothing left to retry
 # TA fixes by removing the bad member; syncing the rest never includes it again
 with patch('membership.enqueue'):assert c.post('/api/admin/teams/one/members/remove',json={'email':'bad.person@gmail.com'},headers=auth(c)).status_code==202
 Fake.calls=[];Fake.revoked=[]
 with patch('membership.Provisioner',Fake):assert process_members(app,'one')[1]==200
 assert Fake.revoked==[['user:bad.person@gmail.com']] and 'bad.person@gmail.com' not in statuses(app)

def test_transient_member_failure_still_retries(app):
 seed_ready(app);c=admin_client(app)
 with patch('membership.enqueue'):add(c,'one','good.person@gmail.com')
 class Flaky(Fake):
  def grant_members(self,students=None):raise Pending('quota')
 with patch('membership.Provisioner',Flaky):result,code=process_members(app,'one')
 assert code==503 and statuses(app)['good.person@gmail.com'][0]=='pending'

def test_add_member_requires_confirmation_and_csrf(app):
 c=admin_client(app)
 r=c.post('/api/admin/teams/one/members',json={'email':' New.Person@GMAIL.com '},headers=auth(c))
 assert r.status_code==400 and r.json['preview'] and r.json['emails']==['new.person@gmail.com']
 assert add(c,'one','new.person@gmail.com',confirm='true').status_code==400  # only boolean true counts
 assert statuses(app)=={}
 assert c.post('/api/admin/teams/one/members',json={'email':'new.person@gmail.com','confirm':True}).status_code==403
 r=add(c,'one',' New.Person@GMAIL.com ');assert r.status_code==201 and r.json['emails']==['new.person@gmail.com']

def test_remove_member_is_admin_csrf_group_scoped_idempotent_and_blocks_login(app):
 seed_ready(app);c=admin_client(app)
 with patch('membership.enqueue') as queue:
  add(c,'one','partner.one@gmail.com');add(c,'one','keeper.one@gmail.com');add(c,'two','other.two@gmail.com')
 assert callback(c,app,'partner.one@gmail.com','sub-p').status_code==302 and c.get('/api/status').status_code==200
 c=admin_client(app);url='/api/admin/teams/one/members/remove'
 assert c.post(url,json={'email':'partner.one@gmail.com'}).status_code==403  # CSRF
 anon=app.test_client();anon.get('/');assert anon.post(url,json={'email':'partner.one@gmail.com'},headers=auth(anon)).status_code==403
 assert c.post(url,json={'email':'one@gmail.com'},headers=auth(c)).status_code==400  # primary stays
 assert c.post('/api/admin/teams/one/members/remove',json={'email':'other.two@gmail.com'},headers=auth(c)).json['already'] is True  # other group untouched
 with patch('membership.enqueue') as queue:
  r=c.post(url,json={'email':' Partner.One@gmail.com'},headers=auth(c));assert r.status_code==202 and queue.call_args.kwargs['kind']=='members'
 assert statuses(app)['partner.one@gmail.com'][0]=='removing'
 assert callback(c,app,'partner.one@gmail.com','sub-p').status_code==403  # cannot log in while revocation is pending
 Fake.revoked=[];Fake.calls=[]
 with patch('membership.Provisioner',Fake):assert process_members(app,'one')[1]==200
 assert Fake.revoked==[['user:partner.one@gmail.com']] and all('user:partner.one@gmail.com' not in c for c in Fake.calls)
 s=statuses(app);assert 'partner.one@gmail.com' not in s and 'keeper.one@gmail.com' in s and 'other.two@gmail.com' in s
 assert c.post(url,json={'email':'partner.one@gmail.com'},headers=auth(c)).json['already'] is True
 assert callback(app.test_client(),app,'partner.one@gmail.com').status_code==403

def test_revoke_only_removes_that_user_and_keeps_other_bindings():
 team={'id':'one','prefix':'one123','email':'one@gmail.com','member_emails':['one@gmail.com']}
 policies={};calls=[]
 sa='serviceAccount:one123-deployer@x.iam.gserviceaccount.com'
 def base(): return {'bindings':[{'role':'roles/run.developer','members':['user:gone@gmail.com','user:stay@gmail.com',sa]},
  {'role':'roles/other','members':['user:gone@gmail.com']},
  {'role':'roles/cloudsql.client','members':['user:gone@gmail.com','user:x@y.com'],'condition':{'title':'cpe334-one123','expression':"resource.type == 'sqladmin.googleapis.com/Instance' && resource.name == 'projects/cpe-se-course-2026/instances/one123-pg'"}},
  {'role':'roles/cloudsql.client','members':['user:gone@gmail.com'],'condition':{'title':'cpe334-other','expression':'other group'}}],'etag':'v1'}
 class API:
  def request(self,method,url,body=None,**kw):
   calls.append((method,url,body))
   if url.endswith(':getIamPolicy'):return base()
   if method=='GET':
    if '/views/' in url or '/serviceAccounts/' in url:return {'description':'CPE334 portal group:one;prefix:one123;v1'}
    return {'labels':{'cpe334-team':'one'},'settings':{'userLabels':{'cpe334-team':'one'}}}
   return {}
 Provisioner(team,{},{},lambda _:None,API()).revoke_members(['user:gone@gmail.com','serviceAccount:evil'])
 sets=[(u,b['policy']) for m,u,b in calls if u.endswith(':setIamPolicy')]
 assert sets
 for url,doc in sets:
  original=base()['bindings'];changed=[(o,n) for o,n in zip(original,doc['bindings']) if o!=n]
  assert len(doc['bindings'])==len(original) and len(changed)==1  # exactly one binding edited per policy
  old,new=changed[0];assert new['members']==[m for m in old['members'] if m!='user:gone@gmail.com'] and new.get('condition')==old.get('condition')
  assert old['role']!='roles/other' and old.get('condition',{}).get('title')!='cpe334-other'
 assert not any('serviceAccount:evil' in json.dumps(b) for m,u,b in calls)

def test_identity_canonicalizes_only_gmail():
 from membership import identity
 assert identity('John.Doe+x@gmail.com')==identity('johndoe@googlemail.com')=='johndoe@gmail.com'
 assert identity('john.doe@uni.ac.th')!=identity('johndoe@gmail.com')
 assert identity('john.doe@uni.ac.th')=='john.doe@uni.ac.th'

def test_non_gmail_roster_email_does_not_collide_and_ta_aliases_are_blocked(app):
 app.config['TA_EMAILS']='ta@gmail.com,ta.admin26@gmail.com'
 with app.db() as db:db.execute("INSERT INTO teams VALUES('uni','Uni','john.doe@uni.ac.th','uni123',1,NULL,0)")
 c=admin_client(app)
 assert add(c,'one','johndoe@gmail.com').status_code==201
 for alias in ('ta.admin26@gmail.com','taadmin26@gmail.com','TA.Admin.26@gmail.com'):assert add(c,'one',alias).status_code==400,alias

def test_gmail_dot_variant_login_matches_member_and_keeps_stored_principal(app):
 c=admin_client(app);assert add(c,'one','dotted.name@gmail.com').status_code==201
 assert callback(c,app,'dottedname@gmail.com','sub-d').status_code==302
 assert c.get('/api/status').json['team']['prefix']=='one123'
 assert callback(c,app,'dotted.name@gmail.com','sub-d').status_code==302
 assert callback(c,app,'dottedname@gmail.com','other-sub').status_code==403  # pinned sub still enforced
 with app.db() as db:db.execute("UPDATE teams SET email='pri.mary.team@gmail.com' WHERE id='two'")
 assert callback(c,app,'primaryteam@gmail.com','sub-t').status_code==302 and c.get('/api/status').json['team']['prefix']=='two123'
 assert 'dotted.name@gmail.com' in statuses(app)  # IAM principal is the exact stored string
 assert callback(c,app,'unknown.person@gmail.com').status_code==403

def test_members_added_before_ready_are_not_queued_and_picked_up_when_ready(app):
 c=admin_client(app);now=int(time.time())
 with app.db() as db:
  db.execute("INSERT INTO activations(team_id,repo,mode,status,step,created_at,updated_at) VALUES('one','o/r','live','running',2,?,?)",(now,now))
  db.execute('INSERT INTO activation_runtime VALUES(?,?,?)',('one','1',json.dumps({'identity':{'repo':'o/r','repository_id':'1','owner_id':'2'},'operations':{}})))
 with patch('membership.enqueue') as queue:
  r=add(c,'one','late.member@gmail.com');assert r.status_code==201 and r.json['cloud_status']=='pending'
  queue.assert_not_called()
 s=statuses(app)['late.member@gmail.com'];assert s[0]=='pending' and 'Activate' in s[1]
 assert process_members(app,'one')[1]==503  # not ready: nothing is granted yet
 with app.db() as db:db.execute("UPDATE activations SET status='failed' WHERE team_id='one'")
 with patch('membership.enqueue') as queue:
  add(c,'one','late.member@gmail.com');queue.assert_not_called()
 assert 'ไม่สำเร็จ' in statuses(app)['late.member@gmail.com'][1]
 with app.db() as db:db.execute("UPDATE activations SET status='ready' WHERE team_id='one'")
 from activation import process_live
 Fake.calls=[]
 with patch('membership.Provisioner',Fake):assert process_live(app,'one')[1]==200  # process_live -> process_members
 assert statuses(app)['late.member@gmail.com']==('ready',None)

def test_duplicate_team_name_and_caps(app):
 c=admin_client(app);post=lambda name,email:c.post('/api/admin/teams',json={'name':name,'email':email},headers=auth(c)).status_code
 assert post('Alpha Team','alpha.team@gmail.com')==201
 assert post('  alpha   TEAM ','alpha.two@gmail.com')==409
 assert post('team one','alpha.three@gmail.com')==409
 assert post('A','alpha.four@gmail.com')==400 and post('x'*81,'alpha.four@gmail.com')==400 and post(5,'alpha.four@gmail.com')==400
 with patch('membership.MAX_TEAMS',3):assert post('Beta Team','beta.team@gmail.com')==409
 assert post('Beta Team','beta.team@gmail.com')==201

def test_team_id_prefix_collision_retries(app):
 with app.db() as db:db.execute("INSERT INTO teams VALUES('t9','Taken','taken.team@gmail.com','saaaaaaaa',1,NULL,0)")
 c=admin_client(app)
 tokens=iter(['111111111111','aaaaaaaaaaaa','222222222222','bbbbbbbbbbbb','333333333333','cccccccccccc'])
 with patch('membership.token',side_effect=lambda n:next(tokens)):
  r=c.post('/api/admin/teams',json={'name':'Fresh Team','email':'fresh.team@gmail.com'},headers=auth(c))
 assert r.status_code==201 and r.json['prefix']=='sbbbbbbbb' and r.json['team_id']=='222222222222'

def concurrent_adds(app):
 clients=[admin_client(app) for _ in range(2)]
 def go(args):
  c,team=args;return add(c,team,'race.member@gmail.com').status_code
 with concurrent.futures.ThreadPoolExecutor(2) as pool:codes=sorted(pool.map(go,zip(clients,('one','two'))))
 assert codes==[201,409]
 with app.db() as db:assert db.execute("SELECT count(*) n FROM team_members WHERE email='race.member@gmail.com'").fetchone()['n']==1

def test_concurrent_add_same_email_different_groups_sqlite(app):concurrent_adds(app)

def test_concurrent_add_same_email_different_groups_postgres(tmp_path):
 url=os.environ.get('PORTAL_TEST_POSTGRES')
 if not url:pytest.skip('Set PORTAL_TEST_POSTGRES to a disposable local PostgreSQL database')
 import psycopg
 from psycopg import sql
 from psycopg.conninfo import conninfo_to_dict,make_conninfo
 assert conninfo_to_dict(url).get('host') in ('127.0.0.1','localhost')
 schema='portal_test_'+uuid.uuid4().hex
 with psycopg.connect(url,autocommit=True) as db:db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
 try:
  from app import create_app
  a=create_app({'DATABASE':str(tmp_path/'u.sqlite3'),'DATABASE_URL':make_conninfo(url,options='-c search_path='+schema),'SECRET_KEY':'test','TESTING':True,'PREVIEW':True,'AUTH_MODE':'google','BASE_URL':'http://127.0.0.1:8876','TA_EMAILS':'ta@gmail.com','GOOGLE_CLIENT_ID':'t','GOOGLE_CLIENT_SECRET':'t'})
  with a.db() as db:
   db.execute("INSERT INTO teams VALUES('one','Team One','one@gmail.com','one123',1,NULL,0)")
   db.execute("INSERT INTO teams VALUES('two','Team Two','two@gmail.com','two123',1,NULL,0)")
  concurrent_adds(a)
 finally:
  with psycopg.connect(url,autocommit=True) as db:db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
