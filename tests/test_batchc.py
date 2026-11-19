"""Regression tests for the batch-C review findings (each fails on the pre-fix code)."""
import io,json,logging,os,shutil,sqlite3,subprocess,sys,tempfile,time,zipfile
from unittest.mock import patch
import pytest
from requests.structures import CaseInsensitiveDict
from tests.test_live import client,IDENTITY
from tests.test_admin import app
from tests.test_membership import admin_client,auth,seed_ready,statuses,Fake
from activation import process_live
from membership import process_members,member_emails
from live_provision import (Provisioner,ProvisionError,Pending,CloudError,RevokeIncomplete,PROJECT,REGION)

@pytest.fixture
def live(tmp_path):
 from app import create_app
 a=create_app({'DATABASE':str(tmp_path/'live.sqlite3'),'SECRET_KEY':'test','TESTING':True,'PREVIEW':False,'AUTH_MODE':'google','BASE_URL':'https://example.test','LIVE_ACTIVATION_ENABLED':True,'WORKER_URL':'https://worker.test','ACTIVATE_MIN_INTERVAL':0})
 with a.db() as c:
  c.execute("INSERT INTO teams VALUES('one','One','one@gmail.com','s11111111',1,NULL,0)")
  c.execute("INSERT INTO teams VALUES('two','Two','two@gmail.com','s22222222',1,NULL,0)")
  for tid in ('one','two'):
   c.execute('INSERT INTO repo_reviews VALUES(?,?,?,?)',(tid,'owner/repo',json.dumps({'status':'prepared','repo':'owner/repo'}),0))
   c.execute('INSERT INTO repo_snapshots VALUES(?,?,?)',(tid,'a'*40,'{}'))
 return a

# ---------------------------------------------------------------- S-H1 revoke independent of owned()/existence
ALL_ROLES=['roles/run.developer','roles/artifactregistry.writer','roles/iam.serviceAccountUser','roles/logging.viewAccessor',
           'roles/secretmanager.secretAccessor','roles/secretmanager.secretVersionAdder','roles/cloudsql.client',
           'projects/%s/roles/cpe334ProjectIdentity'%PROJECT,'roles/serviceusage.serviceUsageConsumer']
SA='serviceAccount:one123-deployer@x.iam.gserviceaccount.com'


class IamCloud:
 """Fake Google API: only IAM policy reads/writes exist; any plain GET (ownership/existence probe) is a failure."""
 def __init__(self,errors=None):
  self.policies={};self.errors=errors or {};self.calls=[];self.plain_gets=[]
 def policy(self,url):
  return self.policies.setdefault(url,{'bindings':[{'role':r,'members':['user:gone@gmail.com','user:stay@gmail.com',SA]} for r in ALL_ROLES],'etag':'e'})
 def request(self,method,url,body=None,missing=False,params=None):
  self.calls.append((method,url))
  base=url.replace(':getIamPolicy','').replace(':setIamPolicy','')
  for needle,err in self.errors.items():
   if needle in url and (':setIamPolicy' in url or ':getIamPolicy' in url):
    if isinstance(err,int):raise CloudError(err,method+' '+url)
    raise err
  if url.endswith(':getIamPolicy'):return json.loads(json.dumps(self.policy(base)))
  if url.endswith(':setIamPolicy'):self.policies[base]=body['policy'];return {}
  self.plain_gets.append(url);raise AssertionError('revoke must not probe resources: '+url)

TEAM={'id':'one','prefix':'one123','email':'one@gmail.com','member_emails':['one@gmail.com']}

def revoker(cloud):return Provisioner(TEAM,{},{},lambda _:None,cloud)

PROJECT_URL='https://cloudresourcemanager.googleapis.com/v1/projects/'+PROJECT
PROJECT_ROLES=['projects/%s/roles/cpe334ProjectIdentity'%PROJECT,'roles/serviceusage.serviceUsageConsumer']

def assert_revoked(cloud,skip=()):
 """Exactly the revoked (url,role) bindings lost the user; every other member and binding is intact."""
 pairs=revoker(cloud).revoke_targets()+[(PROJECT_URL,r) for r in PROJECT_ROLES]
 for url,doc in cloud.policies.items():
  for b in doc['bindings']:
   assert 'user:stay@gmail.com' in b['members'] and SA in b['members'],(url,b['role'])
   revoked=(url,b['role']) in pairs and not any(sk in url for sk in skip)
   assert ('user:gone@gmail.com' in b['members'])!=revoked or (b['role']=='roles/cloudsql.client' and 'user:gone@gmail.com' in b['members']),(url,b['role'])

def test_revoke_does_not_probe_resources_or_labels_and_touches_only_that_user():
 c=IamCloud();revoker(c).revoke_members(['user:gone@gmail.com','serviceAccount:evil','group:x@y.com'])
 assert not c.plain_gets
 assert len(c.policies)==5+2+5+1  # service/job/registry/runtime SA/log view, 2 secrets, 5 slots, project
 assert_revoked(c)
 assert not any('evil' in json.dumps(p) for p in c.policies.values())

def test_label_removed_by_member_does_not_block_revocation():
 # members can edit labels on their own service: old code GETs the resource and refuses on a label mismatch
 class Relabelled(IamCloud):
  def request(self,method,url,body=None,**kw):
   if method=='GET' and ':getIamPolicy' not in url:return {'labels':{}}
   return super().request(method,url,body,**kw)
 c=Relabelled();revoker(c).revoke_members(['user:gone@gmail.com']);assert_revoked(c)

def test_deleted_job_or_404_target_is_skipped_and_everything_else_is_revoked():
 c=IamCloud({'/jobs/one123-migrate':404,'app-secret-3':404});revoker(c).revoke_members(['user:gone@gmail.com'])
 assert_revoked(c,skip=('/jobs/one123-migrate','app-secret-3'))
 assert any('cloudresourcemanager' in u for m,u in c.calls if u.endswith(':setIamPolicy'))  # project-level always processed
 assert any('/services/one123' in u and u.endswith(':setIamPolicy') for m,u in c.calls)

def test_partial_failure_processes_all_targets_reports_failed_and_marks_transient():
 c=IamCloud({'/services/one123':403});r=revoker(c)
 with pytest.raises(RevokeIncomplete) as e:r.revoke_members(['user:gone@gmail.com'])
 assert e.value.failed==['locations/asia-southeast1/services/one123'] and e.value.transient is True
 assert_revoked(c,skip=('/services/one123',))
 assert 'user:gone@gmail.com' in json.dumps(c.policy('https://run.googleapis.com/v2/projects/%s/locations/%s/services/one123'%(PROJECT,REGION)))

def test_pending_error_is_collected_not_fatal_and_permanent_400_is_not_retried():
 c=IamCloud({'cloudresourcemanager':Pending('quota')})
 with pytest.raises(RevokeIncomplete) as e:revoker(c).revoke_members(['user:gone@gmail.com'])
 assert e.value.failed==['project-iam'] and e.value.transient
 c=IamCloud({'/repositories/one123':400})
 with pytest.raises(RevokeIncomplete) as e:revoker(c).revoke_members(['user:gone@gmail.com'])
 assert e.value.transient is False
 assert_revoked(c,skip=('/repositories/one123',))

def test_lease_loss_during_revoke_aborts_instead_of_being_swallowed():
 from live_provision import LeaseLost
 calls=[]
 def save(_):
  calls.append(1)
  if len(calls)>3:raise LeaseLost('x')
 with pytest.raises(LeaseLost):Provisioner(TEAM,{},{},save,IamCloud()).revoke_members(['user:gone@gmail.com'])

def test_incomplete_revoke_keeps_member_removing_with_targets_and_retries_only_when_transient(app):
 seed_ready(app);c=admin_client(app)
 with patch('membership.enqueue'):
  from tests.test_membership import add
  add(c,'one','gone.person@gmail.com');c.post('/api/admin/teams/one/members/remove',json={'email':'gone.person@gmail.com'},headers=auth(c))
 class Broken(Fake):
  def revoke_members(self,students):raise RevokeIncomplete(['locations/x/services/one123'],True)
 with patch('membership.Provisioner',Broken):result,code=process_members(app,'one')
 assert code==503
 s=statuses(app)['gone.person@gmail.com'];assert s[0]=='removing' and 'services/one123' in s[1]
 class Permanent(Fake):
  def revoke_members(self,students):raise RevokeIncomplete(['a'],False)
 with patch('membership.Provisioner',Permanent):assert process_members(app,'one')[1]==200

# ---------------------------------------------------------------- S-H2 revoke for any status / disabled team
def seed(app,status,lease=0,step=6):
 with app.db() as db:
  now=int(time.time());db.execute("INSERT INTO activations(team_id,repo,mode,status,step,created_at,updated_at,lease_until) VALUES('one','owner/repo','live',?,?,?,?,?)",(status,step,now,now,lease))
  db.execute('INSERT INTO activation_runtime VALUES(?,?,?)',('one','1',json.dumps({'identity':{'repo':'owner/repo','repository_id':'1','owner_id':'2'},'operations':{}})))

@pytest.mark.parametrize('status',['failed','running','queued'])
def test_removal_runs_for_non_ready_activation_and_enqueues(app,status):
 seed(app,status,step=3);c=admin_client(app)
 with app.db() as db:db.execute("INSERT INTO team_members(email,team_id,added_at,added_by,cloud_status) VALUES('gone.person@gmail.com','one',1,'ta','ready')")
 with patch('membership.enqueue') as q:
  r=c.post('/api/admin/teams/one/members/remove',json={'email':'gone.person@gmail.com'},headers=auth(c))
  assert r.status_code==202 and q.call_args.kwargs['kind']=='members'
 Fake.revoked=[]
 with patch('membership.Provisioner',Fake):result,code=process_members(app,'one')
 assert code==200,result;assert Fake.revoked==[['user:gone.person@gmail.com']] and 'gone.person@gmail.com' not in statuses(app)
 with app.db() as db:assert db.execute("SELECT status,step FROM activations").fetchone()['status']==status  # activation untouched

def test_removal_waits_for_live_activation_lease_without_running_concurrently(app):
 seed(app,'running',lease=int(time.time())+100);c=admin_client(app)
 with app.db() as db:db.execute("INSERT INTO team_members(email,team_id,added_at,added_by,cloud_status) VALUES('gone.person@gmail.com','one',1,'ta','removing')")
 Fake.revoked=[]
 with patch('membership.Provisioner',Fake):assert process_members(app,'one')[1]==503
 assert Fake.revoked==[]

def test_pending_members_still_wait_when_not_ready_but_revoke_does_not(app):
 seed(app,'failed');
 with app.db() as db:
  db.execute("INSERT INTO team_members(email,team_id,added_at,added_by,cloud_status) VALUES('late.person@gmail.com','one',1,'ta','pending')")
  db.execute("INSERT INTO team_members(email,team_id,added_at,added_by,cloud_status) VALUES('gone.person@gmail.com','one',1,'ta','removing')")
 Fake.revoked=[];Fake.calls=[]
 with patch('membership.Provisioner',Fake):assert process_members(app,'one')[1]==200
 assert Fake.revoked==[['user:gone.person@gmail.com']] and Fake.calls==[]
 assert statuses(app)['late.person@gmail.com'][0]=='pending'

def test_disabled_team_revokes_every_principal_once_and_reenable_regrants(app):
 seed_ready(app);c=admin_client(app)
 with app.db() as db:
  db.execute("INSERT INTO team_members(email,team_id,added_at,added_by,cloud_status) VALUES('mate.one@gmail.com','one',1,'ta','ready')")
  db.execute("INSERT INTO team_members(email,team_id,added_at,added_by,cloud_status) VALUES('mate.two@gmail.com','one',1,'ta','pending')")
 anon=app.test_client();anon.get('/');assert anon.post('/api/admin/teams/one/disable',headers=auth(anon)).status_code==403
 with patch('membership.enqueue') as q:
  r=c.post('/api/admin/teams/one/disable',headers=auth(c));assert r.status_code==200 and r.json['cloud_sync']=='queued' and q.call_args.kwargs['kind']=='members'
 with app.db() as db:
  assert db.execute("SELECT enabled FROM teams WHERE id='one'").fetchone()['enabled']==0
  assert db.execute("SELECT count(*) n FROM admin_audit WHERE action='disable_team'").fetchone()['n']==1
 Fake.revoked=[];Fake.calls=[]
 with patch('membership.Provisioner',Fake):result,code=process_members(app,'one')
 assert code==200 and result['status']=='revoked',result
 assert sorted(Fake.revoked[0])==['user:mate.one@gmail.com','user:mate.two@gmail.com','user:one@gmail.com'] and Fake.calls==[]
 with patch('membership.Provisioner',Fake):assert process_members(app,'one')[0]['status']=='no_pending_members'
 assert len(Fake.revoked)==1  # idempotent
 with patch('membership.enqueue'):assert c.post('/api/admin/teams/one/enable',headers=auth(c)).json['enabled'] is True
 with patch('membership.Provisioner',Fake):result,code=process_members(app,'one')
 assert code==200 and Fake.calls and sorted(Fake.calls[0])==['user:mate.one@gmail.com','user:one@gmail.com']
 with app.db() as db:assert 'access_revoked_at' not in json.loads(db.execute('SELECT state FROM activation_runtime').fetchone()['state'])

def test_disabled_team_revoke_failure_retries_when_transient(app):
 seed(app,'failed');
 with app.db() as db:db.execute("UPDATE teams SET enabled=0 WHERE id='one'")
 class Flaky(Fake):
  def revoke_members(self,students):raise RevokeIncomplete(['x'],True)
 with patch('membership.Provisioner',Flaky):assert process_members(app,'one')[1]==503
 with app.db() as db:assert 'access_revoked_at' not in json.loads(db.execute('SELECT state FROM activation_runtime').fetchone()['state'])

# ---------------------------------------------------------------- S-L3
def test_queue_failure_does_not_overwrite_removing_status(app):
 seed_ready(app);c=admin_client(app)
 def racing_enqueue(*a,**k):
  with app.db() as db:db.execute("UPDATE team_members SET cloud_status='removing'")
  raise Pending('queue down')
 with patch('membership.enqueue',side_effect=racing_enqueue):
  from tests.test_membership import add
  add(c,'one','race.person@gmail.com')
 assert statuses(app)['race.person@gmail.com'][0]=='removing'

# ---------------------------------------------------------------- S-M1 ReDoS + scan outside transaction
def test_credential_scan_is_linear_on_adversarial_input_and_still_detects_real_urls():
 import repo_review
 evil='mysql://a:$'*15000  # ~150 KB
 start=time.perf_counter();assert repo_review.CREDENTIAL_URL.findall(evil)==[];assert time.perf_counter()-start<1.0
 from tests.test_repo_review import fixture_files
 files=fixture_files();files['deploy/deploy.sh']+='\n'+evil[:140000]
 start=time.perf_counter();repo_review.inspect_files('o/r','a'*40,files,'s11111111');assert time.perf_counter()-start<1.0
 for url in ('postgres://admin:hunter2@db.example.com/x','postgresql://u:p@h','mysql://root:secret@10.0.0.1:3306/db'):
  files=fixture_files();files['deploy/deploy.sh']+='\nDB="'+url+'"\n'
  with pytest.raises(ValueError,match='credential'):repo_review.inspect_files('o/r','a'*40,files,'s11111111')
 files=fixture_files();files['deploy/deploy.sh']+='\nDB="postgres://u:${PASSWORD}@h/x"\n'
 repo_review.inspect_files('o/r','a'*40,files,'s11111111')  # variable reference is not a literal credential

def test_oversized_file_is_refused_before_scanning():
 import repo_review
 from tests.test_repo_review import fixture_files
 files=fixture_files();files['Dockerfile']='#'*(repo_review.MAX_SCAN_BYTES+1)
 with pytest.raises(ValueError,match='ใหญ่เกิน'):repo_review.inspect_files('o/r','a'*40,files,'s11111111')

def test_snapshot_inspection_does_not_hold_the_db_lock(live,tmp_path):
 c,csrf=client(live)
 with patch('activation.enqueue'),patch('activation.github_identity',return_value=IDENTITY):
  assert c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf}).status_code==202
 with live.db() as db:
  db.execute("UPDATE activations SET step=5 WHERE team_id='one'");db.execute("UPDATE repo_snapshots SET files='{}' WHERE team_id='one'")
 locked=[]
 def inspect(*a,**k):
  other=sqlite3.connect(live.config['DATABASE'],timeout=0.2)
  try:other.execute('BEGIN IMMEDIATE');other.execute('ROLLBACK');locked.append(False)
  except sqlite3.OperationalError:locked.append(True)
  finally:other.close()
  return {'status':'prepared'}
 with patch.object(Provisioner,'step'),patch.object(Provisioner,'outputs',return_value={}),patch('repo_review.inspect_files',side_effect=inspect):
  assert process_live(live,'one')[1]==200
 assert locked==[False]

# ---------------------------------------------------------------- S-M2 rate limits
def test_failed_review_attempts_are_rate_limited_before_github(live):
 c,csrf=client(live);h={'X-CSRF-Token':csrf}
 with patch('repo_review.fetch_snapshot',side_effect=ValueError('ไม่พบ public repo หรือ branch main ตาม Lab 5')) as fetch:
  assert c.post('/api/repo-review',json={'repo':'o/r'},headers=h).status_code==400
  r=c.post('/api/repo-review',json={'repo':'o/r'},headers=h)
  assert r.status_code==429 and 'กรุณารอ 15 วินาที' in r.json['error']
  assert fetch.call_count==1
 other,h2=client(live,'two')  # per team
 with patch('repo_review.fetch_snapshot',side_effect=ValueError('x')) as fetch:assert other.post('/api/repo-review',json={'repo':'o/r'},headers={'X-CSRF-Token':h2}).status_code==400
 with live.db() as db:db.execute("UPDATE rate_limits SET at=at-100")
 with patch('repo_review.fetch_snapshot',side_effect=ValueError('x')):assert c.post('/api/repo-review',json={'repo':'o/r'},headers=h).status_code==400

def test_review_in_flight_guard_allows_one_at_a_time_and_releases(live):
 c,csrf=client(live);h={'X-CSRF-Token':csrf};seen=[]
 def slow(repo):
  second=c.post('/api/repo-review',json={'repo':'o/r'},headers=h);seen.append((second.status_code,second.json['error']))
  raise ValueError('done')
 with patch('repo_review.fetch_snapshot',side_effect=slow):c.post('/api/repo-review',json={'repo':'o/r'},headers=h)
 assert seen==[(429,'กำลังตรวจ repo ของกลุ่มนี้อยู่ กรุณารอให้เสร็จก่อน แล้วลองอีกครั้ง')]
 with live.db() as db:assert db.execute('SELECT busy_until FROM rate_limits').fetchone()['busy_until']==0

def test_activate_has_per_team_minimum_interval(live):
 live.config['ACTIVATE_MIN_INTERVAL']=5;c,csrf=client(live);h={'X-CSRF-Token':csrf}
 with patch('activation.github_identity',return_value=IDENTITY),patch('activation.enqueue'):
  assert c.post('/api/activate',json={'repo':'owner/repo'},headers=h).status_code==202
  r=c.post('/api/activate',json={'repo':'owner/repo'},headers=h)
  assert r.status_code==429 and 'กดเร็วเกินไป' in r.json['error']
  other,h2=client(live,'two');assert other.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':h2}).status_code in (202,409)

# ---------------------------------------------------------------- ST-M1 provisioning grants only primary + ready members
def test_provisioning_excludes_waiting_pending_failed_removing_members(live):
 with live.db() as db:
  for i,st in enumerate(('ready','waiting','pending','failed','removing')):
   db.execute("INSERT INTO team_members(email,team_id,added_at,added_by,cloud_status) VALUES(?,?,?,?,?)",(f'm{i}.person@gmail.com','one',1,'ta',st))
  team={'id':'one','email':'one@gmail.com'}
  assert member_emails(db,team,ready_only=True)==['m0.person@gmail.com','one@gmail.com']
  assert 'm1.person@gmail.com' in member_emails(db,team)  # the grant path (process_members) still sees pending members
 c,csrf=client(live);seen=[]
 with patch('activation.enqueue'),patch('activation.github_identity',return_value=IDENTITY):
  c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf})
 def step(self,n):seen.append(self.students)
 with patch.object(Provisioner,'step',step):process_live(live,'one')
 assert seen==[['user:m0.person@gmail.com','user:one@gmail.com']]

def test_unknown_gmail_cannot_fail_the_policy_during_provisioning():
 class Google400(IamCloud):
  def request(self,method,url,body=None,**kw):
   if url.endswith(':setIamPolicy') and 'user:unknown@gmail.com' in json.dumps(body):raise CloudError(400,'setIamPolicy')
   if method=='GET' and ':getIamPolicy' not in url:return {'description':'CPE334 portal group:one;prefix:one123;v1','labels':{'cpe334-team':'one'}}
   return super().request(method,url,body,**kw)
 team=dict(TEAM,member_emails=['one@gmail.com'])  # unknown@gmail.com is pending, so process_live no longer passes it
 Provisioner(team,{},{},lambda _:None,Google400()).identity_accounts()
 with pytest.raises(CloudError):Provisioner(dict(TEAM,member_emails=['one@gmail.com','unknown@gmail.com']),{},{},lambda _:None,Google400()).identity_accounts()

# ---------------------------------------------------------------- ST-M2 finished operations are forgotten
def test_failed_long_running_operation_is_dropped_so_retry_checks_the_real_resource():
 class API:
  def __init__(self):self.exists=False;self.posts=0
  def request(self,method,url,body=None,**kw):
   if method=='POST':self.posts+=1;return {'name':'projects/p/locations/r/operations/op1'}
   if '/operations/' in url:return {'done':True,'error':{'code':3}}
   return {'labels':{'cpe334-team':'one'}} if self.exists else None
 api=API();state={};saved=[]
 p=Provisioner(TEAM,{},state,lambda s:saved.append(json.loads(json.dumps(s))),api)
 with pytest.raises(ProvisionError):p.registry()
 assert 'registry' not in state['operations'] and 'registry' not in saved[-1]['operations']
 api.exists=True;p.registry()  # the retry sees the real resource instead of replaying the failed operation
 assert api.posts==1

def test_successful_operation_is_forgotten_too():
 class API:
  def request(self,method,url,body=None,**kw):
   if '/operations/' in url:return {'done':True}
   return {}
 state={'operations':{'k':'https://x/operations/1'}};p=Provisioner(TEAM,{},state,lambda s:None,API())
 p.operation('k','https://x/');assert state['operations']=={}

# ---------------------------------------------------------------- ST-L1 / L4 / L6 / L2
def ready_attach_setup(live):
 from tests.test_resource_only import ready_resources,attach
 c,csrf=client(live);ready_resources(live,c,csrf);return c,csrf,attach

def test_attach_requeues_when_the_first_enqueue_failed(live):
 c,csrf,attach=ready_attach_setup(live)
 with patch('activation.github_identity',return_value=IDENTITY),patch('activation.enqueue',side_effect=Pending('queue')):
  assert c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf}).status_code==503
 r,q=attach(c,csrf)  # "press Activate again" must really enqueue the sub-task
 assert r.status_code==202 and q.call_count==1

def test_attach_relink_and_retry_reset_attempts_so_stale_workers_cannot_write(live):
 c,csrf,attach=ready_attach_setup(live)
 with live.db() as db:db.execute("UPDATE activations SET attempts=777 WHERE team_id='one'")
 attach(c,csrf)
 with live.db() as db:
  row=db.execute("SELECT attempts FROM activations").fetchone();assert row['attempts']==0
  db.execute("UPDATE activations SET attempts=778,github_link_status='failed'")
 attach(c,csrf)
 with live.db() as db:
  assert db.execute("SELECT attempts FROM activations").fetchone()['attempts']==0
  db.execute("UPDATE activations SET attempts=779,status='failed',github_link_status=NULL,step=2")
 with patch('activation.github_identity',return_value=IDENTITY),patch('activation.enqueue'):
  assert c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf}).status_code==202
 with live.db() as db:
  row=db.execute("SELECT attempts,status FROM activations").fetchone();assert row['attempts']==0 and row['status']=='queued'

def test_invalid_prefix_is_a_recorded_failure_not_an_exception(live):
 c,csrf=client(live)
 with patch('activation.enqueue'),patch('activation.github_identity',return_value=IDENTITY):
  c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf})
 with live.db() as db:db.execute("UPDATE teams SET prefix='BAD!' WHERE id='one'")
 result,code=process_live(live,'one',api=object())
 assert code==200 and result['status']=='failed'
 with live.db() as db:
  row=db.execute('SELECT status,lease_until FROM activations').fetchone();assert row['status']=='failed' and row['lease_until']==0

def start_live(live,created_ago):
 c,csrf=client(live)
 with patch('activation.enqueue'),patch('activation.github_identity',return_value=IDENTITY):
  c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf})
 with live.db() as db:db.execute('UPDATE activations SET created_at=?',(int(time.time())-created_ago,))
 return c

def test_403_grace_window_is_measured_from_stage_start_not_first_request(live):
 start_live(live,created_ago=7200)  # queued behind the Cloud SQL create cap for two hours
 with patch.object(Provisioner,'step',side_effect=CloudError(403,'x')):
  result,code=process_live(live,'one')
 assert code==503 and result['status']=='pending'  # fresh stage: IAM propagation 403 is still transient
 with live.db() as db:
  state=json.loads(db.execute('SELECT state FROM activation_runtime').fetchone()['state']);assert state['stage_key']=='step:0'
  state['stage_started_at']=int(time.time())-4000
  db.execute('UPDATE activation_runtime SET state=?',(json.dumps(state),));db.execute('UPDATE activations SET lease_until=0')
 with patch.object(Provisioner,'step',side_effect=CloudError(403,'x')):
  result,code=process_live(live,'one')
 assert code==200 and result['status']=='failed'  # the stage itself has been 403 for >30 min

# ---------------------------------------------------------------- O-H2 quota
def test_activation_limit_env_default_and_counting(live,monkeypatch):
 from app import create_app
 assert live.config['TEAM_ACTIVATION_LIMIT']==39
 monkeypatch.setenv('TEAM_ACTIVATION_LIMIT','7');assert create_app({'DATABASE':':memory:x'.replace(':memory:x',str(live.config['DATABASE'])+'2'),'SECRET_KEY':'t','TESTING':True,'PREVIEW':True}).config['TEAM_ACTIVATION_LIMIT']==7
 monkeypatch.setenv('TEAM_ACTIVATION_LIMIT','nope');assert create_app({'DATABASE':str(live.config['DATABASE'])+'3','SECRET_KEY':'t','TESTING':True,'PREVIEW':True}).config['TEAM_ACTIVATION_LIMIT']==39
 live.config['TEAM_ACTIVATION_LIMIT']=1
 with live.db() as db:
  now=int(time.time());db.execute("INSERT INTO teams VALUES('old','Old','old@gmail.com','sold11111',1,NULL,0)")
  db.execute("INSERT INTO activations(team_id,repo,mode,status,step,created_at,updated_at) VALUES('old','','live','failed',0,?,?)",(now,now))
 c,csrf=client(live)
 with patch('activation.enqueue'):assert c.post('/api/activate',json={'resources_only':True},headers={'X-CSRF-Token':csrf}).status_code==202  # failed-at-stage-0 holds nothing
 with live.db() as db:db.execute("UPDATE teams SET enabled=0 WHERE id='old'");db.execute("UPDATE activations SET status='running',step=2 WHERE team_id='old'")
 c2,h2=client(live,'two')
 with patch('activation.enqueue'):assert c2.post('/api/activate',json={'resources_only':True},headers={'X-CSRF-Token':h2}).status_code==409  # 'one' now holds the only slot
 with live.db() as db:db.execute("UPDATE activations SET status='failed',step=0 WHERE team_id='one'")
 with patch('activation.enqueue'):assert c2.post('/api/activate',json={'resources_only':True},headers={'X-CSRF-Token':h2}).status_code==202

# ---------------------------------------------------------------- O-M3 GitHub auth / 5xx
class Res:
 def __init__(self,status,headers=None):self.status_code=status;self.headers=CaseInsensitiveDict(headers or {})
 def __enter__(self):return self
 def __exit__(self,*a):return False
 def iter_content(self,n):return iter([b'x'])

def test_github_401_and_5xx_have_their_own_messages_and_log_without_token(monkeypatch,caplog,app):
 import repo_review
 monkeypatch.setenv('GITHUB_API_TOKEN','tok-SECRET-123')
 for context in (None,app.app_context()):
  caplog.clear()
  if context:context.push()
  try:
   with patch('repo_review.requests.get',return_value=Res(401)),caplog.at_level(logging.WARNING):
    with pytest.raises(ValueError) as e:repo_review.get_bytes('https://api.github.com/x',10)
   assert str(e.value)==repo_review.GITHUB_AUTH_FAILED and 'จำกัดการอ่าน' not in str(e.value)
   assert any('GITHUB_API_TOKEN' in r.getMessage() and r.levelno==logging.WARNING for r in caplog.records)
   assert 'tok-SECRET-123' not in caplog.text
   caplog.clear()
   for code in (500,502,503):
    with patch('repo_review.requests.get',return_value=Res(code)),caplog.at_level(logging.WARNING):
     with pytest.raises(ValueError) as e:repo_review.get_bytes('https://api.github.com/x',10)
    assert str(e.value)==repo_review.GITHUB_UNAVAILABLE and caplog.records
  finally:
   if context:context.pop()
 with patch('repo_review.requests.get',return_value=Res(429)):
  with pytest.raises(ValueError,match='จำกัดการอ่าน'):repo_review.get_bytes('https://api.github.com/x',10)

# ---------------------------------------------------------------- O-M5 / O-L7 admin dashboard
TABLE='cpe-se-course-2026.billing_export.gcp_billing_export_resource_v1_ABC123'

class Capture:
 def __init__(self,error=None):self.body=None;self.error=error
 def request(self,method,url,body=None,**kw):
  if self.error:raise self.error
  self.body=body;return {'jobComplete':True,'rows':[]}

def test_billing_query_has_partition_filter_with_named_since_parameter():
 from admin_dashboard import collect_costs
 api=Capture();collect_costs({'BILLING_EXPORT_TABLE':TABLE,'BILLING_EXPORT_LOCATION':'US'},api)
 q=api.body['query'];assert '_PARTITIONTIME >= TIMESTAMP(@since)' in q and 'project.id=@project' in q
 params={p['name']:p['parameterValue']['value'] for p in api.body['queryParameters']};assert params=={'project':PROJECT,'since':'2026-11-01'}
 assert 'GROUP BY resource.name, service.description, team_label, currency' in q and 'ARRAY' not in q.upper().split('GROUP BY')[1]
 api=Capture();collect_costs({'BILLING_EXPORT_TABLE':TABLE,'BILLING_EXPORT_LOCATION':'US','BILLING_SINCE':'2026-12-15'},api)
 assert {p['name']:p['parameterValue']['value'] for p in api.body['queryParameters']}['since']=='2026-12-15'
 assert collect_costs({'BILLING_EXPORT_TABLE':TABLE,'BILLING_EXPORT_LOCATION':'US','BILLING_SINCE':"x') OR 1=1"},api)['status']=='invalid_configuration'

def test_export_404_for_more_than_48h_becomes_export_table_missing(app):
 from admin_dashboard import track_missing_export
 base={'status':'awaiting_export','groups':{},'collected_at':1}
 t0=1_000_000
 assert track_missing_export(app.db,dict(base),now=t0)['status']=='awaiting_export'
 assert track_missing_export(app.db,dict(base),now=t0+47*3600)['status']=='awaiting_export'
 r=track_missing_export(app.db,dict(base),now=t0+49*3600);assert r['status']=='export_table_missing' and r['missing_since']==t0
 assert track_missing_export(app.db,{'status':'available','rows':[]},now=t0+50*3600)['status']=='available'  # recovery resets
 assert track_missing_export(app.db,dict(base),now=t0+51*3600)['status']=='awaiting_export'

def test_adc_failure_degrades_sections_instead_of_a_500(app):
 import admin_dashboard
 with patch('admin_dashboard.GoogleAPI',side_effect=RuntimeError('no ADC token=abc')):
  cloud=admin_dashboard.collect_cloud();assert cloud['services'] is None and cloud['errors']['cloud']
  costs=admin_dashboard.collect_costs({'BILLING_EXPORT_TABLE':TABLE,'BILLING_EXPORT_LOCATION':'US'});assert costs['status']=='unavailable'
  c=admin_client(app);app.config['BILLING_EXPORT_TABLE']=TABLE
  r=c.get('/api/admin/overview');assert r.status_code==200 and r.json['cloud']['errors']['cloud'] and r.json['costs']['status']=='unavailable'

# ---------------------------------------------------------------- Z-H1 zip file-type bits
def attrs(z):return {i.filename:i.external_attr>>16 for i in z.infolist()}

def check_ditto(data,expect):
 if sys.platform!='darwin' or not shutil.which('ditto'):pytest.skip('ditto is macOS only')
 with tempfile.TemporaryDirectory() as d:
  zp=os.path.join(d,'a.zip');open(zp,'wb').write(data);out=os.path.join(d,'out');os.mkdir(out)
  subprocess.run(['ditto','-x','-k',zp,out],check=True,timeout=30)
  for rel,executable in expect.items():
   mode=os.stat(os.path.join(out,rel)).st_mode
   assert bool(mode&0o111)==executable,(rel,oct(mode))

def test_project_kit_zip_has_regular_file_bits_and_keeps_exec_bit_via_finder_extraction(app):
 from tests.test_kit_download import prepared
 r=prepared(app,'one').get('/api/kit/download');z=zipfile.ZipFile(io.BytesIO(r.data));a=attrs(z)
 assert a['project-kit/kit.sh']==0o100755 and a['project-kit/from-portal-json.sh']==0o100755
 assert a['project-kit/README.md']==0o100644 and a['project-kit/resources.env']==0o100644
 check_ditto(r.data,{'project-kit/kit.sh':True,'project-kit/from-portal-json.sh':True,'project-kit/README.md':False,'project-kit/resources.env':False})

def test_lab5_kit_zip_has_regular_file_bits_and_keeps_exec_bit_via_finder_extraction(live):
 c,_=client(live);r=c.get('/api/lab5-kit/download');z=zipfile.ZipFile(io.BytesIO(r.data));a=attrs(z);root='lab5-starter-kit-s11111111/'
 assert a[root+'deploy/deploy.sh']==0o100755 and a[root+'deploy/release.sh']==0o100755
 assert a[root+'.github/workflows/deploy.yml']==0o100644 and a[root+'README-LAB5.md']==0o100644
 check_ditto(r.data,{root+'deploy/deploy.sh':True,root+'deploy/release.sh':True,root+'README-LAB5.md':False})


def test_kit_zip_tolerates_missing_gitattributes_and_includes_it_when_present(tmp_path):
 from app import kit_files
 (tmp_path/'kit.sh').write_text('x')
 assert kit_files(tmp_path)==['kit.sh']
 (tmp_path/'.gitattributes').write_text('* text=auto eol=lf\n')
 assert '.gitattributes' in kit_files(tmp_path)
