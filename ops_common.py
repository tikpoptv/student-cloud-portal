"""Shared helpers for the team lifecycle scripts (ops_pause_team / ops_resume_team / ops_teardown_team).

Safety model:
* Every script is a DRY-RUN unless --apply is passed. In dry-run the API is wrapped so any write raises.
* A resource is only touched if it passes Provisioner.owned() (same label/marker check the provisioner uses).
* Nothing here is ever run by the web/worker; operators run it from a laptop with the Cloud SQL proxy up.
"""
import json
import re
import subprocess
from live_provision import Provisioner,ProvisionError,Pending,CloudError,GoogleAPI,ROOTS,PROJECT,REGION,NUMBER

READ_POSTS=(':getIamPolicy',)
CRM=f'https://cloudresourcemanager.googleapis.com/v1/projects/{PROJECT}'


class ReadOnlyAPI:
    """Dry-run guard: forwards reads, raises on anything that could change the cloud."""
    def __init__(self,api):self.api=api
    def request(self,method,url,body=None,**kw):
        if method=='GET' or (method=='POST' and url.endswith(READ_POSTS)):return self.api.request(method,url,body,**kw)
        raise RuntimeError('dry-run refused a write: '+method+' '+url)


def make_api(account):  # pragma: no cover - needs gcloud and the network
    """GoogleAPI using the operator's own gcloud login (never a hardcoded account)."""
    if not account:return GoogleAPI()
    import requests
    token=subprocess.run(['gcloud','auth','print-access-token','--account='+account],capture_output=True,text=True,timeout=30,check=True).stdout.strip()
    session=requests.Session();session.headers['Authorization']='Bearer '+token
    return GoogleAPI(session)


def load_groups(ids=None,all_ready=False):  # pragma: no cover - needs the hosted portal database via the proxy
    """Team dicts like ops_backfill_secret_slots.load_groups. Needs Cloud SQL proxy at 127.0.0.1:55440.

    --all-ready: live teams whose activation status is ready. --group ids: those teams even when not ready
    (a failed activation can leave partial resources that a teardown must be able to find).
    """
    from pathlib import Path
    from urllib.parse import quote
    import database
    from membership import member_emails
    secret=json.loads(Path('private/hosted-secrets.json').read_text())
    url='postgresql://portal:'+quote(secret['database_password'],safe='')+'@127.0.0.1:55440/portal'
    groups=[]
    with database.connect('',url) as c:
        if all_ready:
            rows=c.execute("SELECT t.id,t.name,t.email,t.prefix FROM teams t JOIN activations a ON a.team_id=t.id WHERE a.mode='live' AND a.status='ready' AND t.enabled=1").fetchall()
        else:
            rows=[r for r in c.execute("SELECT id,name,email,prefix FROM teams").fetchall() if r['id'] in (ids or [])]
        for r in rows:
            if ids and r['id'] not in ids:continue
            team={'id':r['id'],'name':r['name'],'email':r['email'],'prefix':r['prefix']}
            team['member_emails']=member_emails(c,team)
            groups.append(team)
    return groups


def add_common_args(ap,allow_all_ready=True):
    ap.add_argument('--group',action='append',metavar='TEAM_ID',help='team id (repeatable)')
    if allow_all_ready:ap.add_argument('--all-ready',action='store_true',help='every live team whose activation is ready (needs the Cloud SQL proxy)')
    ap.add_argument('--apply',action='store_true',help='actually change things; without it this is a dry-run')
    ap.add_argument('--account',help='gcloud account to use (default: application default credentials)')


def select_groups(args,groups,out):
    """Returns the list of teams to act on, or None after printing a usage problem."""
    all_ready=getattr(args,'all_ready',False)
    if not args.group and not all_ready:
        out('ERROR: pass --group TEAM_ID (repeatable)'+(' or --all-ready' if getattr(args,'allow_all',True) else ''));return None
    if groups is None:groups=load_groups(args.group,all_ready)
    if args.group:
        known={g['id'] for g in groups};missing=[g for g in args.group if g not in known]
        if missing:out('ERROR: unknown or not-ready team id(s): '+', '.join(missing));return None
        groups=[g for g in groups if g['id'] in args.group]
    if not groups:out('ERROR: no teams selected');return None
    return groups


def provisioner(team,api):
    return Provisioner(team,None,{},lambda _:None,api)


def check_owned(p,api,url,description=False):
    """-> ('absent'|'owned'|'foreign', object). Uses the Provisioner's own ownership rule."""
    obj=api.request('GET',url,missing=True)
    if obj is None:return 'absent',None
    try:p.owned(obj,description)
    except ProvisionError:return 'foreign',obj
    return 'owned',obj


def sql_url(p):return ROOTS['sql']+f'projects/{PROJECT}/instances/{p.p}-pg'


def set_sql_policy(team,api,apply,out,policy,scale_run=False):
    """Set Cloud SQL activationPolicy for one team. Returns exit status 0/1/2 (2 = refused, foreign resource)."""
    p=provisioner(team,api);tag=team['prefix']
    state,obj=check_owned(p,api,sql_url(p))
    if state=='absent':out(f'  {tag}: no SQL instance {tag}-pg (not provisioned?) - nothing to do');return 0
    if state=='foreign':out(f'  {tag}: REFUSED - {tag}-pg exists but is not owned by team {team["id"]}');return 2
    current=obj.get('settings',{}).get('activationPolicy')
    status=0
    if current==policy:out(f'  {tag}: SQL {tag}-pg already {policy} (state {obj.get("state")})')
    else:
        out(f'  {tag}: {"did" if apply else "would"} PATCH SQL {tag}-pg activationPolicy {current} -> {policy}')
        if apply:
            try:p.req('PATCH',sql_url(p),{'settings':{'activationPolicy':policy}})
            except (Pending,CloudError) as err:out(f'  {tag}: FAILED - {err}');status=1
    if scale_run:status=max(status,scale_run_to_zero(p,api,apply,out))
    return status


def scale_run_to_zero(p,api,apply,out):
    """Drop Cloud Run minInstanceCount to 0 (stops idle-instance billing). Does not stop request billing."""
    tag=p.p;url=ROOTS['run']+f'projects/{PROJECT}/locations/{REGION}/services/{tag}'
    state,obj=check_owned(p,api,url)
    if state=='absent':out(f'  {tag}: no Cloud Run service - skipped');return 0
    if state=='foreign':out(f'  {tag}: REFUSED - Cloud Run service {tag} is not owned by this team');return 2
    minimum=obj.get('template',{}).get('scaling',{}).get('minInstanceCount',0) or 0
    if not minimum:out(f'  {tag}: Cloud Run {tag} already minInstanceCount=0');return 0
    out(f'  {tag}: {"did" if apply else "would"} PATCH Cloud Run {tag} minInstanceCount {minimum} -> 0 (not restored by resume)')
    if apply:
        try:p.req('PATCH',url,{'template':{'scaling':{'minInstanceCount':0}}},params={'updateMask':'template.scaling.minInstanceCount'})
        except (Pending,CloudError) as err:out(f'  {tag}: FAILED - {err}');return 1
    return 0


def teardown_targets(p):
    """Ordered (label, url, uses_description_marker) for everything the Provisioner may have created."""
    parent=f'projects/{PROJECT}/locations/{REGION}'
    t=[('Cloud Run service',ROOTS['run']+parent+'/services/'+p.p,False),
       ('Cloud Run job',ROOTS['run']+parent+'/jobs/'+p.p+'-migrate',False),
       ('Cloud SQL instance',sql_url(p),False),
       ('Artifact Registry repo',ROOTS['ar']+parent+'/repositories/'+p.p,False)]
    for suffix in ('database-password','database-url','admin-password','demo-password',*[n[len(p.p)+1:] for n in p.slot_names()]):
        t.append(('secret '+p.p+'-'+suffix,ROOTS['sm']+f'projects/{PROJECT}/secrets/{p.p}-{suffix}',False))
    pool=ROOTS['iam']+f'projects/{NUMBER}/locations/global/workloadIdentityPools/{p.p}-pool'
    t+=[('WIF provider',pool+'/providers/'+p.p+'-provider',True),('WIF pool',pool,True),
        ('log view',ROOTS['log']+f'projects/{PROJECT}/locations/global/buckets/_Default/views/{p.p}',True)]
    return t


def service_accounts(p):
    return [('service account '+n,ROOTS['iam']+f'projects/{PROJECT}/serviceAccounts/{e}',True) for n,e in (('runner',p.runtime),('deployer',p.deployer))]


def teardown_team(team,api,apply,out):
    """Returns 0 ok, 1 failure part-way, 2 refused (foreign resource; nothing was changed)."""
    p=provisioner(team,api);tag=team['prefix']
    owned=[];foreign=[]
    for label,url,desc in teardown_targets(p)+service_accounts(p):
        state,_=check_owned(p,api,url,desc)
        if state=='owned':owned.append((label,url))
        elif state=='foreign':foreign.append(label)
    if foreign:
        out(f'  {tag}: REFUSED - not owned by team {team["id"]}, nothing deleted: '+', '.join(foreign));return 2
    if not owned:out(f'  {tag}: no owned resources found');return 0
    steps=[(l,u) for l,u in owned if not l.startswith('service account ')]
    sas=[(l,u) for l,u in owned if l.startswith('service account ')]
    verb='did' if apply else 'would'
    for label,url in steps:
        out(f'  {tag}: {verb} DELETE {label}')
        if apply and not _delete(p,url,label,tag,out):return 1
    out(f'  {tag}: {verb} revoke this team\'s project-level IAM bindings ({len(p.students)} user(s) + its service accounts)')
    if apply:
        try:p.policy(CRM,project_grants(p),project=True,remove=True)
        except (Pending,CloudError) as err:out(f'  {tag}: FAILED revoking project IAM - {err}');return 1
    for label,url in sas:
        out(f'  {tag}: {verb} DELETE {label}')
        if apply and not _delete(p,url,label,tag,out):return 1
    return 0


def project_grants(p):
    """The exact role/condition bindings the Provisioner adds at project level, for removal."""
    grants=[]
    for role,members,cond in p.project_member_grants(p.students):
        extra='serviceAccount:'+(p.runtime if role=='roles/cloudsql.client' else p.deployer)
        grants.append((role,members+[extra],cond))
    return grants


def _delete(p,url,label,tag,out):
    try:p.req('DELETE',url)
    except (Pending,CloudError) as err:out(f'  {tag}: FAILED deleting {label} - {err}');return False
    return True
