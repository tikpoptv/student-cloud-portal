import json,time
from unittest.mock import patch
import pytest
from app import create_app
from tests.test_oauth_setup import callback
from admin_dashboard import collect_cloud,costs_for_teams,redacted,collect_costs

@pytest.fixture
def app(tmp_path):
 a=create_app({'DATABASE':str(tmp_path/'admin.sqlite3'),'SECRET_KEY':'test','TESTING':True,'PREVIEW':True,'AUTH_MODE':'google','BASE_URL':'http://127.0.0.1:8876','TA_EMAILS':'ta@gmail.com','GOOGLE_CLIENT_ID':'test','GOOGLE_CLIENT_SECRET':'test'})
 with a.db() as c:
  c.execute("INSERT INTO teams VALUES('one','Team One','one@gmail.com','one123',1,NULL,0)")
  c.execute("INSERT INTO teams VALUES('two','Team Two','two@gmail.com','two123',1,NULL,0)")
 return a

def admin_client(app):
 c=app.test_client();assert callback(c,app,'ta@gmail.com').status_code==302
 return c

def test_only_verified_allowlisted_ta_gets_dashboard(app):
 c=app.test_client();assert c.get('/api/admin/overview').status_code==403
 assert callback(c,app,'one@gmail.com').status_code==302
 with patch('admin_dashboard.collect_cloud') as cloud:
  assert c.get('/api/admin/overview').status_code==403;cloud.assert_not_called()
  assert c.get('/api/admin/teams/two/logs').status_code==403
 c=admin_client(app)
 assert b'ta@gmail.com' in c.get('/').data
 assert c.get('/api/status').status_code==401
 app.config['TA_EMAILS']='other@gmail.com'
 assert c.get('/api/admin/overview').status_code==403

def test_admin_overview_all_teams_activity_and_cache(app):
 student=app.test_client();callback(student,app,'one@gmail.com');student.get('/api/status')
 c=admin_client(app)
 with patch('admin_dashboard.collect_cloud',return_value={'services':[],'sql':None,'jobs':[],'registry':[],'requests':None,'collected_at':123,'errors':{'sql':'HTTP 403'}}) as cloud:
  data=c.get('/api/admin/overview').json
  assert len(data['teams'])==2
  one=next(t for t in data['teams'] if t['id']=='one');two=next(t for t in data['teams'] if t['id']=='two')
  assert one['last_login'] and one['last_seen'] and one['recently_seen']
  assert two['last_login'] is None and not two['recently_seen']
  assert one['costs'] is None and data['costs']['status']=='not_configured'
  c.get('/api/admin/overview');assert cloud.call_count==1


def test_credit_observations_audited_csrf_and_restricted(app):
 c=admin_client(app)
 payload={'amount':'99.12','currency':'USD','observed_at':int(time.time()),'note':'checked console'}
 assert c.post('/api/admin/credit-observation',json=payload).status_code==403
 with c.session_transaction() as s:csrf=s['csrf']
 h={'X-CSRF-Token':csrf}
 for invalid in ('NaN','Infinity','-1','10000001'):
  assert c.post('/api/admin/credit-observation',json={**payload,'amount':invalid},headers=h).status_code==400
 assert c.post('/api/admin/credit-observation',json={**payload,'observed_at':int(time.time())+1000},headers=h).status_code==400
 assert c.post('/api/admin/credit-observation',json=payload,headers=h).status_code==200
 with app.db() as db:
  assert db.execute('SELECT amount FROM credit_observations').fetchone()['amount']=='99.12'
  assert db.execute("SELECT COUNT(*) n FROM admin_audit WHERE action='credit_observation'").fetchone()['n']==1


def test_logs_are_server_scoped_and_redacted(app):
 c=admin_client(app)
 entry={'timestamp':'2026-11-19T01:00:00Z','severity':'ERROR','textPayload':'password=abc token warning postgres://user:pass@host/db Bearer abc.def','jsonPayload':{'secret':'never-return'},'httpRequest':{'requestUrl':'https://x?secret=hidden','status':500}}
 with patch('admin_dashboard.GoogleAPI') as api:
  api.return_value.request.return_value={'entries':[entry]}
  result=c.get('/api/admin/teams/one/logs?prefix=two123').json
  body=api.return_value.request.call_args.args[2];assert 'one123' in body['filter'] and 'two123' not in body['filter']
  encoded=json.dumps(result);assert 'abc' not in encoded and 'user:pass' not in encoded and 'never-return' not in encoded and '?secret' not in encoded
  assert result['entries'][0]['http']=={'status':500}
  assert c.get('/api/admin/teams/one/logs?severity=ERROR%20OR%20true').status_code==400
  assert c.get('/api/admin/teams/missing/logs').status_code==404


def test_cloud_inventory_never_returns_env_or_secret_contents():
 class API:
  def request(self,m,url,body=None,params=None):
   if '/services' in url:return {'services':[{'name':'projects/p/services/one123','labels':{'cpe334-team':'one'},'terminalCondition':{'state':'CONDITION_SUCCEEDED'},'template':{'containers':[{'image':'student/app','env':[{'name':'PASSWORD','value':'never-return'}]}]}}]}
   return {}
 data=collect_cloud(API());assert data['services'][0]['ready'] is True
 assert 'never-return' not in json.dumps(data)


def test_costs_exact_attribution_currency_and_shared_bucket():
 base={'service':'SQL','gross':5,'credits':-4,'net':1,'currency':'USD','usage_through':'100','export_through':'200','labels':{}}
 rows=[{**base,'resource':'projects/p/instances/one123-pg'},{**base,'resource':'projects/p/services/one1234'},{**base,'resource':'unknown','labels':{'cpe334-team':'two'},'currency':'THB'}]
 data=costs_for_teams({'status':'available','rows':rows},[{'id':'one','prefix':'one123'},{'id':'two','prefix':'two123'}])
 assert data['groups']['one']['USD']['gross']==5
 assert data['groups']['two']['THB']['net']==1
 assert data['unallocated']['USD']['gross']==5
 assert data['totals']['USD']=={'gross':10,'credits':-8,'net':2}
 assert data['usage_through']==100


def test_billing_query_bounded_parameterized_and_validated():
 class API:
  def request(self,m,url,body=None,params=None):
   assert body['maximumBytesBilled']=='1000000000'
   assert '@project' in body['query'] and body['queryParameters'][0]['parameterValue']['value']=='cpe-se-course-2026'
   return {'jobComplete':True,'rows':[{'f':[{'v':v} for v in ['projects/p/services/a','Cloud Run',None,'USD','2','-1','1','100','200']]}]}
 config={'BILLING_EXPORT_TABLE':'course-project.billing.gcp_billing_export_resource_v1_123','BILLING_EXPORT_LOCATION':'US'}
 data=collect_costs(config,API());assert data['rows'][0]['gross']==2
 assert collect_costs({**config,'BILLING_EXPORT_TABLE':'x`; DROP'})['status']=='invalid_configuration'
 assert collect_costs({**config,'BILLING_EXPORT_TABLE':''})['status']=='not_configured'

def test_pending_billing_rechecks_after_one_minute_but_available_keeps_cache(app):
 c=admin_client(app);now=int(time.time())
 pending={'status':'awaiting_export','groups':{},'collected_at':now-61}
 with app.db() as db:
  db.execute('INSERT INTO admin_snapshots VALUES(?,?,?)',('costs',json.dumps(pending),now-61))
 with patch('admin_dashboard.collect_cloud',return_value={'services':[],'sql':[],'jobs':[],'registry':[],'requests':{},'collected_at':now,'errors':{}}),patch('admin_dashboard.collect_costs',return_value={'status':'available','rows':[],'collected_at':now}) as collect:
  assert c.get('/api/admin/overview').json['costs']['status']=='available'
  assert collect.call_count==1
  with app.db() as db:db.execute("UPDATE admin_snapshots SET at=? WHERE kind='costs'",(now-120,))
  assert c.get('/api/admin/overview').status_code==200
  assert collect.call_count==1

def test_missing_export_is_pending_without_provider_error():
 from live_provision import CloudError
 class Missing:
  def request(self,*args,**kwargs):raise CloudError(404)
 config={'BILLING_EXPORT_TABLE':'course-project.billing.gcp_billing_export_resource_v1_123','BILLING_EXPORT_LOCATION':'US'}
 result=collect_costs(config,Missing());assert result['status']=='awaiting_export' and 'error' not in result


def test_billing_sql_is_valid_shape_no_array_group_by_or_alias_shadow():
 import re as _re
 seen={}
 class API:
  def request(self,m,url,body=None,params=None):
   seen.update(body);return {'jobComplete':True,'rows':[{'f':[{'v':v} for v in ['projects/p/services/a','Cloud Run','one','USD','2','-1','1','100','200']]}]}
 config={'BILLING_EXPORT_TABLE':'course-project.billing.gcp_billing_export_resource_v1_123','BILLING_EXPORT_LOCATION':'US'}
 data=collect_costs(config,API());q=seen['query']
 assert data['rows'][0]['labels']=={'cpe334-team':'one'}
 group=_re.search(r'GROUP BY(.*)$',q,_re.S).group(1)
 exprs=[e.strip() for e in group.split(',')]
 assert exprs and all(e.lower()!='labels' and 'ARRAY' not in e.upper() for e in exprs)
 assert 'ARRAY(' not in q.upper().replace('ARRAY (','ARRAY(')
 source={'resource','service','labels','currency','cost','credits','project','usage_end_time','export_time','system_labels','tags'}
 aliases=_re.findall(r'\bAS\s+(\w+)\s*(?:,|\n|FROM)',q)
 assert aliases and not (set(a.lower() for a in aliases)&source)
 assert '@project' in q and 'maximumBytesBilled' in seen
 for e in exprs:assert e in ('resource.name','service.description','team_label','currency')


@pytest.mark.parametrize('raw,secret',[
 ('Authorization: Basic dXNlcjpwYXNzd29yZA==','dXNlcjpw'),
 ('Authorization: Digest user=a response=zzz','zzz'),
 ('token ya29.a0AfH6SMBxyzABC-def_123','ya29.a0'),
 ('x ghp_'+'a'*36,'ghp_aaaa'),('x gho_'+'b'*36,'gho_bbbb'),('github_pat_'+'C'*40,'github_pat_CCC'),
 ('Cookie: sid=abc123; other=zzz','abc123'),('Set-Cookie: sess=qq77; HttpOnly','qq77'),
 ('password: hunter two','two'),('password="two words" end','words'),
 ('jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcSIG','eyJzdWIi'),
 ('key AKIAIOSFODNN7EXAMPLE','AKIAIOSFODNN7'),
])
def test_redacted_masks_secret_forms(raw,secret):
 out=redacted(raw);assert secret not in out and '[REDACTED]' in out


def test_redacted_leaves_ordinary_logs_unchanged():
 for line in ('GET /api/status 200 12ms','Token expired for user, retry later','Basic auth is disabled','Deploy finished: revision one123-00005 ready','cookie banner rendered'):
  assert redacted(line)==line


def test_forged_label_cannot_shift_cost_to_other_team():
 base={'service':'Run','gross':5,'credits':0,'net':5,'currency':'USD','usage_through':'1','export_through':'2'}
 rows=[{**base,'resource':'projects/p/services/one123','labels':{'cpe334-team':'two'}},
       {**base,'resource':'projects/p/services/one123','labels':{'cpe334-team':'one'}}]
 data=costs_for_teams({'status':'available','rows':rows},[{'id':'one','prefix':'one123'},{'id':'two','prefix':'two123'}])
 assert 'two' not in data['groups'] and data['groups']['one']['USD']['gross']==5
 assert data['unallocated']['USD']['gross']==5 and data['label_mismatch']==1
