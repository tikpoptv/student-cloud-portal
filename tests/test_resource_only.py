import json,time
from unittest.mock import patch
from tests.test_live import app,client,IDENTITY
from activation import process_live
from live_provision import Provisioner


def activate(c,csrf,**data):
 return c.post('/api/activate',json={'resources_only':True,**data},headers={'X-CSRF-Token':csrf})


def test_resource_activation_without_repository_or_review_is_team_scoped_and_idempotent(app):
 c,csrf=client(app)
 with app.db() as db:db.execute('DELETE FROM repo_reviews');db.execute('DELETE FROM repo_snapshots')
 with patch('activation.github_identity') as github,patch('activation.enqueue'):
  r=activate(c,csrf,team_id='two',prefix='other',project='victim');assert r.status_code==202
  assert activate(c,csrf).status_code==202
  second,h=client(app,'two');assert activate(second,h).status_code==202
  github.assert_not_called()
 with app.db() as db:
  rows=db.execute('SELECT * FROM activation_runtime ORDER BY team_id').fetchall();assert len(rows)==2
  assert rows[0]['repository_id']=='resources:one' and rows[1]['repository_id']=='resources:two'
  assert json.loads(rows[0]['state'])['identity'] is None
 assert c.get('/api/status').json['activation']['repo']==''
 assert activate(c,csrf,repo='owner/repo').status_code==400


def test_resource_only_worker_finishes_without_ever_provisioning_github(app):
 c,csrf=client(app)
 with patch('activation.enqueue'):assert activate(c,csrf).status_code==202
 called=[]
 def step(worker,n):
  called.append(n)
  if n==5:worker.github()
 with patch.object(Provisioner,'step',step),patch.object(Provisioner,'req',return_value=None) as req,patch.object(Provisioner,'policy'):
  for n in range(6):assert process_live(app,'one')[1]==(200 if n==5 else 503)
  assert all('workloadIdentity' not in call.args[1] for call in req.call_args_list)
 assert called==list(range(6))
 output=c.get('/api/handoff').json
 assert output['created_in_google_cloud'] is True and output['github_connected'] is False
 assert output['github_repository'] is None and output['github_variables']=={}
 assert 'wif_provider' not in output['resources'] and 'wif_pool' not in output['resources']
 assert output['resources']['cloud_run_service']=='s11111111'


def test_connect_later_uses_only_final_stage_and_same_resources(app):
 c,csrf=client(app)
 with patch('activation.enqueue'):activate(c,csrf)
 with app.db() as db:
  db.execute("UPDATE activations SET status='ready',step=6 WHERE team_id='one'")
  state=json.loads(db.execute("SELECT state FROM activation_runtime WHERE team_id='one'").fetchone()['state']);state['service_url']='https://existing.run.app';state['operations']['registry']='already-finished'
  db.execute('UPDATE activation_runtime SET state=? WHERE team_id=?',(json.dumps(state),'one'))
 with patch('activation.github_identity',return_value=IDENTITY),patch('activation.enqueue'):
  assert c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf}).status_code==202
 with app.db() as db:
  row=db.execute("SELECT * FROM activations WHERE team_id='one'").fetchone();assert row['step']==6 and row['status']=='ready' and row['github_link_status']=='queued' and row['repo']=='owner/repo'
  state=json.loads(db.execute("SELECT state FROM activation_runtime WHERE team_id='one'").fetchone()['state']);assert state['service_url']=='https://existing.run.app' and state['operations']['registry']=='already-finished'
 with patch.object(Provisioner,'step') as step:
  assert process_live(app,'one')[1]==200;assert step.call_args.args==(5,)
 assert c.get('/api/handoff').json['github_connected'] is True
 assert c.get('/api/handoff').json['service_url']=='https://existing.run.app'
 with app.db() as db:assert len(db.execute('SELECT * FROM activations').fetchall())==1


def test_resource_only_cannot_bypass_limits_and_does_not_unlink_existing_repo(app):
 app.config['TEAM_ACTIVATION_LIMIT']=0;c,csrf=client(app)
 with patch('activation.enqueue'):assert activate(c,csrf).status_code==409
 app.config['TEAM_ACTIVATION_LIMIT']=36
 with patch('activation.github_identity',return_value=IDENTITY),patch('activation.enqueue'):
  assert c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf}).status_code==202
  with app.db() as db:db.execute("UPDATE activations SET status='ready',step=6 WHERE team_id='one'")
  assert activate(c,csrf).json['duplicate'] is True
 with app.db() as db:
  assert db.execute("SELECT repo FROM activations WHERE team_id='one'").fetchone()['repo']=='owner/repo'
  assert json.loads(db.execute("SELECT state FROM activation_runtime WHERE team_id='one'").fetchone()['state'])['identity']==IDENTITY


def test_connect_waits_for_ready_and_rejects_repository_already_used_by_another_team(app):
 c,csrf=client(app);other,header=client(app,'two')
 with patch('activation.github_identity',return_value=IDENTITY),patch('activation.enqueue'):
  activate(c,csrf)
  assert c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf}).status_code==409
  assert other.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':header}).status_code==202
  with app.db() as db:db.execute("UPDATE activations SET status='ready',step=6 WHERE team_id='one'")
  assert c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf}).status_code==409


def test_resource_only_upgrades_old_preview_without_repository(app):
 c,csrf=client(app)
 with app.db() as db:db.execute("INSERT INTO activations(team_id,repo,mode,status,created_at,updated_at) VALUES('one','old/repo','preview','ready',0,0)")
 with patch('activation.enqueue'):assert activate(c,csrf).status_code==202
 assert c.get('/api/status').json['activation']['mode']=='live'
 assert c.get('/api/status').json['activation']['repo']==''


# ---- GitHub link is a sub-state; resources stay ready ----
READY_OUTPUTS={'mode':'live','created_in_google_cloud':True,'github_connected':False,'github_repository':None,'service_url':'https://existing.run.app','resources':{'cloud_run_service':'s11111111'},'github_variables':{}}


def ready_resources(app,c,csrf):
 with patch('activation.enqueue'):activate(c,csrf)
 with app.db() as db:
  db.execute("UPDATE activations SET status='ready',step=6,outputs=?,created_at=1000,updated_at=1500,worker_seen_at=1500 WHERE team_id='one'",(json.dumps(READY_OUTPUTS),))


def attach(c,csrf,enqueue=None):
 with patch('activation.github_identity',return_value=IDENTITY),patch('activation.enqueue') as q:
  r=c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf})
 return r,q


def test_attach_keeps_resources_ready_outputs_handoff_and_timing_then_connects(app):
 c,csrf=client(app);ready_resources(app,c,csrf)
 r,q=attach(c,csrf);assert r.status_code==202 and q.call_args.kwargs['retry'] is True
 a=c.get('/api/status').json['activation']
 assert a['status']=='ready' and a['step']==6 and a['created_at']==1000 and a['updated_at']==1500
 assert a['github_link_status']=='queued' and a['outputs']['service_url']=='https://existing.run.app'
 h=c.get('/api/handoff');assert h.status_code==200 and h.json['github_connected'] is False and h.json['service_url']=='https://existing.run.app'
 with patch.object(Provisioner,'step') as step:assert process_live(app,'one')[1]==200;assert step.call_args.args==(5,)
 a=c.get('/api/status').json['activation']
 assert a['status']=='ready' and a['github_link_status'] is None and a['outputs']['github_connected'] is True
 assert a['created_at']==1000 and a['updated_at']==1500


def test_failed_github_link_is_link_specific_and_resources_stay_ready_and_retryable(app):
 from live_provision import ProvisionError
 c,csrf=client(app);ready_resources(app,c,csrf);attach(c,csrf)
 with patch.object(Provisioner,'step',side_effect=ProvisionError('WIF ownership conflict')):assert process_live(app,'one')[1]==200
 a=c.get('/api/status').json['activation']
 assert a['status']=='ready' and a['error'] is None and a['github_link_status']=='failed' and 'WIF' in a['github_link_error']
 assert a['outputs']['service_url']=='https://existing.run.app' and c.get('/api/handoff').status_code==200
 assert process_live(app,'one')[1] in (200,503) and c.get('/api/status').json['activation']['github_link_status']=='failed'
 r,q=attach(c,csrf);assert r.status_code==202 and q.call_args.kwargs['retry'] is True
 a=c.get('/api/status').json['activation']
 assert a['status']=='ready' and a['github_link_status']=='queued' and a['github_link_error'] is None
 assert c.get('/api/status').json['progress']['worker_last_seen_at'] is None
 with patch.object(Provisioner,'step'):assert process_live(app,'one')[1]==200
 a=c.get('/api/status').json['activation']
 assert a['github_link_status'] is None and a['outputs']['github_connected'] is True and a['created_at']==1000


def test_link_retry_is_not_duplicated_while_queued_or_leased_and_resource_only_post_does_not_relink(app):
 c,csrf=client(app);ready_resources(app,c,csrf);attach(c,csrf)
 with app.db() as db:db.execute('UPDATE activations SET worker_seen_at=? WHERE team_id=?',(int(time.time()),'one'))  # a worker picked the task up
 r,q=attach(c,csrf);assert r.json['duplicate'] is True and r.status_code==200;q.assert_not_called()
 with patch('activation.enqueue') as q:assert activate(c,csrf).json['duplicate'] is True;q.assert_not_called()
 with app.db() as db:db.execute("UPDATE activations SET github_link_status='failed' WHERE team_id='one'")
 with patch('activation.enqueue') as q:assert activate(c,csrf).json['duplicate'] is True;q.assert_not_called()
 assert c.get('/api/status').json['activation']['github_link_status']=='failed'


def test_link_worker_waiting_is_not_a_failure(app):
 from live_provision import Pending
 c,csrf=client(app);ready_resources(app,c,csrf);attach(c,csrf)
 with patch.object(Provisioner,'step',side_effect=Pending('waiting')),patch('activation.time.time',return_value=3000):assert process_live(app,'one')[1]==503
 a=c.get('/api/status').json
 assert a['activation']['status']=='ready' and a['activation']['github_link_status']=='running' and a['progress']['worker_last_seen_at']==3000
 assert a['activation']['updated_at']==1500


def test_preview_resource_only_then_attach_repo_matches_live_transition(tmp_path):
 from app import create_app,work_once
 p=create_app({'DATABASE':str(tmp_path/'p.sqlite3'),'SECRET_KEY':'x','TESTING':True,'PREVIEW':True})
 c=p.test_client();c.get('/')
 with c.session_transaction() as s:s['team_id']='preview';csrf=s['csrf']
 post=lambda **d:c.post('/api/activate',json=d,headers={'X-CSRF-Token':csrf})
 assert post(resources_only=True).status_code==202
 assert post(repo='owner/repo').status_code==409  # not ready yet, same as live
 for _ in range(6):work_once(p,0)
 assert c.get('/api/status').json['activation']['outputs']['github_connected'] is False
 assert post(resources_only=True).json['duplicate'] is True
 assert post(repo='owner/repo').status_code==202
 a=c.get('/api/status').json['activation'];assert a['repo']=='owner/repo' and a['outputs']['github_connected'] is True and a['status']=='ready'
 assert post(repo='other/repo').status_code==409
 assert post(repo='owner/repo').json['duplicate'] is True
