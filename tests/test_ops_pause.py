"""Pause / resume / teardown scripts against a fake cloud. No network, no gcloud."""
import ops_pause_team as pause,ops_resume_team as resume,ops_teardown_team as teardown
import ops_common as common
from live_provision import PROJECT,REGION,ROOTS,NUMBER

TEAM={'id':'one','name':'One','email':'one@gmail.com','prefix':'one123','member_emails':['one@gmail.com','b@gmail.com']}
OTHER={'id':'two','name':'Two','email':'two@gmail.com','prefix':'two123','member_emails':['two@gmail.com']}


def marker(t):return f"CPE334 portal group:{t['id']};prefix:{t['prefix']};v1"


class FakeCloud:
    """Holds resources keyed by URL; records every call. Descriptions/labels mirror the Provisioner conventions."""
    def __init__(self,teams=(TEAM,)):
        self.res={};self.calls=[];self.policies={}
        for t in teams:self.seed(t)
    def seed(self,t,foreign=()):
        p=t['prefix'];gid=t['id'];parent=f'projects/{PROJECT}/locations/{REGION}'
        lab={'labels':{'cpe334-team':gid}}
        self.res[ROOTS['run']+parent+'/services/'+p]={**lab,'template':{'scaling':{'minInstanceCount':2}}}
        self.res[ROOTS['run']+parent+'/jobs/'+p+'-migrate']=dict(lab)
        self.res[ROOTS['sql']+f'projects/{PROJECT}/instances/{p}-pg']={'settings':{'userLabels':lab['labels'],'activationPolicy':'ALWAYS'},'state':'RUNNABLE'}
        self.res[ROOTS['ar']+parent+'/repositories/'+p]=dict(lab)
        for s in ('database-password','database-url','admin-password','demo-password','app-secret-1','app-secret-5'):
            self.res[ROOTS['sm']+f'projects/{PROJECT}/secrets/{p}-{s}']=dict(lab)
        pool=ROOTS['iam']+f'projects/{NUMBER}/locations/global/workloadIdentityPools/{p}-pool'
        d={'description':marker(t)}
        self.res[pool]=dict(d);self.res[pool+'/providers/'+p+'-provider']=dict(d)
        self.res[ROOTS['log']+f'projects/{PROJECT}/locations/global/buckets/_Default/views/{p}']=dict(d)
        for n in ('runner','deployer'):
            self.res[ROOTS['iam']+f'projects/{PROJECT}/serviceAccounts/{p}-{n}@{PROJECT}.iam.gserviceaccount.com']=dict(d)
        for url in foreign:
            key=next(k for k in self.res if k.endswith(url))
            self.res[key]={'labels':{'cpe334-team':'someone-else'},'description':'not ours','settings':{'userLabels':{'cpe334-team':'someone-else'},'activationPolicy':'ALWAYS'}}
    def request(self,method,url,body=None,missing=False,params=None):
        self.calls.append((method,url,body))
        if url.endswith(':getIamPolicy'):
            return {'bindings':[{'role':'roles/serviceusage.serviceUsageConsumer','members':['user:one@gmail.com','user:keep@gmail.com']}],'etag':'e'}
        if url.endswith(':setIamPolicy'):self.policies['project']=body['policy'];return {}
        if method=='GET':
            if url in self.res:return self.res[url]
            if missing:return None
            raise AssertionError('unexpected GET '+url)
        if method=='PATCH':
            if 'settings' in (body or {}):self.res[url]['settings']['activationPolicy']=body['settings']['activationPolicy']
            return {}
        if method=='DELETE':
            assert url in self.res,url;del self.res[url];return {}
        raise AssertionError((method,url))
    def writes(self):
        return [c for c in self.calls if c[0] in ('PATCH','DELETE') or (c[0]=='POST')]


def lines():
    buf=[];return buf,buf.append


def sql(cloud,t=TEAM):return cloud.res[ROOTS['sql']+f"projects/{PROJECT}/instances/{t['prefix']}-pg"]['settings']['activationPolicy']


def test_pause_dry_run_makes_no_writes():
    cloud=FakeCloud();buf,out=lines()
    assert pause.main(['--group','one','--scale-run-to-zero'],cloud,[TEAM],out)==0
    assert not [c for c in cloud.calls if c[0]!='GET'],cloud.calls
    assert sql(cloud)=='ALWAYS' and any('would PATCH SQL' in l for l in buf) and any('DRY-RUN' in l for l in buf)


def test_pause_apply_then_resume_toggles_only_own_sql():
    cloud=FakeCloud((TEAM,OTHER));out=lines()[1]
    assert pause.main(['--group','one','--apply'],cloud,[TEAM,OTHER],out)==0
    assert sql(cloud)=='NEVER' and sql(cloud,OTHER)=='ALWAYS'
    patched=[c[1] for c in cloud.calls if c[0]=='PATCH']
    assert patched==[ROOTS['sql']+f'projects/{PROJECT}/instances/one123-pg']
    assert resume.main(['--group','one','--apply'],cloud,[TEAM,OTHER],out)==0 and sql(cloud)=='ALWAYS'
    n=len(cloud.calls);assert resume.main(['--group','one','--apply'],cloud,[TEAM],out)==0
    assert not [c for c in cloud.calls[n:] if c[0]!='GET']  # already ALWAYS: idempotent


def test_pause_scale_run_to_zero_and_resume_dry_run():
    cloud=FakeCloud();out=lines()[1]
    pause.main(['--group','one','--apply','--scale-run-to-zero'],cloud,[TEAM],out)
    run=[c for c in cloud.calls if c[0]=='PATCH' and '/services/' in c[1]]
    assert run and run[0][2]=={'template':{'scaling':{'minInstanceCount':0}}}
    n=len(cloud.calls);resume.main(['--group','one'],cloud,[TEAM],out)
    assert not [c for c in cloud.calls[n:] if c[0]!='GET']


def test_pause_refuses_foreign_sql_instance():
    cloud=FakeCloud();cloud.seed(TEAM,foreign=('/instances/one123-pg',));buf,out=lines()
    assert pause.main(['--group','one','--apply'],cloud,[TEAM],out)==2
    assert not [c for c in cloud.calls if c[0]!='GET'] and any('REFUSED' in l for l in buf)


def test_selection_rules():
    out=lines()[1]
    assert pause.main([],FakeCloud(),[TEAM],out)==2
    assert pause.main(['--group','nope'],FakeCloud(),[TEAM],out)==2
    assert teardown.main(['--all-ready'],FakeCloud(),[TEAM],out)==2
    assert teardown.main(['--all-ready','--apply','--confirm-delete','one123'],FakeCloud(),[TEAM],out)==2


def test_teardown_dry_run_lists_everything_and_deletes_nothing():
    cloud=FakeCloud();buf,out=lines();before=dict(cloud.res)
    assert teardown.main(['--group','one'],cloud,[TEAM],out)==0
    assert cloud.res==before and not [c for c in cloud.calls if c[0] not in ('GET',)]
    text='\n'.join(buf)
    for word in ('Cloud Run service','Cloud Run job','Cloud SQL instance','Artifact Registry repo','app-secret-5','WIF provider','WIF pool','log view','service account runner','service account deployer'):assert word in text


def test_teardown_requires_typed_confirmation():
    cloud=FakeCloud();buf,out=lines();before=dict(cloud.res)
    assert teardown.main(['--group','one','--apply'],cloud,[TEAM],out)==2
    assert teardown.main(['--group','one','--apply','--confirm-delete','wrong'],cloud,[TEAM],out)==2
    assert teardown.main(['--group','one','--apply','--confirm-delete','one123','--confirm-delete','zzz'],cloud,[TEAM],out)==2
    assert cloud.res==before and not cloud.calls  # refused before any API call


def test_teardown_apply_deletes_only_owned_team_resources():
    cloud=FakeCloud((TEAM,OTHER));out=lines()[1]
    assert teardown.main(['--group','one','--apply','--confirm-delete','one123'],cloud,[TEAM,OTHER],out)==0
    assert not [k for k in cloud.res if 'one123' in k]
    assert len([k for k in cloud.res if 'two123' in k])==len([k for k in FakeCloud((OTHER,)).res])
    deleted=[c[1] for c in cloud.calls if c[0]=='DELETE']
    assert deleted and all('one123' in u for u in deleted)
    # project IAM: only this team's members removed, others kept; SAs deleted after the IAM cleanup
    order=[c[0]+(':sa' if '/serviceAccounts/' in c[1] and c[0]=='DELETE' else '') for c in cloud.calls]
    assert order.index('POST')<order.index('DELETE:sa')
    members=cloud.policies['project']['bindings'][0]['members']
    assert members==['user:keep@gmail.com']


def test_teardown_refuses_whole_team_when_any_resource_is_foreign():
    cloud=FakeCloud();cloud.seed(TEAM,foreign=('/secrets/one123-app-secret-5','/services/one123'));buf,out=lines()
    assert teardown.main(['--group','one','--apply','--confirm-delete','one123'],cloud,[TEAM],out)==2
    assert not [c for c in cloud.calls if c[0]!='GET'],cloud.calls
    assert any('REFUSED' in l for l in buf)


def test_dry_run_guard_blocks_writes():
    import pytest
    guard=common.ReadOnlyAPI(FakeCloud())
    with pytest.raises(RuntimeError):guard.request('DELETE','https://x/y')
    with pytest.raises(RuntimeError):guard.request('PATCH','https://x/y',{})
