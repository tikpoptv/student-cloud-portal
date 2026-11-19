"""Transactional activation entry point and task worker. Cloud identities stay server-side."""
import json
import secrets
import time
import requests
from flask import jsonify
from live_provision import github_identity,enqueue,Pending,ProvisionError,CloudError,Provisioner,LeaseLost


def activate_live(app,team,repo,resources_only=False):
    identity=None
    if not resources_only:
        with app.db() as conn:
            saved=conn.execute('SELECT report FROM repo_reviews WHERE team_id=?',(team['id'],)).fetchone()
            snapshot=conn.execute('SELECT sha FROM repo_snapshots WHERE team_id=?',(team['id'],)).fetchone()
        if not saved or not snapshot:return jsonify(error='ตรวจ repo และยืนยันค่าของแอปก่อน Activate'),409
        review=json.loads(saved['report'])
        if review['status']!='prepared' or review['repo'].casefold()!=repo.casefold():
            return jsonify(error='ต้องใช้ repo เดียวกับผลตรวจที่พร้อมใช้งาน'),409
        try:identity=github_identity(repo)
        except (ValueError,requests.RequestException):return jsonify(error='ยืนยัน GitHub repository ไม่สำเร็จ กรุณาลองใหม่'),400
    now=int(time.time());retry=False
    with app.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        current=conn.execute('SELECT * FROM activations WHERE team_id=?',(team['id'],)).fetchone()
        frozen=conn.execute('SELECT * FROM activation_runtime WHERE team_id=?',(team['id'],)).fetchone()
        attach=bool(identity and current and current['mode']=='live' and not current['repo'])
        link=current['github_link_status'] if current and current['mode']=='live' else None
        relink=bool(identity and not resources_only and current and current['mode']=='live' and current['repo'] and current['status']=='ready' and link)
        if attach and current['status']!='ready':return jsonify(error='รอสร้างทรัพยากรให้พร้อมก่อนเชื่อม GitHub'),409
        if resources_only and current and current['mode']=='live':
            identity=json.loads(frozen['state'])['identity'] if frozen else None
            repo=current['repo']
        elif identity:
            repo=identity['repo']
        else:repo=''
        identity_key=identity['repository_id'] if identity else 'resources:'+team['id']
        if current and current['mode']=='live' and current['repo'] and current['repo'].casefold()!=repo.casefold():
            return jsonify(error='กลุ่มนี้เริ่มเตรียมระบบแล้ว กรุณาใช้ repository เดิม'),409
        if frozen and frozen['repository_id']!=identity_key and not attach:
            return jsonify(error='Repository identity เปลี่ยน ต้องให้ TA ตรวจสอบ'),409
        other=conn.execute('SELECT team_id FROM activation_runtime WHERE repository_id=? AND team_id!=?',(identity_key,team['id'])).fetchone()
        if other:return jsonify(error='Repository นี้ถูกใช้กับกลุ่มอื่นแล้ว กรุณาให้ TA ตรวจสอบ'),409
        if attach:
            state=json.loads(frozen['state']);state['identity']=identity
            conn.execute('UPDATE activation_runtime SET repository_id=?,state=? WHERE team_id=?',(identity_key,json.dumps(state),team['id']))
            # The resources stay ready (outputs, step and created_at untouched); only the GitHub link is queued.
            conn.execute("UPDATE activations SET repo=?,github_link_status='queued',github_link_error=NULL,github_link_at=?,worker_seen_at=NULL,lease_until=0,attempts=0 WHERE team_id=?",(repo,now,team['id']))
            conn.execute('INSERT INTO events(team_id,action,at,detail) VALUES(?,?,?,?)',(team['id'],'github_queued',now,'Connect verified GitHub to existing infrastructure'))
            created=now;retry=True
        elif relink:
            if link=='running' and current['lease_until']>now:return jsonify(status='ready',github_link_status='running',duplicate=True),200
            # A queued link no worker has ever seen may have lost its task (enqueue failed): enqueue it again.
            if link=='queued' and current['worker_seen_at'] is not None and now-(current['github_link_at'] or 0)<=600:return jsonify(status='ready',github_link_status='queued',duplicate=True),200
            conn.execute("UPDATE activations SET github_link_status='queued',github_link_error=NULL,github_link_at=?,worker_seen_at=NULL,lease_until=0,attempts=0 WHERE team_id=?",(now,team['id']))
            conn.execute('INSERT INTO events(team_id,action,at,detail) VALUES(?,?,?,?)',(team['id'],'github_requeued',now,'Retry GitHub link on existing infrastructure'))
            created=now;retry=True
        elif current and current['mode']=='live':
            if current['status']=='ready':return jsonify(status='ready',duplicate=True),200
            if current['status']=='running' and current['lease_until']>now:return jsonify(status='running',duplicate=True),200
            retry=current['status']=='failed' or now-current['updated_at']>600
            if retry:
                conn.execute("UPDATE activations SET status='queued',error=NULL,lease_until=0,updated_at=?,worker_seen_at=NULL,attempts=0 WHERE team_id=?",(now,team['id']))
                if frozen:  # a fresh retry gets a fresh 403 propagation grace window
                    fstate=json.loads(frozen['state']);fstate.pop('stage_key',None);fstate.pop('stage_started_at',None)
                    conn.execute('UPDATE activation_runtime SET state=? WHERE team_id=?',(json.dumps(fstate),team['id']))
            created=current['created_at']
        else:
            # Quota: enabled, non-demo teams that hold or are creating resources. A failed activation still at stage 0
            # (registry never created) holds nothing and is not counted. A failure at a later stage may own partial
            # resources, so it keeps counting (we cannot tell cheaply what exists).
            count=conn.execute("SELECT a.team_id FROM activations a JOIN teams t ON t.id=a.team_id WHERE a.mode='live' AND t.enabled=1 AND t.demo=0 AND NOT (a.status='failed' AND a.step=0)").fetchall()
            if len(count)>=app.config['TEAM_ACTIVATION_LIMIT']:return jsonify(error='จำนวนกลุ่มถึงขีดจำกัดรายวิชา กรุณาติดต่อ TA'),409
            if frozen is None:conn.execute('INSERT INTO activation_runtime VALUES(?,?,?)',(team['id'],identity_key,json.dumps({'identity':identity,'operations':{}})))
            conn.execute("INSERT INTO activations(team_id,repo,mode,status,created_at,updated_at) VALUES(?,?,'live','queued',?,?) ON CONFLICT(team_id) DO UPDATE SET repo=excluded.repo,mode='live',status='queued',step=0,error=NULL,outputs='{}',created_at=excluded.created_at,updated_at=excluded.updated_at,lease_until=0,attempts=0,worker_seen_at=NULL,github_link_status=NULL,github_link_error=NULL,github_link_at=NULL",(team['id'],repo,now,now))
            conn.execute('INSERT INTO events(team_id,action,at,detail) VALUES(?,?,?,?)',(team['id'],'live_queued',now,'Queued group infrastructure'+(' without GitHub' if not identity else '')))
            created=now
    try:enqueue(app.config,team['id'],created,retry=retry)
    except (Pending,ProvisionError):
        return jsonify(error='บันทึกงานแล้วแต่ส่งเข้าคิวไม่สำเร็จ กด Activate อีกครั้งเพื่อส่งงานเดิม'),503
    return jsonify(status='queued'),202


def process_live(app,team_id,api=None):
    from membership import member_emails,process_members
    with app.db() as conn:
        completed=conn.execute("SELECT status,github_link_status FROM activations WHERE team_id=? AND mode='live'",(team_id,)).fetchone()
    if completed and completed['status']=='ready' and completed['github_link_status'] not in ('queued','running'):return process_members(app,team_id,api)
    now=int(time.time());token=secrets.randbelow(1_000_000_000)+1
    with app.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute("SELECT a.*,t.name,t.email,t.prefix,t.enabled FROM activations a JOIN teams t ON t.id=a.team_id WHERE a.team_id=? AND a.mode='live'",(team_id,)).fetchone()
        if not row:return {'ignored':True},200
        linking=row['status']=='ready' and row['github_link_status'] in ('queued','running')
        if row['status'] in ('ready','failed') and not linking:return {'status':row['status']},200
        if not row['enabled']:return {'disabled':True},200
        if row['lease_until']>now:return {'busy':True},503
        runtime=conn.execute('SELECT state FROM activation_runtime WHERE team_id=?',(team_id,)).fetchone()
        if not runtime:return {'missing_state':True},500
        state=json.loads(runtime['state'])
        # The 403 (IAM propagation) grace window runs from the start of the current stage, not from the first
        # request: teams queue behind the Cloud SQL create cap, so later stages may start long after created_at.
        stage_key='link:'+str(row['github_link_at']) if linking else 'step:'+str(row['step'])
        if state.get('stage_key')!=stage_key:
            state['stage_key']=stage_key;state['stage_started_at']=now
            conn.execute('UPDATE activation_runtime SET state=? WHERE team_id=?',(json.dumps(state),team_id))
        stage_started=state.get('stage_started_at',now)
        if linking:conn.execute("UPDATE activations SET github_link_status='running',attempts=?,lease_until=?,worker_seen_at=? WHERE team_id=?",(token,now+150,now,team_id))
        else:conn.execute("UPDATE activations SET status='running',attempts=?,lease_until=?,updated_at=?,worker_seen_at=? WHERE team_id=?",(token,now+150,now,now,team_id))
    team={'id':team_id,'name':row['name'],'email':row['email'],'prefix':row['prefix']}
    with app.db() as conn:team['member_emails']=member_emails(conn,team,ready_only=True)  # grant others via process_members after ready
    def save(value):
        with app.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            current=conn.execute('SELECT attempts FROM activations WHERE team_id=?',(team_id,)).fetchone()
            if current['attempts']!=token:raise LeaseLost('Worker lease changed')
            conn.execute('UPDATE activation_runtime SET state=? WHERE team_id=?',(json.dumps(value),team_id))
            beat=int(time.time())
            # Only a worker writes the heartbeat; a GitHub link must not move the finished resources' updated_at.
            if linking:conn.execute('UPDATE activations SET lease_until=?,worker_seen_at=? WHERE team_id=?',(beat+150,beat,team_id))
            else:conn.execute('UPDATE activations SET lease_until=?,updated_at=?,worker_seen_at=? WHERE team_id=?',(beat+150,beat,beat,team_id))
    detail=None;failed=False;step=5 if linking else row['step'];outputs={}
    try:
        worker=Provisioner(team,state['identity'],state,save,api)  # invalid identity is a recorded failure, not a 500 retry loop
        worker.step(step);step+=1
        if step==6:outputs=worker.outputs()
    except Pending as err:detail=str(err)
    except CloudError as err:
        detail=str(err);failed=not (err.status==403 and now-stage_started<1800)
    except ProvisionError as err:detail=str(err);failed=True
    except Exception:
        # Never return request/credential payloads or provider exception strings.
        detail='Provisioning interrupted. Retry will resume the existing resources.'
    ready=step==6
    if linking:return _finish_link(app,team,team_id,token,state,ready,failed,detail,outputs,api)
    report=_review_report(app,team,state) if ready else None  # CPU work stays outside the DB transaction/advisory lock
    with app.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        changed=conn.execute('UPDATE activations SET status=?,step=?,outputs=?,error=?,updated_at=?,worker_seen_at=?,lease_until=0 WHERE team_id=? AND attempts=?',
                            ('ready' if ready else 'failed' if failed else 'running',step,json.dumps(outputs),detail,int(time.time()),int(time.time()),team_id,token))
        if changed.rowcount:
            conn.execute('INSERT INTO events(team_id,action,at,detail) VALUES(?,?,?,?)',(team_id,'live_step',int(time.time()),detail or 'Infrastructure stage '+str(step)+' completed'))
            if report is not None:conn.execute('UPDATE repo_reviews SET report=? WHERE team_id=?',(json.dumps(report),team_id))
    # Cloud Tasks retries the same durable job until it is ready or permanently failed.
    if ready:
        member_result,code=process_members(app,team_id,api)
        if code!=200:return member_result,code
    return {'status':'ready' if ready else 'failed' if failed else 'pending'},200 if ready or failed else 503


def _review_report(app,team,state):
    """Re-inspect the saved snapshot as a live proposal. Returns None when there is nothing to update."""
    with app.db() as conn:
        snapshot=conn.execute('SELECT * FROM repo_snapshots WHERE team_id=?',(team['id'],)).fetchone()
    if not snapshot or not state['identity']:return None
    from repo_review import inspect_files
    try:return inspect_files(state['identity']['repo'],snapshot['sha'],json.loads(snapshot['files']),team['prefix'],preview=False)
    except ValueError:return None


def _finish_link(app,team,team_id,token,state,connected,failed,detail,outputs,api):
    """Settle only the GitHub sub-state; the ready resources, their outputs and timing stay untouched."""
    now=int(time.time())
    report=_review_report(app,team,state) if connected else None
    with app.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if connected:
            changed=conn.execute("UPDATE activations SET outputs=?,github_link_status=NULL,github_link_error=NULL,worker_seen_at=?,lease_until=0 WHERE team_id=? AND attempts=?",(json.dumps(outputs),now,team_id,token))
        else:
            changed=conn.execute("UPDATE activations SET github_link_status=?,github_link_error=?,worker_seen_at=?,lease_until=0 WHERE team_id=? AND attempts=?",('failed' if failed else 'running',detail,now,team_id,token))
        if changed.rowcount:
            conn.execute('INSERT INTO events(team_id,action,at,detail) VALUES(?,?,?,?)',(team_id,'github_linked' if connected else 'github_link_failed' if failed else 'github_link_waiting',now,detail or 'GitHub connected to existing infrastructure'))
            if report is not None:conn.execute('UPDATE repo_reviews SET report=? WHERE team_id=?',(json.dumps(report),team_id))
    if connected:
        from membership import process_members
        member_result,code=process_members(app,team_id,api)
        if code!=200:return member_result,code
    return {'status':'ready' if connected else 'github_failed' if failed else 'pending'},200 if connected or failed else 503
