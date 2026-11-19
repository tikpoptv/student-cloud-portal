"""Backfill per-group student secret slots (<prefix>-app-secret-1..5) for groups that are already ready.

DEFAULT IS --dry-run: it only reads from Google Cloud and prints what it would create/grant.
Nothing is changed unless --apply is passed explicitly. Uses the same Provisioner code as activation.
Usage: python ops_backfill_secret_slots.py [--dry-run | --apply] [--group TEAM_ID ...]
"""
import argparse,json,sys
from live_provision import Provisioner,ProvisionError,Pending,CloudError,ROOTS,PROJECT,LABEL


class DryRunAPI:
    """Forwards reads; simulates and records writes so the real Provisioner logic can run end to end."""
    def __init__(self,api):
        self.api=api;self.actions=[];self.created={};self.policies={}
    def request(self,method,url,body=None,missing=False,params=None):
        if url.startswith(ROOTS['sm']) and url.endswith('/secrets') and method=='POST':
            name=params['secretId'];self.actions.append('create secret '+name)
            self.created[url+'/'+name]={'name':name,'labels':body['labels']};return {}
        if url in self.created and method=='GET':return self.created[url]
        if url.endswith(':getIamPolicy'):
            resource=url[:-len(':getIamPolicy')]
            if resource in self.created:return json.loads(json.dumps(self.policies.get(resource,{'bindings':[]})))
            return self.api.request(method,url,body,missing=missing,params=params)
        if url.endswith(':setIamPolicy'):
            resource=url[:-len(':setIamPolicy')]
            self.actions.append('set IAM policy on '+resource.split('/secrets/')[-1])
            self.policies[resource]=body['policy'];return {}
        if method=='GET' or (method=='POST' and url.endswith(':getIamPolicy')):
            return self.api.request(method,url,body,missing=missing,params=params)
        raise RuntimeError('dry-run refused a write: '+method+' '+url)


class RecordingAPI:
    """Apply mode: forwards everything and records the mutations that really happened."""
    def __init__(self,api):self.api=api;self.actions=[]
    def request(self,method,url,body=None,**kw):
        result=self.api.request(method,url,body,**kw)
        if url.endswith('/secrets') and method=='POST':self.actions.append('create secret '+kw['params']['secretId'])
        if url.endswith(':setIamPolicy'):self.actions.append('set IAM policy on '+url[:-len(':setIamPolicy')].split('/secrets/')[-1])
        return result


def run_group(team,state,api,apply):
    """Returns (list of actions, error-or-None) for one group."""
    wrapper=RecordingAPI(api) if apply else DryRunAPI(api)
    p=Provisioner(team,state.get('identity'),state,lambda _:None,wrapper)
    try:
        p.owned(p.req('GET',ROOTS['sql']+f'projects/{PROJECT}/instances/{p.p}-pg'))  # group really is provisioned
        p.slot_secrets()
    except (ProvisionError,Pending,CloudError) as err:
        return wrapper.actions,str(err)
    return wrapper.actions,None


def load_groups(only=None):  # pragma: no cover - needs the hosted portal database
    from pathlib import Path
    from urllib.parse import quote
    import database
    from membership import member_emails
    secret=json.loads(Path('private/hosted-secrets.json').read_text())
    url='postgresql://portal:'+quote(secret['database_password'],safe='')+'@127.0.0.1:55440/portal'
    groups=[]
    with database.connect('',url) as c:
        rows=c.execute("SELECT a.team_id,t.name,t.email,t.prefix,r.state FROM activations a JOIN teams t ON t.id=a.team_id JOIN activation_runtime r ON r.team_id=a.team_id WHERE a.mode='live' AND a.status='ready' AND t.enabled=1").fetchall()
        for r in rows:
            if only and r['team_id'] not in only:continue
            team={'id':r['team_id'],'name':r['name'],'email':r['email'],'prefix':r['prefix']}
            team['member_emails']=member_emails(c,team)
            groups.append((team,json.loads(r['state'])))
    return groups


def main(argv=None,api=None,groups=None,out=print):
    ap=argparse.ArgumentParser(description=__doc__.split('\n')[0])
    mode=ap.add_mutually_exclusive_group()
    mode.add_argument('--dry-run',action='store_true',help='default: only print what would change')
    mode.add_argument('--apply',action='store_true',help='actually create slots and grant IAM')
    ap.add_argument('--group',action='append',help='limit to this team id (repeatable)')
    args=ap.parse_args(argv)
    apply=args.apply
    if groups is None:groups=load_groups(args.group)
    elif args.group:groups=[g for g in groups if g[0]['id'] in args.group]
    if api is None:
        from live_provision import GoogleAPI
        api=GoogleAPI()
    out(('APPLY' if apply else 'DRY-RUN (no changes; pass --apply to execute)')+f': {len(groups)} group(s)')
    failures=0
    for team,state in groups:
        actions,error=run_group(team,state,api,apply)
        for a in actions:out(f"  {team['prefix']}: {'did' if apply else 'would'} {a}")
        if error:failures+=1;out(f"  {team['prefix']}: SKIPPED/FAILED - {error}")
        elif not actions:out(f"  {team['prefix']}: already up to date")
    return 1 if failures else 0


if __name__=='__main__':
    sys.exit(main())
