import json
from unittest.mock import patch
import pytest
from app import create_app
from activation import process_live
from live_provision import Provisioner, ProvisionError, Pending, wif_condition, task_name

@pytest.fixture
def app(tmp_path):
 a=create_app({'DATABASE':str(tmp_path/'live.sqlite3'),'SECRET_KEY':'test','TESTING':True,'PREVIEW':False,'AUTH_MODE':'google','BASE_URL':'https://example.test','LIVE_ACTIVATION_ENABLED':True,'WORKER_URL':'https://worker.test','ACTIVATE_MIN_INTERVAL':0})
 with a.db() as c:
  c.execute("INSERT INTO teams VALUES('one','One','one@gmail.com','s11111111',1,NULL,0)")
  c.execute("INSERT INTO teams VALUES('two','Two','two@gmail.com','s22222222',1,NULL,0)")
  for tid in ('one','two'):
   c.execute('INSERT INTO repo_reviews VALUES(?,?,?,?)',(tid,'owner/repo',json.dumps({'status':'prepared','repo':'owner/repo'}),0))
   c.execute('INSERT INTO repo_snapshots VALUES(?,?,?)',(tid,'a'*40,'{}'))
 return a

def client(a,team='one'):
 c=a.test_client();c.get('/')
 with c.session_transaction() as s:s['team_id']=team;csrf=s['csrf']
 return c,csrf

IDENTITY={'repo':'owner/repo','repository_id':'123','owner_id':'456'}

def test_live_activation_freezes_identity_ignores_tampering_and_deduplicates(app):
 c,csrf=client(app)
 with patch('activation.github_identity',return_value=IDENTITY),patch('activation.enqueue') as enqueue:
  for _ in range(2):
   assert c.post('/api/activate',json={'repo':'owner/repo','prefix':'victim','team_id':'two','project':'other'},headers={'X-CSRF-Token':csrf}).status_code==202
  assert enqueue.call_args.args[1]=='one'
  with app.db() as db:
   rows=db.execute('SELECT * FROM activations').fetchall();assert len(rows)==1
   assert rows[0]['team_id']=='one' and rows[0]['mode']=='live'
   state=json.loads(db.execute("SELECT state FROM activation_runtime WHERE team_id='one'").fetchone()['state'])
   assert state['identity']==IDENTITY
  other,csrf2=client(app,'two')
  assert other.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf2}).status_code==409
  assert other.get('/api/status').json['activation'] is None

def test_live_activation_requires_review_and_persists_when_dispatch_fails(app):
 c,csrf=client(app)
 with app.db() as db:db.execute("DELETE FROM repo_reviews WHERE team_id='one'")
 assert c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf}).status_code==409
 with app.db() as db:db.execute('INSERT INTO repo_reviews VALUES(?,?,?,?)',('one','owner/repo',json.dumps({'repo':'owner/repo','status':'prepared'}),0))
 with patch('activation.github_identity',return_value=IDENTITY),patch('activation.enqueue',side_effect=Pending('queue')):
  assert c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf}).status_code==503
  assert c.get('/api/status').json['activation']['mode']=='live'

def test_worker_retries_same_checkpoint_and_redacts_provider_failures(app):
 c,csrf=client(app)
 with patch('activation.github_identity',return_value=IDENTITY),patch('activation.enqueue'):
  c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf})
 with patch('activation.Provisioner.step',side_effect=Pending('Waiting for database readiness')):
  assert process_live(app,'one')[1]==503
 assert c.get('/api/status').json['activation']['step']==0
 with patch('activation.Provisioner.step',side_effect=RuntimeError('password=private')):
  process_live(app,'one')
 assert 'private' not in c.get('/api/status').text
 with patch('activation.Provisioner.step',side_effect=ProvisionError('ownership conflict')):
  assert process_live(app,'one')[1]==200
 assert c.get('/api/status').json['activation']['status']=='failed'

def test_conflicting_resource_stops_before_mutation_and_wif_is_exact():
 class API:
  def request(self,method,url,body=None,**kw):
   assert method=='GET'
   return {'labels':{'cpe334-team':'another'}}
 p=Provisioner({'id':'one','email':'one@gmail.com','prefix':'s11111111'},IDENTITY,{},lambda _:None,API())
 with pytest.raises(ProvisionError):p.registry()
 condition=wif_condition(IDENTITY)
 for text in ["repository_id == '123'","repository_owner_id == '456'","refs/heads/main","environment:demo",".github/workflows/deploy.yml@refs/heads/main"]:assert text in condition
 assert task_name('one',1)==task_name('one',1) and task_name('one',1)!=task_name('two',1)

def test_live_worker_endpoint_is_not_available_on_public_web(app):
 c,_=client(app)
 assert c.post('/internal/provision',json={'team_id':'one'}).status_code in (403,404)

def test_operation_resume_does_not_repeat_creation():
 class API:
  def __init__(self):self.created=0;self.done=False
  def request(self,method,url,body=None,**kw):
   if method=='POST':self.created+=1;return {'name':'projects/p/locations/r/operations/op1','done':False}
   if '/operations/' in url:return {'done':self.done}
   return {'labels':{'cpe334-team':'one'}} if self.created else None
 api=API();state={};saved=[]
 p=Provisioner({'id':'one','email':'one@gmail.com','prefix':'s11111111'},IDENTITY,state,lambda s:saved.append(json.dumps(s)),api)
 with pytest.raises(Pending):p.registry()
 assert api.created==1 and saved
 api.done=True
 restarted=Provisioner(p.team,IDENTITY,json.loads(saved[-1]),lambda _:None,api)
 restarted.registry();assert api.created==1

def test_direct_resource_creation_is_not_treated_as_an_operation():
 class API:
  def __init__(self):self.created=False
  def request(self,method,url,body=None,**kw):
   if method=='POST':self.created=True
   return {'name':'projects/p/secrets/s1','labels':{'cpe334-team':'one'}} if self.created else None
 p=Provisioner({'id':'one','email':'one@gmail.com','prefix':'s11111111'},IDENTITY,{},lambda _:None,API())
 assert p.ensure('secret','https://example/','secret','parent',{})['name']=='projects/p/secrets/s1'
 assert not p.state['operations']

def test_ready_only_after_six_stages_promotes_existing_review_to_live(app):
 from tests.test_repo_review import fixture_files
 c,csrf=client(app)
 with app.db() as db:db.execute('UPDATE repo_snapshots SET files=? WHERE team_id=?',(json.dumps(fixture_files()),'one'))
 with patch('activation.github_identity',return_value=IDENTITY),patch('activation.enqueue'):
  c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf})
 with patch('activation.Provisioner.step'):
  for n in range(6):
   result,status=process_live(app,'one')
   assert status==(200 if n==5 else 503)
   row=c.get('/api/status').json['activation']
   assert row['step']==n+1
   assert (row['status']=='ready')==(n==5)
 review=c.get('/api/repo-review').json['review']
 assert review['preview'] is False and review['status']=='prepared'
 assert all('STOP: preview proposal' not in x['after'] for x in review['changes'])
 outputs=c.get('/api/handoff').json
 assert outputs['mode']=='live' and outputs['created_in_google_cloud'] is True
 assert 'PROJECT_NUMBER' not in outputs['github_variables']['WIF_PROVIDER']
 assert outputs['application_deployed_by_portal'] is False
 assert 'password=' not in json.dumps(outputs)

@pytest.mark.parametrize('url,verb',[
 ('https://iam.googleapis.com/v1/projects/p/serviceAccounts/a','POST'),
 ('https://logging.googleapis.com/v2/projects/p/locations/global/buckets/b/views/v','POST'),
 ('https://artifactregistry.googleapis.com/v1/projects/p/locations/r/repositories/a','GET'),
 ('https://run.googleapis.com/v2/projects/p/locations/r/services/a','GET'),
 ('https://secretmanager.googleapis.com/v1/projects/p/secrets/a','GET'),
])
def test_iam_policy_methods_and_etag_are_preserved(url,verb):
 class API:
  def request(self,method,endpoint,body=None,**kw):
   if endpoint.endswith(':getIamPolicy'):
    assert method==verb;return {'etag':'current','bindings':[]}
   assert method=='POST' and endpoint.endswith(':setIamPolicy')
   assert body['policy']['etag']=='current' and body['policy']['version']==3
 p=Provisioner({'id':'one','email':'one@gmail.com','prefix':'s11111111'},IDENTITY,{},lambda _:None,API())
 p.policy(url,[('roles/run.developer',['user:one@gmail.com'],None)])

def test_enqueue_duplicate_does_not_require_task_reader_permissions():
 from live_provision import enqueue,AlreadyExists
 class API:
  def request(self,method,url,body=None,**kw):
   assert method=='POST';raise AlreadyExists('duplicate')
 enqueue({'WORKER_URL':'https://worker.test','TASK_IDENTITY':'tasks@example.test'},'one',1,api=API())
