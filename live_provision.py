"""Course provisioning state machine. No student code or shell is executed here."""
import base64
import hashlib
import json
import re
import secrets
import uuid
from urllib.parse import quote
import requests

PROJECT='cpe-se-course-2026'
NUMBER='670075229477'
REGION='asia-southeast1'
SLOT_COUNT=5  # per-group empty secret slots students fill with their own API keys
LABEL='cpe334-team'
PLACEHOLDER=f'{REGION}-docker.pkg.dev/{PROJECT}/cpe334-portal/placeholder:v1'
ROOTS={'ar':'https://artifactregistry.googleapis.com/v1/','run':'https://run.googleapis.com/v2/',
       'iam':'https://iam.googleapis.com/v1/','sm':'https://secretmanager.googleapis.com/v1/',
       'sql':'https://sqladmin.googleapis.com/sql/v1beta4/','log':'https://logging.googleapis.com/v2/'}

class Pending(Exception):pass
class ProvisionError(Exception):pass
class AlreadyExists(Pending):pass
class LeaseLost(Pending):pass  # a fenced worker lost its lease: stop immediately, never swallow
class RevokeIncomplete(ProvisionError):
    """Some revoke targets failed; the rest were processed. `failed` names them, `transient` says retry can help."""
    def __init__(self,failed,transient):
        self.failed=list(failed);self.transient=transient
        super().__init__('Revocation incomplete for: '+', '.join(self.failed))
SA_NOT_READY_RE=re.compile(r'service ?account.{0,200}(does not exist|not found)',re.IGNORECASE|re.DOTALL)
class CloudError(ProvisionError):
    def __init__(self,status,endpoint='',detail=''):
        self.status=status;self.detail=detail
        # Google answers 400 "Service account ... does not exist" for a few seconds after creating it: that is propagation, not a bad request.
        self.propagating=status==400 and bool(SA_NOT_READY_RE.search(detail))
        super().__init__('Google Cloud rejected a provisioning request (HTTP '+str(status)+'). '+endpoint+((' Google said: '+detail) if detail else ''))

def error_detail(response):
    """Short provider message for TA diagnosis. Never the request body, headers or credentials."""
    try:message=response.json().get('error',{}).get('message','')
    except Exception:return ''
    return ' '.join(message.split())[:200] if isinstance(message,str) else ''

class GoogleAPI:
    def __init__(self,session=None):
        if session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
            credentials,_=google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
            session=AuthorizedSession(credentials)
        self.session=session
    def request(self,method,url,body=None,missing=False,params=None):
        try:r=self.session.request(method,url,json=body,params=params,timeout=(5,25))
        except requests.RequestException:raise Pending('Cloud connection interrupted; retrying the same step') from None
        if r.status_code==404 and missing:return None
        if r.status_code==409 and r.json().get('error',{}).get('status')=='ALREADY_EXISTS':raise AlreadyExists('Resource already exists')
        if r.status_code in (408,409,412,429) or r.status_code>=500:raise Pending('Waiting for Google Cloud operation or quota')
        if not 200<=r.status_code<300:raise CloudError(r.status_code,method+' '+url,error_detail(r))
        return r.json() if r.content else {}


def github_identity(repo):
    from repo_review import get_bytes,normalize_repo
    repo=normalize_repo(repo)
    raw=get_bytes('https://api.github.com/repos/'+repo,200000)
    if raw is None:raise ValueError('Public GitHub repository was not found')
    data=json.loads(raw)
    if data.get('private') or data.get('archived') or not isinstance(data.get('id'),int) or not isinstance(data.get('owner',{}).get('id'),int):
        raise ValueError('Repository identity cannot be verified')
    canonical=normalize_repo(data['full_name'])
    return {'repo':canonical,'repository_id':str(data['id']),'owner_id':str(data['owner']['id'])}


def wif_condition(identity):
    repo=identity['repo']
    return (f"assertion.repository_id == '{identity['repository_id']}' && assertion.repository_owner_id == '{identity['owner_id']}'"
            f" && assertion.ref == 'refs/heads/main' && assertion.sub == 'repo:{repo}:environment:demo'"
            f" && assertion.workflow_ref == '{repo}/.github/workflows/deploy.yml@refs/heads/main'"
            " && assertion.event_name in ['push','workflow_dispatch']")

class Provisioner:
    def __init__(self,team,identity,state,save,api=None):
        self.team=team;self.identity=identity;self.state=state;self.save=save;self.api=api or GoogleAPI()
        self.p=team['prefix'];self.marker='CPE334 portal group:'+team['id']+';prefix:'+self.p+';v1'
        if not re.fullmatch('[a-z][a-z0-9]{2,9}',self.p) or not re.fullmatch('[a-z0-9_-]{1,63}',team['id']):raise ProvisionError('Invalid assigned identity')
        self.labels={LABEL:team['id'],'managed-by':'cpe334-portal'}
        self.students=['user:'+email for email in sorted(set(team.get('member_emails',[team['email']])))]
        self.runtime=f'{self.p}-runner@{PROJECT}.iam.gserviceaccount.com'
        self.deployer=f'{self.p}-deployer@{PROJECT}.iam.gserviceaccount.com'
    def req(self,method,url,body=None,**kw):
        self.save(self.state)  # Renew the fenced lease even if a provider stage outlives the HTTP request.
        return self.api.request(method,url,body,**kw)
    def owned(self,obj,description=False):
        actual=obj.get('description','') if description else obj.get('labels',obj.get('settings',{}).get('userLabels',{})).get(LABEL)
        if actual!=(self.marker if description else self.team['id']):raise ProvisionError('Resource name already exists without this group ownership; TA review required')
    def operation(self,key,root,body=None):
        operations=self.state.setdefault('operations',{})
        if key not in operations:
            if body is None:return
            name=body.get('name')
            if not name or ('/operations/' not in name and body.get('kind')!='sql#operation'):return
            operations[key]=root+name;self.save(self.state)
        result=self.req('GET',operations[key])
        done=result.get('done') or result.get('status')=='DONE'
        if not done:raise Pending('Waiting for Google Cloud operation')
        # A finished operation (success or failure) is forgotten so a retry re-checks the real resource
        # instead of re-reading a failed long-running operation forever.
        operations.pop(key,None);self.save(self.state)
        if result.get('error'):raise ProvisionError('Google Cloud operation failed; TA review required')
    def ensure(self,key,root,path,create_path,body,params=None,description=False):
        self.operation(key,root)
        obj=self.req('GET',root+path,missing=True)
        if obj is None:
            result=self.req('POST',root+create_path,body,params=params)
            self.operation(key,root,result)
            obj=self.req('GET',root+path,missing=True)
            if obj is None:raise Pending('Resource is becoming available')
        self.owned(obj,description)
        return obj
    def policy(self,url,grants,project=False,remove=False):
        if project or url.startswith(ROOTS['iam']) or url.startswith(ROOTS['log']):
            doc=self.req('POST',url+':getIamPolicy',{'options':{'requestedPolicyVersion':3}})
        else:doc=self.req('GET',url+':getIamPolicy',params={'options.requestedPolicyVersion':3})
        changed=False
        if remove:
            # Revoke only the listed principals from the exact role/condition bindings; every other
            # member (teammates, service accounts) and every other binding stays untouched.
            for role,members,condition in grants:
                binding=next((b for b in doc.get('bindings',[]) if b['role']==role and b.get('condition')==condition),None)
                if binding is None:continue
                kept=[m for m in binding['members'] if m not in members]
                if len(kept)!=len(binding['members']):
                    changed=True;binding['members']=kept
                    if not kept:doc['bindings'].remove(binding)
            if changed:
                doc['version']=3
                self.req('POST',url+':setIamPolicy',{'policy':doc})
            return
        for role,members,condition in grants:
            binding=next((b for b in doc.get('bindings',[]) if b['role']==role and b.get('condition')==condition),None)
            if binding is None:
                binding={'role':role,'members':[]};doc.setdefault('bindings',[]).append(binding)
                if condition:binding['condition']=condition
            for member in members:
                if member not in binding['members']:binding['members'].append(member);changed=True
        if changed:
            doc['version']=3
            self.req('POST',url+':setIamPolicy',{'policy':doc})
    def secret(self,suffix,value=None):
        path=f'projects/{PROJECT}/secrets/{self.p}-{suffix}'
        self.ensure('secret-'+suffix,ROOTS['sm'],path,f'projects/{PROJECT}/secrets',
                    {'labels':self.labels,'replication':{'automatic':{}}},params={'secretId':self.p+'-'+suffix})
        version=self.req('GET',ROOTS['sm']+path+'/versions/latest',missing=True)
        if version is None:
            value=value if value is not None else secrets.token_urlsafe(32)
            self.req('POST',ROOTS['sm']+path+':addVersion',{'payload':{'data':base64.b64encode(value.encode()).decode()}})
        result=self.req('GET',ROOTS['sm']+path+'/versions/latest:access')
        return base64.b64decode(result['payload']['data']).decode()
    def registry(self):
        self.ensure('registry',ROOTS['ar'],f'projects/{PROJECT}/locations/{REGION}/repositories/{self.p}',
                    f'projects/{PROJECT}/locations/{REGION}/repositories',{'format':'DOCKER','labels':self.labels,'description':self.marker},params={'repositoryId':self.p})
    def database(self):
        root=ROOTS['sql'];name=self.p+'-pg';path=f'projects/{PROJECT}/instances/{name}'
        self.operation('sql-instance',root+f'projects/{PROJECT}/operations/')
        instance=self.req('GET',root+path,missing=True)
        if instance is None:
            others=self.req('GET',root+f'projects/{PROJECT}/instances').get('items',[])
            if sum(i.get('state')=='PENDING_CREATE' for i in others)>=2:raise Pending('Another group database is being created')
            if len(others)>=40:raise ProvisionError('Course database count limit reached; TA review required')
            result=self.req('POST',root+f'projects/{PROJECT}/instances',{'name':name,'region':REGION,'databaseVersion':'POSTGRES_16',
                'settings':{'tier':'db-f1-micro','edition':'ENTERPRISE','dataDiskSizeGb':'10','dataDiskType':'PD_SSD','storageAutoResize':False,
                 'activationPolicy':'ALWAYS','userLabels':self.labels,'backupConfiguration':{'enabled':True,'startTime':'03:00'},
                 'ipConfiguration':{'ipv4Enabled':True,'authorizedNetworks':[]}}})
            self.operation('sql-instance',root+f'projects/{PROJECT}/operations/',result)
            raise Pending('Database creation started')
        self.owned(instance)
        if instance.get('state')!='RUNNABLE':raise Pending('Waiting for database readiness')
        self.operation('sql-database',root+f'projects/{PROJECT}/operations/')
        if self.req('GET',root+path+'/databases/'+self.p,missing=True) is None:
            result=self.req('POST',root+path+'/databases',{'name':self.p,'charset':'UTF8'})
            self.operation('sql-database',root+f'projects/{PROJECT}/operations/',result)
        password=self.secret('database-password')
        self.operation('sql-user',root+f'projects/{PROJECT}/operations/')
        users=self.req('GET',root+path+'/users').get('items',[])
        if not any(u['name']==self.p for u in users):
            result=self.req('POST',root+path+'/users',{'name':self.p,'password':password})
            self.operation('sql-user',root+f'projects/{PROJECT}/operations/',result)
    def identity_accounts(self):
        for suffix,email in [('runner',self.runtime),('deployer',self.deployer)]:
            path=f'projects/{PROJECT}/serviceAccounts/{email}'
            self.ensure('sa-'+suffix,ROOTS['iam'],path,f'projects/{PROJECT}/serviceAccounts',
                        {'accountId':self.p+'-'+suffix,'serviceAccount':{'displayName':self.p+' '+suffix,'description':self.marker}},description=True)
        self.policy(ROOTS['iam']+f'projects/{PROJECT}/serviceAccounts/{self.runtime}',[('roles/iam.serviceAccountUser',self.students+['serviceAccount:'+self.deployer,'serviceAccount:cpe334-provisioner@'+PROJECT+'.iam.gserviceaccount.com'],None)])
        members=['serviceAccount:'+self.runtime]+self.students
        self.policy(f'https://cloudresourcemanager.googleapis.com/v1/projects/{PROJECT}',[
            ('roles/cloudsql.client',members,{'title':'cpe334-'+self.p,'expression':f"resource.type == 'sqladmin.googleapis.com/Instance' && resource.name == 'projects/{PROJECT}/instances/{self.p}-pg'"}),
            ('projects/'+PROJECT+'/roles/cpe334ProjectIdentity',self.students+['serviceAccount:'+self.deployer],None),
            ('roles/serviceusage.serviceUsageConsumer',self.students+['serviceAccount:'+self.deployer],None)],project=True)
    def connection_secrets(self):
        password=self.secret('database-password')
        connection=f'{PROJECT}:{REGION}:{self.p}-pg'
        value=f'postgresql://{self.p}:{quote(password,safe="")}@localhost/{self.p}?host=/cloudsql/{connection}&schema=public&connection_limit=3'
        self.secret('database-url',value)
        self.secret('admin-password');self.secret('demo-password')
        for suffix in ('database-url','admin-password','demo-password'):
            members=['serviceAccount:'+self.runtime]
            if suffix!='database-url':members.extend(self.students)
            self.policy(ROOTS['sm']+f'projects/{PROJECT}/secrets/{self.p}-{suffix}',[('roles/secretmanager.secretAccessor',members,None)])
        self.slot_secrets()
    def slot_names(self):return [f'{self.p}-app-secret-{n}' for n in range(1,SLOT_COUNT+1)]
    def slot_secrets(self):
        """Idempotently pre-create the empty student secret slots (no versions) and grant slot-level IAM.

        Students may add versions and read them on these slots only (never version manage/destroy/delete);
        the runtime SA can read them so Cloud Run can mount them. Existing secrets not owned by the group are refused.
        """
        for name in self.slot_names():
            path=f'projects/{PROJECT}/secrets/{name}'
            self.ensure('secret-'+name[len(self.p)+1:],ROOTS['sm'],path,f'projects/{PROJECT}/secrets',
                        {'labels':self.labels,'replication':{'automatic':{}}},params={'secretId':name})
            self.policy(ROOTS['sm']+path,[
                ('roles/secretmanager.secretAccessor',['serviceAccount:'+self.runtime,'serviceAccount:'+self.deployer]+self.students,None),
                ('roles/secretmanager.secretVersionAdder',self.students,None)])
    def deployments(self):
        root=ROOTS['run'];parent=f'projects/{PROJECT}/locations/{REGION}'
        env=[{'name':name,'valueSource':{'secretKeyRef':{'secret':self.p+'-'+suffix,'version':'latest'}}}
             for name,suffix in [('DATABASE_URL','database-url'),('ADMIN_PASSWORD','admin-password')]]
        template={'serviceAccount':self.runtime,'volumes':[{'name':'cloudsql','cloudSqlInstance':{'instances':[f'{PROJECT}:{REGION}:{self.p}-pg']}}],
                  'containers':[{'image':PLACEHOLDER,'env':env,'volumeMounts':[{'name':'cloudsql','mountPath':'/cloudsql'}],
                                 'resources':{'limits':{'cpu':'1','memory':'512Mi'}}}]}
        service=self.ensure('run-service',root,parent+'/services/'+self.p,parent+'/services',
            {'labels':self.labels,'ingress':'INGRESS_TRAFFIC_ALL','template':{**template,'scaling':{'minInstanceCount':0,'maxInstanceCount':1}}},params={'serviceId':self.p})
        job_template=json.loads(json.dumps(template));job_template['containers'][0].update(command=['python'],args=['-c',"raise SystemExit('Deploy your reviewed application image before running migrations')"])
        job=self.ensure('run-job',root,parent+'/jobs/'+self.p+'-migrate',parent+'/jobs',
            {'labels':self.labels,'template':{'taskCount':1,'parallelism':1,'template':{**job_template,'maxRetries':0,'timeout':'600s'}}},params={'jobId':self.p+'-migrate'})
        if service.get('reconciling') or job.get('reconciling'):raise Pending('Cloud Run is reconciling')
        self.state['service_url']=service.get('uri','');self.save(self.state)
        self.policy(root+parent+'/services/'+self.p,[('roles/run.invoker',['allUsers'],None)])
        members=self.students+['serviceAccount:'+self.deployer]
        for resource in ('services/'+self.p,'jobs/'+self.p+'-migrate'):
            self.policy(root+parent+'/'+resource,[('roles/run.developer',members,None)])
        self.policy(ROOTS['ar']+parent+'/repositories/'+self.p,[('roles/artifactregistry.writer',members,None)])
        self.policy(ROOTS['iam']+f'projects/{PROJECT}/serviceAccounts/{self.runtime}',[('roles/iam.serviceAccountUser',members,None)])
    def github(self):
        if self.identity:
            root=ROOTS['iam'];parent=f'projects/{NUMBER}/locations/global';pool=self.p+'-pool';provider=self.p+'-provider'
            self.ensure('wif-pool',root,parent+'/workloadIdentityPools/'+pool,parent+'/workloadIdentityPools',
                        {'displayName':self.p+' GitHub','description':self.marker},params={'workloadIdentityPoolId':pool},description=True)
            path=parent+'/workloadIdentityPools/'+pool
            expected={'google.subject':'assertion.sub','attribute.repository_id':'assertion.repository_id'}
            obj=self.ensure('wif-provider',root,path+'/providers/'+provider,path+'/providers',
                        {'displayName':self.p+' GitHub','description':self.marker,'oidc':{'issuerUri':'https://token.actions.githubusercontent.com'},
                         'attributeMapping':expected,'attributeCondition':wif_condition(self.identity)},params={'workloadIdentityPoolProviderId':provider},description=True)
            if obj.get('attributeCondition')!=wif_condition(self.identity) or obj.get('attributeMapping')!=expected:raise ProvisionError('Existing WIF provider does not match frozen repository')
            member=f'principalSet://iam.googleapis.com/projects/{NUMBER}/locations/global/workloadIdentityPools/{pool}/attribute.repository_id/{self.identity["repository_id"]}'
            self.policy(root+f'projects/{PROJECT}/serviceAccounts/{self.deployer}',[('roles/iam.workloadIdentityUser',[member],None)])
        name=f'projects/{PROJECT}/locations/global/buckets/_Default/views/{self.p}'
        existing=self.req('GET',ROOTS['log']+name,missing=True)
        filter_=f'resource.labels.service_name="{self.p}" OR resource.labels.job_name="{self.p}-migrate" OR resource.labels.database_id="{PROJECT}:{self.p}-pg"'
        if existing is None:
            self.req('POST',ROOTS['log']+f'projects/{PROJECT}/locations/global/buckets/_Default/views',{'description':self.marker,'filter':filter_},params={'viewId':self.p})
        else:
            if existing.get('description')!=self.marker or existing.get('filter')!=filter_:raise ProvisionError('Log view ownership does not match this group')
        self.policy(ROOTS['log']+name,[('roles/logging.viewAccessor',self.students+['serviceAccount:'+self.deployer],None)])
    def member_targets(self):
        parent=f'projects/{PROJECT}/locations/{REGION}'
        targets=[(ROOTS['run']+parent+'/services/'+self.p,'roles/run.developer',False),
                 (ROOTS['run']+parent+'/jobs/'+self.p+'-migrate','roles/run.developer',False),
                 (ROOTS['ar']+parent+'/repositories/'+self.p,'roles/artifactregistry.writer',False),
                 (ROOTS['iam']+f'projects/{PROJECT}/serviceAccounts/{self.runtime}','roles/iam.serviceAccountUser',True),
                 (ROOTS['log']+f'projects/{PROJECT}/locations/global/buckets/_Default/views/{self.p}','roles/logging.viewAccessor',True)]
        for suffix in ('admin-password','demo-password'):
            targets.append((ROOTS['sm']+f'projects/{PROJECT}/secrets/{self.p}-{suffix}','roles/secretmanager.secretAccessor',False))
        self.owned(self.req('GET',ROOTS['sql']+f'projects/{PROJECT}/instances/{self.p}-pg'))
        for url,role,description in targets:
            self.owned(self.req('GET',url),description)
        # Student secret slots: tolerate groups not yet backfilled (missing slot is skipped), but a slot that
        # exists must be owned by this group. Members get accessor+versionAdder only (no version manager/admin).
        for name in self.slot_names():
            url=ROOTS['sm']+f'projects/{PROJECT}/secrets/{name}'
            obj=self.req('GET',url,missing=True)
            if obj is None:continue
            self.owned(obj)
            targets.extend([(url,'roles/secretmanager.secretAccessor',False),(url,'roles/secretmanager.secretVersionAdder',False)])
        return targets
    def project_member_grants(self,students):
        return [('roles/cloudsql.client',students,{'title':'cpe334-'+self.p,'expression':f"resource.type == 'sqladmin.googleapis.com/Instance' && resource.name == 'projects/{PROJECT}/instances/{self.p}-pg'"}),
                ('projects/'+PROJECT+'/roles/cpe334ProjectIdentity',students,None),
                ('roles/serviceusage.serviceUsageConsumer',students,None)]
    def grant_members(self,students=None):
        students=self.students if students is None else students
        targets=self.member_targets()
        for url,role,_ in targets:self.policy(url,[(role,students,None)])
        self.policy(f'https://cloudresourcemanager.googleapis.com/v1/projects/{PROJECT}',self.project_member_grants(students),project=True)
    def revoke_targets(self):
        """(url,role) pairs derived from the unique prefix only: no GET, no ownership check.

        Members hold run.developer on their own service/job and can edit labels or delete the job, so
        revocation must never depend on a resource still existing or still carrying our label."""
        parent=f'projects/{PROJECT}/locations/{REGION}'
        targets=[(ROOTS['run']+parent+'/services/'+self.p,'roles/run.developer'),
                 (ROOTS['run']+parent+'/jobs/'+self.p+'-migrate','roles/run.developer'),
                 (ROOTS['ar']+parent+'/repositories/'+self.p,'roles/artifactregistry.writer'),
                 (ROOTS['iam']+f'projects/{PROJECT}/serviceAccounts/{self.runtime}','roles/iam.serviceAccountUser'),
                 (ROOTS['log']+f'projects/{PROJECT}/locations/global/buckets/_Default/views/{self.p}','roles/logging.viewAccessor')]
        for suffix in ('admin-password','demo-password'):
            targets.append((ROOTS['sm']+f'projects/{PROJECT}/secrets/{self.p}-{suffix}','roles/secretmanager.secretAccessor'))
        for name in self.slot_names():
            url=ROOTS['sm']+f'projects/{PROJECT}/secrets/{name}'
            targets.extend([(url,'roles/secretmanager.secretAccessor'),(url,'roles/secretmanager.secretVersionAdder')])
        return targets
    def revoke_members(self,students):
        """Best-effort removal of the given user principals from this group's bindings (never service accounts
        or other users). A missing target (404) is skipped, every target and the project-level bindings are
        always attempted, and failures are collected and reported together (RevokeIncomplete)."""
        students=[s for s in students if s.startswith('user:')]
        if not students:return
        failed=[];transient=False
        def attempt(label,work):
            nonlocal transient
            try:work()
            except LeaseLost:raise
            except CloudError as err:
                if err.status==404:return  # resource (or slot) is gone: nothing to revoke there
                failed.append(label);transient=transient or err.status!=400
            except Exception:
                failed.append(label);transient=True
        for url,role in self.revoke_targets():
            attempt(url.split(PROJECT+'/',1)[-1],lambda url=url,role=role:self.policy(url,[(role,students,None)],remove=True))
        attempt('project-iam',lambda:self.policy(f'https://cloudresourcemanager.googleapis.com/v1/projects/{PROJECT}',self.project_member_grants(students),project=True,remove=True))
        if failed:raise RevokeIncomplete(list(dict.fromkeys(failed)),transient)
    def step(self,number):
        [self.registry,self.database,self.identity_accounts,self.connection_secrets,self.deployments,self.github][number]()
    def outputs(self):
        from app import build_plan
        result=build_plan(self.team,self.identity['repo'] if self.identity else '',PROJECT,REGION)
        result.update(mode='live',created_in_google_cloud=True,service_url=self.state.get('service_url'),application_deployed_by_portal=False,
                      notice='Infrastructure is ready. The placeholder is not your application; build, migrate and deploy your reviewed code.',
                      next_steps=['Download the live patch and review it with your teammate.','Build and push your app image, run migration, deploy and complete the Lab 5 evidence.'])
        if self.identity:
            result['github_variables']['WIF_PROVIDER']=result['github_variables']['WIF_PROVIDER'].replace('PROJECT_NUMBER',NUMBER)
        else:
            result['notice']='Group infrastructure is ready. Build and deploy your own application; GitHub and Lab 5 are optional.'
            result['next_steps']=['Use the assigned resource names and runtime service account to deploy your application.','Read only your group resources and logs; credits are shared.']
        result['resources']['logs_view']=f'projects/{PROJECT}/locations/global/buckets/_Default/views/{self.p}'
        return result


def task_name(team_id,created):return 'activate-'+hashlib.sha256((team_id+':'+str(created)).encode()).hexdigest()[:40]

def enqueue(config,team_id,created,api=None,retry=False,kind='provision'):
    api=api or GoogleAPI()
    queue=f'projects/{PROJECT}/locations/{REGION}/queues/cpe334-activation'
    name=task_name(team_id,created)+(('-'+uuid.uuid4().hex[:12]) if retry else '')
    body={'task':{'name':queue+'/tasks/'+name,'dispatchDeadline':'180s','httpRequest':{
        'httpMethod':'POST','url':config['WORKER_URL']+'/internal/provision','headers':{'Content-Type':'application/json'},
        'body':base64.b64encode(json.dumps({'team_id':team_id,**({'kind':kind} if kind!='provision' else {})}).encode()).decode(),
        'oidcToken':{'serviceAccountEmail':config['TASK_IDENTITY'],'audience':config['WORKER_URL']}}}}
    # An existing deterministic task is success, not a second activation.
    try:api.request('POST','https://cloudtasks.googleapis.com/v2/'+queue+'/tasks',body)
    except AlreadyExists:
        return
