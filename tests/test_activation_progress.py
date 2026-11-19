import json,time
from unittest.mock import patch
from tests.test_live import app,client,IDENTITY
from activation import process_live
from live_provision import Pending


def test_status_exposes_worker_heartbeat_and_stage_age_without_runtime_state(app):
 c,csrf=client(app)
 with patch('activation.github_identity',return_value=IDENTITY),patch('activation.enqueue'):
  c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf})
 result=c.get('/api/status').json
 assert result['progress']['worker_last_seen_at'] is None
 with app.db() as db:
  db.execute("UPDATE activations SET step=1,attempts=1,worker_seen_at=123,updated_at=125,created_at=100 WHERE team_id='one'")
  db.execute('INSERT INTO events(team_id,action,at,detail) VALUES(?,?,?,?)',('one','live_step',110,'Infrastructure stage 1 completed'))
  db.execute('INSERT INTO events(team_id,action,at,detail) VALUES(?,?,?,?)',('one','live_step',120,'Waiting for Google Cloud operation or quota'))
 result=c.get('/api/status').json
 assert result['progress']=={'worker_last_seen_at':123,'step_started_at':110}
 assert abs(result['server_time']-time.time())<5
 assert 'operations' not in result and 'identity' not in result['progress']


def test_worker_checkpoint_renews_last_seen_without_advancing_stage(app):
 c,csrf=client(app)
 with patch('activation.github_identity',return_value=IDENTITY),patch('activation.enqueue'):
  c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf})
 def step(worker,n):
  worker.save(worker.state)
  with app.db() as db:row=db.execute("SELECT updated_at,lease_until FROM activations WHERE team_id='one'").fetchone()
  assert row['updated_at']==1000 and row['lease_until']==1150
  raise Pending('Waiting for Google Cloud operation or quota')
 with patch('activation.time.time',return_value=1000),patch('activation.Provisioner.step',step):
  assert process_live(app,'one')[1]==503
 result=c.get('/api/status').json
 assert result['activation']['step']==0 and result['progress']['worker_last_seen_at']==1000


def queue_live(app,c,csrf):
 with patch('activation.github_identity',return_value=IDENTITY),patch('activation.enqueue') as q:
  c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf})
 return q


def test_retry_after_failure_clears_heartbeat_and_requeues_with_fresh_time(app):
 c,csrf=client(app);queue_live(app,c,csrf)
 with app.db() as db:db.execute("UPDATE activations SET status='failed',step=2,attempts=7,created_at=100,updated_at=200,worker_seen_at=200,error='x' WHERE team_id='one'")
 with patch('activation.github_identity',return_value=IDENTITY),patch('activation.enqueue') as q:
  assert c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf}).status_code==202
 body=c.get('/api/status').json
 assert q.call_args.kwargs['retry'] is True
 assert body['activation']['status']=='queued' and body['progress']['worker_last_seen_at'] is None and abs(body['activation']['updated_at']-time.time())<5


def test_worker_claim_sets_heartbeat_and_attach_does_not_fake_one(app):
 c,csrf=client(app);queue_live(app,c,csrf)
 assert c.get('/api/status').json['progress']['worker_last_seen_at'] is None
 with patch('activation.time.time',return_value=2000),patch('activation.Provisioner.step',side_effect=Pending('wait')):process_live(app,'one')
 assert c.get('/api/status').json['progress']['worker_last_seen_at']==2000


def test_duplicate_tasks_after_stale_queue_retry_do_not_double_create(app):
 c,csrf=client(app);queue_live(app,c,csrf)
 with app.db() as db:db.execute("UPDATE activations SET updated_at=1 WHERE team_id='one'")  # queued for >600s
 with patch('activation.github_identity',return_value=IDENTITY),patch('activation.enqueue') as q:
  assert c.post('/api/activate',json={'repo':'owner/repo'},headers={'X-CSRF-Token':csrf}).status_code==202
 assert q.call_args.kwargs['retry'] is True  # a second task exists now
 created=[];inner=[]
 def step(worker,n):
  created.append(n)
  inner.append(process_live(app,'one'))  # the duplicate task arrives while the first holds the lease
 with patch('activation.Provisioner.step',step):assert process_live(app,'one')[1]==503
 assert created==[0] and inner==[({'busy':True},503)]
 assert c.get('/api/status').json['activation']['step']==1
