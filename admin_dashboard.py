"""TA-only read-only cloud operations dashboard; never returns secret payloads."""
import json
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import wraps
from flask import abort, jsonify, request, session
from live_provision import GoogleAPI, PROJECT, REGION, PLACEHOLDER


def utc(ts):
    return datetime.fromtimestamp(ts,timezone.utc).isoformat().replace('+00:00','Z')


REDACT='[REDACTED]'


def redacted(value):
    text=str(value)
    text=re.sub(r'(?i)(postgres(?:ql)?://)[^\s"\x27]+',r'\1'+REDACT,text)
    text=re.sub(r'(?im)\b((?:proxy-)?authorization|cookie|set-cookie)(\s*[:=]\s*).*$',r'\1\2'+REDACT,text)
    text=re.sub(r'\b((?i:Bearer)\s+[\w.~+/=\-]+|Basic\s+[A-Za-z0-9+/]{8,}=*)',REDACT,text)
    text=re.sub(r'(?i)((?:password|passwd|secret|access_token|refresh_token|id_token|client_secret|api[_-]?key)\s*["\x27]?\s*[:=]\s*)(?:"[^"]*"|\x27[^\x27]*\x27|[^\s,;"\x27]+(?:[ \t]+(?![\w-]+\s*[:=])[^\s,;"\x27]+)*)',r'\1'+REDACT,text)
    text=re.sub(r'\beyJ[\w-]{5,}\.eyJ[\w-]{5,}(?:\.[\w-]*)?',REDACT,text)
    text=re.sub(r'\bya29\.[\w.\-]+',REDACT,text)
    text=re.sub(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})',REDACT,text)
    text=re.sub(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',REDACT,text)
    return text[:2000]


def all_pages(api,url,key,params=None):
    rows=[];params=dict(params or {})
    for _ in range(10):
        data=api.request('GET',url,params=params);rows.extend(data.get(key,[]))
        if not data.get('nextPageToken'):return rows
        params['pageToken']=data['nextPageToken']
    raise ValueError('Resource inventory exceeds dashboard limit')


def collect_cloud(api=None):
    now=int(time.time())
    try:api=api or GoogleAPI()
    except Exception as err:  # e.g. ADC failure: degrade this section instead of a 500 for the whole overview
        return {'collected_at':now,'errors':{'cloud':redacted(str(err))},'services':None,'jobs':None,'sql':None,'registry':None,'billing':None,'requests':None}
    parent=f'projects/{PROJECT}/locations/{REGION}'
    sources={
        'services':lambda:all_pages(api,'https://run.googleapis.com/v2/'+parent+'/services','services',{'pageSize':100}),
        'jobs':lambda:all_pages(api,'https://run.googleapis.com/v2/'+parent+'/jobs','jobs',{'pageSize':100}),
        'sql':lambda:all_pages(api,f'https://sqladmin.googleapis.com/sql/v1beta4/projects/{PROJECT}/instances','items'),
        'registry':lambda:all_pages(api,'https://artifactregistry.googleapis.com/v1/'+parent+'/repositories','repositories',{'pageSize':100}),
        'billing':lambda:api.request('GET',f'https://cloudbilling.googleapis.com/v1/projects/{PROJECT}/billingInfo'),
    }
    # Aggregate request counts and status codes without exposing request bodies or resource credentials.
    def metric(kind):
        return all_pages(api,f'https://monitoring.googleapis.com/v3/projects/{PROJECT}/timeSeries','timeSeries',{
            'filter':f'metric.type="{kind}" AND resource.type="cloud_run_revision"',
            'interval.startTime':utc(now-86400),'interval.endTime':utc(now),
            'aggregation.alignmentPeriod':'3600s','aggregation.perSeriesAligner':'ALIGN_SUM',
            'view':'FULL','pageSize':1000})
    sources['requests']=lambda:metric('run.googleapis.com/request_count')
    result={'collected_at':now,'errors':{}}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures={k:pool.submit(fn) for k,fn in sources.items()}
        for key,future in futures.items():
            try:result[key]=future.result()
            except Exception as err:
                result[key]=None;result['errors'][key]=redacted(str(err))
    # Whitelist metadata. Cloud Run configuration can contain plaintext student env values.
    if result['services'] is not None:
        result['services']=[{'name':s['name'].split('/')[-1],'labels':s.get('labels',{}),'uri':s.get('uri'),
            'ready':s.get('terminalCondition',{}).get('state')=='CONDITION_SUCCEEDED',
            'condition':redacted(s.get('terminalCondition',{}).get('message','')),
            'revision':s.get('latestReadyRevision','').split('/')[-1],
            'updated_at':s.get('updateTime'), 'reconciling':s.get('reconciling',False),
            'placeholder':any(c.get('image')==PLACEHOLDER for c in s.get('template',{}).get('containers',[])),
            'max_instances':s.get('template',{}).get('scaling',{}).get('maxInstanceCount'),
            'service_account':s.get('template',{}).get('serviceAccount')}
            for s in result['services']]
    if result['jobs'] is not None:
        result['jobs']=[{'name':j['name'].split('/')[-1],'labels':j.get('labels',{}),
            'ready':j.get('terminalCondition',{}).get('state')=='CONDITION_SUCCEEDED',
            'execution':{'name':j.get('latestCreatedExecution',{}).get('name','').split('/')[-1],
                'completion_status':j.get('latestCreatedExecution',{}).get('completionStatus'),
                'completion_time':j.get('latestCreatedExecution',{}).get('completionTime')}} for j in result['jobs']]
    if result['sql'] is not None:
        result['sql']=[{'name':s['name'],'state':s.get('state'),'region':s.get('region'),
            'tier':s.get('settings',{}).get('tier'),'disk_gb':s.get('settings',{}).get('dataDiskSizeGb'),
            'labels':s.get('settings',{}).get('userLabels',{}),'version':s.get('databaseVersion'),
            'activation_policy':s.get('settings',{}).get('activationPolicy')} for s in result['sql']]
    if result['registry'] is not None:
        result['registry']=[{'name':s['name'].split('/')[-1],'labels':s.get('labels',{}),
            'size_bytes':s.get('sizeBytes','0')} for s in result['registry']]
    metrics={}
    for series in result.get('requests') or []:
        name=series.get('resource',{}).get('labels',{}).get('service_name','');code=series.get('metric',{}).get('labels',{}).get('response_code_class','')
        row=metrics.setdefault(name,{'requests':0,'errors_5xx':0,'hourly':{}})
        for point in series.get('points',[]):
            count=int(point.get('value',{}).get('int64Value',0));row['requests']+=count
            if code=='5xx':row['errors_5xx']+=count
            hour=point['interval']['endTime'];row['hourly'][hour]=row['hourly'].get(hour,0)+count
    result['requests']=metrics if result['requests'] is not None else None
    return result


def collect_costs(config,api=None):
    table=config['BILLING_EXPORT_TABLE'];location=config['BILLING_EXPORT_LOCATION']
    if not table:return {'status':'not_configured','groups':{},'collected_at':int(time.time())}
    if not re.fullmatch(r'[a-z][a-z0-9-]{4,62}\.[A-Za-z_][\w]*\.gcp_billing_export_resource_v1_[\w]+',table):
        return {'status':'invalid_configuration','groups':{},'collected_at':int(time.time())}
    since=config.get('BILLING_SINCE') or '2026-11-01'
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',since):
        return {'status':'invalid_configuration','groups':{},'collected_at':int(time.time())}
    # Labels/resource names attribute spend, never invented estimates. The ingestion-time partition filter bounds
    # scanned bytes: the export table lives on a billing account shared with other projects.
    query=f'''SELECT resource.name AS resource_name, service.description AS service_name,
      (SELECT l.value FROM UNNEST(labels) AS l WHERE l.key='cpe334-team' LIMIT 1) AS team_label,
      currency AS currency_code, SUM(cost) AS gross_cost,
      SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) AS c),0)) AS credit_total,
      SUM(cost+IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) AS c),0)) AS net_cost,
      MAX(usage_end_time) AS usage_through, MAX(export_time) AS export_through
      FROM `{table}` WHERE project.id=@project AND _PARTITIONTIME >= TIMESTAMP(@since)
      GROUP BY resource.name, service.description, team_label, currency'''
    try:
        api=api or GoogleAPI()
        data=api.request('POST',f'https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT}/queries',{
            'query':query,'useLegacySql':False,'parameterMode':'NAMED','queryParameters':[{'name':'project','parameterType':{'type':'STRING'},'parameterValue':{'value':PROJECT}},{'name':'since','parameterType':{'type':'STRING'},'parameterValue':{'value':since}}],
            'maximumBytesBilled':'1000000000','timeoutMs':10000,'location':location,'maxResults':10000})
        if not data.get('jobComplete') or data.get('pageToken'):return {'status':'query_pending_or_too_large','groups':{},'collected_at':int(time.time())}
        rows=[]
        for row in data.get('rows',[]):
            v=[x['v'] for x in row['f']]
            if isinstance(v[2],list):labels={x['v']['f'][0]['v']:x['v']['f'][1]['v'] for x in v[2]}
            else:labels={'cpe334-team':v[2]} if v[2] else {}
            rows.append(dict(resource=v[0] or '',service=v[1],labels=labels,currency=v[3],gross=float(v[4]),credits=float(v[5]),net=float(v[6]),usage_through=v[7],export_through=v[8]))
        return {'status':'available' if rows else 'awaiting_data','rows':rows,'collected_at':int(time.time())}
    except Exception as err:
        if getattr(err,'status',None)==404:
            return {'status':'awaiting_export','groups':{},'collected_at':int(time.time())}
        return {'status':'unavailable','error':redacted(str(err)),'groups':{},'collected_at':int(time.time())}


MISSING_EXPORT_AFTER=48*3600


def track_missing_export(db,result,now=None):
    """Turn a billing export table that keeps answering 404 for >48 h into 'export_table_missing'.
    The first-seen-404 time is persisted in admin_snapshots (kind 'costs_404_since')."""
    now=int(now if now is not None else time.time())
    with db() as conn:
        row=conn.execute("SELECT payload FROM admin_snapshots WHERE kind='costs_404_since'").fetchone()
        if result.get('status')!='awaiting_export':
            if row:conn.execute("DELETE FROM admin_snapshots WHERE kind='costs_404_since'")
            return result
        first=json.loads(row['payload']).get('first') if row else None
        if first is None:
            first=now
            conn.execute("INSERT INTO admin_snapshots(kind,payload,at) VALUES('costs_404_since',?,?) ON CONFLICT(kind) DO UPDATE SET payload=excluded.payload,at=excluded.at",(json.dumps({'first':first}),now))
    if now-first>MISSING_EXPORT_AFTER:result=dict(result,status='export_table_missing',missing_since=first)
    return result


def costs_for_teams(costs,teams):
    output={k:v for k,v in costs.items() if k!='rows'};output.update(groups={},totals={},unallocated={})
    for row in costs.get('rows',[]):
        label=row['labels'].get('cpe334-team')
        by_prefix=[t for t in teams if any(re.fullmatch(re.escape(t['prefix'])+r'(?:-(?:pg|migrate|runner|deployer|database-url|database-password|admin-password|demo-password|app-secret-[1-5]))?',segment) for segment in row['resource'].split('/'))]
        by_label=[t for t in teams if label==t['id']]
        # Labels are student-writable: never let one override resource-name ownership.
        mismatch=bool(by_label and by_prefix and {t['id'] for t in by_prefix}!={by_label[0]['id']})
        matches=[] if mismatch else list({t['id']:t for t in by_label+by_prefix}.values())
        target=output['groups'].setdefault(matches[0]['id'],{}) if len(matches)==1 else output['unallocated']
        if mismatch:output['label_mismatch']=output.get('label_mismatch',0)+1
        currency=row['currency']
        for bucket in (target,output['totals']):
            acc=bucket.setdefault(currency,{'gross':0,'credits':0,'net':0})
            for key in acc:acc[key]+=row[key]
        for key in ('usage_through','export_through'):
            if row.get(key):output[key]=max(float(output.get(key,0)),float(row[key]))
    return output


def register_admin(app):
    with app.db() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS team_activity(team_id TEXT PRIMARY KEY REFERENCES teams(id),last_seen INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS admin_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT NOT NULL,action TEXT NOT NULL,at INTEGER NOT NULL,detail TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS admin_snapshots(kind TEXT PRIMARY KEY,payload TEXT NOT NULL,at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS credit_observations(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT NOT NULL,amount TEXT NOT NULL,currency TEXT NOT NULL,observed_at INTEGER NOT NULL,recorded_at INTEGER NOT NULL,note TEXT NOT NULL);
        ''')
    lock=threading.Lock()
    def admin(fn):
        @wraps(fn)
        def wrapped(*args,**kwargs):
            if not app.current_admin():abort(403)
            return fn(*args,**kwargs)
        return wrapped
    from membership import register_membership
    register_membership(app,admin)

    def cached(kind,ttl,collect):
        with app.db() as conn:row=conn.execute('SELECT * FROM admin_snapshots WHERE kind=?',(kind,)).fetchone()
        def fresh(value):
            age=int(time.time())-value['at']
            duration=60 if kind=='costs' and json.loads(value['payload']).get('status')!='available' else ttl
            return age<duration
        if row and fresh(row):return json.loads(row['payload'])
        if not lock.acquire(blocking=False):
            return json.loads(row['payload']) if row else {'collected_at':None,'errors':{'refresh':'Refresh in progress'}}
        try:
            with app.db() as conn:latest=conn.execute('SELECT * FROM admin_snapshots WHERE kind=?',(kind,)).fetchone()
            if latest and fresh(latest):return json.loads(latest['payload'])
            value=collect()
            with app.db() as conn:conn.execute('INSERT INTO admin_snapshots(kind,payload,at) VALUES(?,?,?) ON CONFLICT(kind) DO UPDATE SET payload=excluded.payload,at=excluded.at',(kind,json.dumps(value),int(time.time())))
            return value
        finally:lock.release()

    @app.get('/api/admin/overview')
    @admin
    def overview():
        cloud=cached('cloud',60,lambda:collect_cloud())
        with app.db() as conn:
            teams=[dict(r) for r in conn.execute('''SELECT t.id,t.name,t.email,t.prefix,t.enabled,CASE WHEN t.google_sub IS NOT NULL THEN 1 ELSE 0 END primary_signed_in,
              a.status,a.step,a.mode,a.repo,a.error,a.created_at,a.updated_at,
              v.last_seen,(SELECT MAX(e.at) FROM events e WHERE e.team_id=t.id AND e.action='login') last_login,
              (SELECT COUNT(*) FROM events e WHERE e.team_id=t.id AND e.action='login') login_count,
              (SELECT r.created_at FROM repo_reviews r WHERE r.team_id=t.id) repo_reviewed_at
              FROM teams t LEFT JOIN activations a ON a.team_id=t.id LEFT JOIN team_activity v ON v.team_id=t.id WHERE t.demo=0 ORDER BY t.name''').fetchall()]
            members=[dict(r) for r in conn.execute('SELECT email,team_id,added_at,google_sub,cloud_status,cloud_error FROM team_members').fetchall()]
            observation=conn.execute('SELECT * FROM credit_observations ORDER BY id DESC LIMIT 1').fetchone()
            audit=[dict(r) for r in conn.execute('SELECT email,action,at,detail FROM admin_audit ORDER BY id DESC LIMIT 20').fetchall()]
        costs=costs_for_teams(cached('costs',900,lambda:track_missing_export(app.db,collect_costs(app.config))),teams)
        for team in teams:
            team['members']=[{'email':team['email'],'primary':True,'signed_in':bool(team['primary_signed_in']),'cloud_status':'primary'}]+[{k:v for k,v in m.items() if k not in ('google_sub','team_id')}|{'signed_in':bool(m['google_sub']),'primary':False} for m in members if m['team_id']==team['id']]
            for key in ('services','jobs','sql','registry'):
                team[key]=[r for r in cloud.get(key) or [] if r.get('labels',{}).get('cpe334-team')==team['id']]
            team['metrics']=(cloud.get('requests') or {}).get(team['prefix']) if cloud.get('requests') is not None else None
            team['costs']=costs['groups'].get(team['id'])
            team['recently_seen']=bool(team['last_seen'] and int(time.time())-team['last_seen']<300)
            if team['error']:team['error']=redacted(team['error'])
        return jsonify(admin_email=app.current_admin(),project=PROJECT,region=REGION,now=int(time.time()),teams=teams,
            cloud=cloud,costs=costs,billing_export={'table':app.config['BILLING_EXPORT_TABLE'],'location':app.config['BILLING_EXPORT_LOCATION']},credit_observation=dict(observation) if observation else None,audit=audit)

    @app.get('/api/admin/teams/<team_id>/logs')
    @admin
    def logs(team_id):
        with app.db() as conn:
            team=conn.execute('SELECT id,prefix FROM teams WHERE id=? AND demo=0',(team_id,)).fetchone()
            events=[dict(r) for r in conn.execute('SELECT action,at,detail FROM events WHERE team_id=? ORDER BY id DESC LIMIT 50',(team_id,)).fetchall()]
        if not team:abort(404)
        prefix=team['prefix']
        if not re.fullmatch('[a-z][a-z0-9]{2,9}',prefix):abort(409)
        level=request.args.get('severity','DEFAULT');hours=request.args.get('hours','24')
        if level not in ('DEFAULT','WARNING','ERROR') or hours not in ('1','24','168'):abort(400)
        filter_=f'((resource.type="cloud_run_revision" AND resource.labels.service_name="{prefix}") OR (resource.type="cloud_run_job" AND resource.labels.job_name="{prefix}-migrate") OR (resource.type="cloudsql_database" AND resource.labels.database_id="{PROJECT}:{prefix}-pg")) AND timestamp>="{utc(time.time()-int(hours)*3600)}" AND severity>={level}'
        entries=[];error=None
        try:
            data=GoogleAPI().request('POST','https://logging.googleapis.com/v2/entries:list',{'resourceNames':['projects/'+PROJECT],'filter':filter_,'orderBy':'timestamp desc','pageSize':100})
            for e in data.get('entries',[]):
                # Whitelist text/message only, never forward arbitrary structured credentials/env.
                message=e.get('textPayload') or e.get('jsonPayload',{}).get('message') or e.get('jsonPayload',{}).get('msg') or e.get('protoPayload',{}).get('status',{}).get('message')
                h=e.get('httpRequest',{});summary={k:h[k] for k in ('requestMethod','status','latency') if k in h}
                entries.append({'at':e.get('timestamp'),'severity':e.get('severity','DEFAULT'),'resource':e.get('resource',{}).get('type'),'message':redacted(message) if message else '', 'http':summary})
        except Exception as err:error=redacted(str(err))
        with app.db() as conn:conn.execute('INSERT INTO admin_audit(email,action,at,detail) VALUES(?,?,?,?)',(app.current_admin(),'read_logs',int(time.time()),team_id))
        for event in events:event['detail']=redacted(event['detail'])
        return jsonify(entries=entries,events=events,error=error,collected_at=int(time.time()),limit=100)

    @app.post('/api/admin/credit-observation')
    @admin
    def credit_observation():
        from decimal import Decimal,InvalidOperation
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict):abort(400)
        try:
            amount=Decimal(str(data['amount']));at=int(data['observed_at']);currency=data['currency'];note=str(data.get('note','')).strip()
            if not amount.is_finite() or amount<0 or amount>Decimal('10000000') or not re.fullmatch('[A-Z]{3}',currency) or at>time.time()+60 or at<time.time()-366*86400 or len(note)>500:raise ValueError()
        except (KeyError,ValueError,TypeError,InvalidOperation):abort(400)
        with app.db() as conn:
            conn.execute('INSERT INTO credit_observations(email,amount,currency,observed_at,recorded_at,note) VALUES(?,?,?,?,?,?)',(app.current_admin(),str(amount),currency,at,int(time.time()),note))
            conn.execute('INSERT INTO admin_audit(email,action,at,detail) VALUES(?,?,?,?)',(app.current_admin(),'credit_observation',int(time.time()),f'{amount} {currency}; observed {at}'))
        return jsonify(saved=True)
