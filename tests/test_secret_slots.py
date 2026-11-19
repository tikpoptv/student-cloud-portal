import json,re
import pytest
from live_provision import Provisioner,ProvisionError,SLOT_COUNT,PROJECT
import ops_backfill_secret_slots as backfill
from admin_dashboard import costs_for_teams

SM='https://secretmanager.googleapis.com/v1/'
SQL='https://sqladmin.googleapis.com/sql/v1beta4/'
ACCESSOR='roles/secretmanager.secretAccessor';ADDER='roles/secretmanager.secretVersionAdder'


class FakeCloud:
 """Stateful fake of Secret Manager + Cloud SQL ownership reads + secret IAM policies."""
 def __init__(self):
  self.secrets={};self.policies={};self.calls=[]
 def seed(self,prefix,gid,suffixes=('database-url','database-password','admin-password','demo-password')):
  for s in suffixes:
   self.secrets[f'projects/{PROJECT}/secrets/{prefix}-{s}']={'labels':{'cpe334-team':gid}}
 def request(self,method,url,body=None,missing=False,params=None):
  self.calls.append((method,url))
  if url.startswith(SQL):return {'settings':{'userLabels':{'cpe334-team':self.gid}}} if self.gid else {}
  path=url[len(SM):] if url.startswith(SM) else url
  if url.endswith(':getIamPolicy'):
   return json.loads(json.dumps(self.policies.get(path[:-len(':getIamPolicy')],{'bindings':[],'etag':'e'})))
  if url.endswith(':setIamPolicy'):
   self.policies[path[:-len(':setIamPolicy')]]=body['policy'];return {}
  if not url.startswith(SM) and method=='GET':return {'labels':{'cpe334-team':self.gid},'description':'CPE334 portal group:%s;prefix:%s;v1'%(self.gid,self.gid+'123' if self.gid in('one','two') else '')}
  if method=='POST' and path.endswith('/secrets'):
   name=f'{path}/{params["secretId"]}'
   assert 'versions' not in json.dumps(body)
   self.secrets[name]={'labels':body['labels']};return {}
  if method=='GET':
   if path in self.secrets:return self.secrets[path]
   if missing:return None
   raise AssertionError('unexpected GET '+url)
  raise AssertionError((method,url))
 gid=None

def team(gid='one',prefix='one123',members=('partner@gmail.com',)):
 return {'id':gid,'prefix':prefix,'email':gid+'@gmail.com','member_emails':[gid+'@gmail.com',*members]}

def prov(cloud,t=None):
 t=t or team();cloud.gid=t['id']
 return Provisioner(t,{},{},lambda _:None,cloud)

def slot(prefix,n):return f'projects/{PROJECT}/secrets/{prefix}-app-secret-{n}'
def roles(cloud,path):return {b['role']:set(b['members']) for b in cloud.policies.get(path,{}).get('bindings',[])}


def test_slots_created_with_exact_roles_and_no_versions():
 c=FakeCloud();p=prov(c);p.slot_secrets()
 assert SLOT_COUNT==5
 names=[k for k in c.secrets if 'app-secret' in k]
 assert sorted(names)==sorted(slot('one123',n) for n in range(1,6))
 assert all(c.secrets[n]['labels']['cpe334-team']=='one' for n in names)
 assert not any('versions' in u or 'addVersion' in u for _,u in c.calls)
 for n in names:
  r=roles(c,n)
  assert set(r)=={ACCESSOR,ADDER}
  assert r[ACCESSOR]=={'serviceAccount:one123-runner@'+PROJECT+'.iam.gserviceaccount.com','serviceAccount:one123-deployer@'+PROJECT+'.iam.gserviceaccount.com','user:one@gmail.com','user:partner@gmail.com'}
  assert r[ADDER]=={'user:one@gmail.com','user:partner@gmail.com'}  # members only, never service accounts
 blob=json.dumps(c.policies)
 assert 'secretVersionManager' not in blob and 'secretmanager.admin' not in blob and 'roles/owner' not in blob

def test_slots_idempotent_and_other_group_untouched():
 c=FakeCloud();c.seed('two123','two')
 other=slot('two123',1);c.secrets[other]={'labels':{'cpe334-team':'two'}};c.policies[other]={'bindings':[{'role':ACCESSOR,'members':['user:two@gmail.com']}]}
 before=json.dumps(c.policies[other]);p=prov(c);p.slot_secrets()
 snap=(json.dumps(c.secrets,sort_keys=True),json.dumps(c.policies,sort_keys=True))
 c.calls.clear();p.slot_secrets()
 assert snap==(json.dumps(c.secrets,sort_keys=True),json.dumps(c.policies,sort_keys=True))
 assert not any(u.endswith(':setIamPolicy') or m=='POST' and u.endswith('/secrets') for m,u in c.calls)
 assert json.dumps(c.policies[other])==before
 assert not any(k.startswith(f'projects/{PROJECT}/secrets/two123-database') and k in c.policies for k in c.secrets)

def test_existing_credentials_secrets_get_no_policy_change():
 c=FakeCloud();c.seed('one123','one');prov(c).slot_secrets()
 assert not any('database' in k for k in c.policies)

def test_foreign_existing_slot_is_refused_without_mutation():
 c=FakeCloud();c.secrets[slot('one123',1)]={'labels':{'cpe334-team':'someone-else'}}
 with pytest.raises(ProvisionError):prov(c).slot_secrets()
 assert not c.policies and len([k for k in c.secrets if 'app-secret' in k])==1

def test_grant_and_revoke_members_cover_slots_and_touch_only_that_member():
 c=FakeCloud();p=prov(c);p.slot_secrets()
 for k in ('admin-password','demo-password'):c.secrets[f'projects/{PROJECT}/secrets/one123-{k}']={'labels':{'cpe334-team':'one'}}
 other=slot('two123',1);c.secrets[other]={'labels':{'cpe334-team':'two'}};c.policies[other]={'bindings':[{'role':ADDER,'members':['user:partner@gmail.com']}]}
 slots=[(u,r) for u,r,_ in p.member_targets() if 'app-secret' in u]
 assert len(slots)==2*SLOT_COUNT and {r for _,r in slots}=={ACCESSOR,ADDER} and not any('two123' in u for u,_ in slots)
 p.grant_members(['user:newbie@gmail.com'])
 for n in range(1,6):
  r=roles(c,slot('one123',n))
  assert 'user:newbie@gmail.com' in r[ACCESSOR] and 'user:newbie@gmail.com' in r[ADDER]
 p.revoke_members(['user:partner@gmail.com','serviceAccount:evil'])
 for n in range(1,6):
  r=roles(c,slot('one123',n))
  assert 'user:partner@gmail.com' not in r[ACCESSOR] and 'user:partner@gmail.com' not in r[ADDER]
  assert {'user:one@gmail.com','user:newbie@gmail.com'}<=r[ADDER]<=({'user:one@gmail.com','user:newbie@gmail.com'})
  assert any(m.startswith('serviceAccount:one123-runner') for m in r[ACCESSOR])
 assert c.policies[other]['bindings'][0]['members']==['user:partner@gmail.com']
 assert 'secretVersionManager' not in json.dumps(c.policies) and 'secretmanager.admin' not in json.dumps(c.policies)

def test_member_grants_tolerate_group_without_slots_yet():
 c=FakeCloud();p=prov(c)
 for k in ('admin-password','demo-password'):c.secrets[f'projects/{PROJECT}/secrets/one123-{k}']={'labels':{'cpe334-team':'one'}}
 assert not any('app-secret' in u for u,_,_ in p.member_targets())
 p.grant_members()

def test_dashboard_cost_attribution_recognises_slots():
 base={'service':'Secret Manager','gross':1,'credits':0,'net':1,'currency':'USD','usage_through':'1','export_through':'1','labels':{}}
 rows=[{**base,'resource':'projects/p/secrets/one123-app-secret-3'},{**base,'resource':'projects/p/secrets/one123-app-secret-9'}]
 data=costs_for_teams({'status':'available','rows':rows},[{'id':'one','prefix':'one123'}])
 assert data['groups']['one']['USD']['gross']==1 and data['unallocated']['USD']['gross']==1

# ---- ops_backfill_secret_slots ----
def groups():return [(team(),{'identity':None,'operations':{}}),(team('two','two123',()),{'identity':None,'operations':{}})]

class MultiCloud(FakeCloud):
 def request(self,method,url,body=None,**kw):
  if url.startswith(SQL):
   self.calls.append((method,url));return {'settings':{'userLabels':{'cpe334-team':'one' if '/one123-pg' in url else 'two'}}}
  return super().request(method,url,body,**kw)

def test_backfill_default_is_dry_run_and_changes_nothing():
 c=MultiCloud();out=[]
 assert backfill.main([],api=c,groups=groups(),out=out.append)==0
 assert not c.secrets and not c.policies
 assert not any(m=='POST' and (u.endswith('/secrets') or u.endswith(':setIamPolicy')) for m,u in c.calls)
 text='\n'.join(out);assert 'DRY-RUN' in text and 'would create secret one123-app-secret-1' in text and 'would create secret two123-app-secret-5' in text
 assert text.count('would create secret')==10

def test_backfill_apply_creates_slots_and_is_idempotent():
 c=MultiCloud();out=[]
 assert backfill.main(['--apply'],api=c,groups=groups(),out=out.append)==0
 assert len([k for k in c.secrets if 'app-secret' in k])==10
 assert roles(c,slot('two123',2))[ADDER]=={'user:two@gmail.com'}
 assert roles(c,slot('one123',2))[ADDER]=={'user:one@gmail.com','user:partner@gmail.com'}
 out.clear();c.calls.clear()
 assert backfill.main(['--apply'],api=c,groups=groups(),out=out.append)==0
 assert not any(m=='POST' and (u.endswith('/secrets') or u.endswith(':setIamPolicy')) for m,u in c.calls)
 assert all('already up to date' in l for l in out[1:])

def test_backfill_group_filter_and_foreign_slot_reported_not_applied():
 c=MultiCloud();c.secrets[slot('one123',2)]={'labels':{'cpe334-team':'x'}};out=[]
 assert backfill.main(['--apply','--group','one'],api=c,groups=groups(),out=out.append)==1
 assert 'FAILED' in '\n'.join(out) and not any('two123' in k for k in c.secrets)
 assert not c.policies.get(slot('one123',2))

def test_backfill_dry_run_reports_missing_iam_on_existing_slots():
 c=MultiCloud();prov(c).slot_secrets();c.policies.clear();out=[]
 backfill.main(['--group','one'],api=c,groups=groups(),out=out.append)
 assert 'would set IAM policy on one123-app-secret-1' in '\n'.join(out) and not c.policies
