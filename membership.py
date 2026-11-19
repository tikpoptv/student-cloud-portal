"""TA-maintained group membership and private-worker permission synchronization."""
import json,re,secrets,sqlite3,time
from flask import abort,jsonify,request
from live_provision import Provisioner,Pending,ProvisionError,CloudError,RevokeIncomplete,LeaseLost,enqueue

try:
    import psycopg
    INTEGRITY=(sqlite3.IntegrityError,psycopg.IntegrityError)
except ImportError:  # SQLite preview without the PostgreSQL driver
    INTEGRITY=(sqlite3.IntegrityError,)

MAX_TEAMS=200
GMAIL_DOMAINS=('gmail.com','googlemail.com')
BAD_MEMBER='Google ไม่รู้จักอีเมลนี้หรืออีเมลไม่ถูกต้อง กรุณาตรวจตัวสะกด แล้วลบสมาชิกและเพิ่มใหม่'
GENERIC='ยังให้สิทธิ์ Cloud ไม่ครบ ระบบจะลองใหม่หรือติดต่อ TA'
REVOKE_GENERIC='ยังเพิกถอนสิทธิ์ Cloud ไม่สำเร็จ ระบบจะลองใหม่หรือกดลองอีกครั้ง'
WAIT_ACTIVATION='รอให้กลุ่ม Activate เสร็จก่อน ระบบจะให้สิทธิ์ให้เองอัตโนมัติ'
ACTIVATION_FAILED='การ Activate ของกลุ่มยังไม่สำเร็จ ต้อง Activate ใหม่ก่อน ระบบจึงจะให้สิทธิ์'
QUEUE_FAILED='ส่งงานเข้าคิวไม่สำเร็จ กรุณากดซิงก์สิทธิ์อีกครั้ง'
REVOKE_TARGETS=' (ทรัพยากรที่ยังไม่สำเร็จ: '
REMOVE_WAIT='รอให้กลุ่ม Activate เสร็จ ระบบจะเพิกถอนสิทธิ์ให้เอง'
# Statuses whose Cloud permissions are (or may be) granted and that the sync should still grant.
GRANTABLE=('waiting','pending')


def identity(value):
    """Canonical identity for duplicate/ownership comparison only (never an IAM principal).

    Dots and +tags are ignored only for Gmail, where Google treats them as the same
    mailbox. Other domains keep the exact local part: john.doe@uni.ac.th is not johndoe@gmail.com.
    """
    local,_,domain=value.strip().lower().partition('@')
    if domain in GMAIL_DOMAINS:return local.split('+')[0].replace('.','')+'@gmail.com'
    return local+'@'+domain


def token(n):return secrets.token_hex(n)


def member_emails(conn,team,ready_only=False):
    """Emails that should hold group permissions (excludes members being removed or rejected by Google).

    ready_only=True is for infrastructure provisioning: only the primary email and members whose grant already
    succeeded. Waiting/pending members are left to process_members, which grants (and fails) them one by one,
    so a single mistyped Gmail can never make a whole policy (and the activation) fail."""
    query="SELECT email FROM team_members WHERE team_id=? AND cloud_status "+("='ready'" if ready_only else "NOT IN ('removing','failed')")
    return sorted({team['email']}|{r['email'] for r in conn.execute(query,(team['id'],)).fetchall()})


def valid_gmail(email):
    if len(email)>254 or not email.endswith('@gmail.com'):return False
    local=email[:-len('@gmail.com')]
    # Gmail usernames: 6-30 letters/digits/dots, no leading/trailing/consecutive dots, no '+'.
    return 6<=len(local)<=30 and re.fullmatch(r'[a-z0-9]+(\.[a-z0-9]+)*',local) is not None


def register_membership(app,admin):
    with app.db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS team_members(
          email TEXT PRIMARY KEY,team_id TEXT NOT NULL REFERENCES teams(id),google_sub TEXT,
          added_at INTEGER NOT NULL,added_by TEXT NOT NULL,cloud_status TEXT NOT NULL DEFAULT 'waiting',cloud_error TEXT
        );''')
    def ta_identities():
        from app import normalize_email
        return {identity(normalize_email(e)) for e in app.config['TA_EMAILS'].split(',') if e.strip()}
    def address(data):
        from app import normalize_email
        value=data.get('email')
        if not isinstance(value,str):abort(400,'รูปแบบ Gmail ไม่ถูกต้อง')
        # Stored lowercase and exact: Google ignores dots but IAM matches the exact string, so we keep the
        # typed dots (the IAM principal is this stored string) and reject '+' tags. Login and duplicate
        # checks compare identity() values instead of the raw string.
        email=normalize_email(value)
        if not valid_gmail(email):abort(400,'รูปแบบ Gmail ไม่ถูกต้อง')
        if identity(email) in ta_identities():abort(400,'อีเมลนี้เป็นบัญชี TA ไม่สามารถเพิ่มเป็นสมาชิกได้')
        return email
    def available(c,email):
        registered=c.execute('SELECT email FROM teams UNION SELECT email FROM team_members').fetchall()
        # Detect Gmail aliases for conflicts only; the IAM principal stays the exact stored address.
        if any(identity(r['email'])==identity(email) for r in registered):
            abort(409,'อีเมลนี้อยู่ในกลุ่มแล้ว กรุณาตรวจรายชื่อก่อนเพิ่ม')

    @app.post('/api/admin/teams')
    @admin
    def add_team():
        data=request.get_json(silent=True)
        if not isinstance(data,dict):abort(400)
        email=address(data);name=data.get('name','')
        if not isinstance(name,str):abort(400,'ชื่อกลุ่มต้องยาว 2-80 ตัวอักษร')
        name=' '.join(name.split())
        if not 2<=len(name)<=80:abort(400,'ชื่อกลุ่มต้องยาว 2-80 ตัวอักษร')
        now=int(time.time())
        for _ in range(8):
            tid=token(6);prefix='s'+token(6)[:8]
            try:
                with app.db() as c:
                    c.execute('BEGIN IMMEDIATE');available(c,email)
                    rows=c.execute('SELECT name FROM teams WHERE demo=0').fetchall()
                    if len(rows)>=MAX_TEAMS:abort(409,'จำนวนกลุ่มเต็มแล้ว กรุณาติดต่อผู้ดูแลระบบ')
                    if any(r['name'].casefold()==name.casefold() for r in rows):abort(409,'มีชื่อกลุ่มนี้อยู่แล้ว')
                    c.execute('INSERT INTO teams(id,name,email,prefix) VALUES(?,?,?,?)',(tid,name,email,prefix))
                    c.execute('INSERT INTO admin_audit(email,action,at,detail) VALUES(?,?,?,?)',(app.current_admin(),'add_team',now,tid+' '+email))
                return jsonify(team_id=tid,prefix=prefix),201
            except INTEGRITY:continue  # id/prefix collision (or a racing duplicate): draw new identifiers
        abort(409,'สร้างกลุ่มไม่สำเร็จ กรุณาลองอีกครั้ง')

    @app.post('/api/admin/teams/<team_id>/members')
    @admin
    def add_member(team_id):
        data=request.get_json(silent=True)
        if not isinstance(data,dict):abort(400)
        email=address(data);now=int(time.time());confirmed=data.get('confirm') is True
        with app.db() as c:
            c.execute('BEGIN IMMEDIATE')
            team=c.execute('SELECT * FROM teams WHERE id=? AND demo=0 AND enabled=1',(team_id,)).fetchone()
            if not team:abort(404)
            existing=c.execute('SELECT * FROM team_members WHERE email=? AND team_id=?',(email,team_id)).fetchone()
            if team['email']==email:return jsonify(saved=True,duplicate=True,cloud_status='primary'),200
            if existing and existing['cloud_status']=='removing':abort(409,'สมาชิกนี้กำลังถูกเพิกถอนสิทธิ์ รอให้เสร็จก่อนจึงเพิ่มใหม่')
            if not existing:
                available(c,email)
                # A mistyped but real address would silently receive group permissions: require explicit confirmation.
                if not confirmed:
                    return jsonify(error='กรุณายืนยันอีเมลที่จะเพิ่มก่อน',preview=True,confirm_required=True,emails=[email]),400
                try:
                    c.execute('INSERT INTO team_members(email,team_id,added_at,added_by) VALUES(?,?,?,?)',(email,team_id,now,app.current_admin()))
                except INTEGRITY:abort(409,'อีเมลนี้อยู่ในกลุ่มแล้ว กรุณาตรวจรายชื่อก่อนเพิ่ม')
                c.execute('INSERT INTO admin_audit(email,action,at,detail) VALUES(?,?,?,?)',(app.current_admin(),'add_member',now,team_id+' '+email))
            activation=c.execute("SELECT status FROM activations WHERE team_id=? AND mode='live'",(team_id,)).fetchone()
        status=existing['cloud_status'] if existing else 'waiting'
        if status!='ready' and activation:
            ready=activation['status']=='ready'
            note=None if ready else (ACTIVATION_FAILED if activation['status']=='failed' else WAIT_ACTIVATION)
            with app.db() as c:c.execute("UPDATE team_members SET cloud_status='pending',cloud_error=? WHERE team_id=? AND email=? AND cloud_status IN ('waiting','pending','failed')",(note,team_id,email))
            status='pending'
            # Not ready yet: do not queue a task that can only answer 503 until retries run out;
            # process_live syncs pending members as soon as the activation reaches ready.
            if ready:
                try:enqueue(app.config,team_id,now,retry=True,kind='members')
                except Exception:
                    with app.db() as c:c.execute("UPDATE team_members SET cloud_status='waiting',cloud_error=? WHERE team_id=? AND email=? AND cloud_status IN ('waiting','pending')",(QUEUE_FAILED,team_id,email))
                    status='waiting'
        elif existing and status=='failed':
            with app.db() as c:c.execute("UPDATE team_members SET cloud_status='waiting',cloud_error=NULL WHERE team_id=? AND email=? AND cloud_status='failed'",(team_id,email))
            status='waiting'
        return jsonify(saved=True,cloud_status=status,emails=[email]),200 if existing else 201

    @app.post('/api/admin/teams/<team_id>/members/remove')
    @admin
    def remove_member(team_id):
        from app import normalize_email
        data=request.get_json(silent=True)
        if not isinstance(data,dict) or not isinstance(data.get('email'),str):abort(400)
        email=normalize_email(data['email']);now=int(time.time())
        with app.db() as c:
            c.execute('BEGIN IMMEDIATE')
            team=c.execute('SELECT * FROM teams WHERE id=? AND demo=0',(team_id,)).fetchone()
            if not team:abort(404)
            if team['email']==email:abort(400,'ไม่สามารถลบอีเมลหลักของกลุ่มได้')
            member=c.execute('SELECT * FROM team_members WHERE email=? AND team_id=?',(email,team_id)).fetchone()
            if not member:return jsonify(removed=True,already=True,cloud_status='removed'),200  # idempotent
            activation=c.execute("SELECT status FROM activations WHERE team_id=? AND mode='live'",(team_id,)).fetchone()
            runtime=c.execute('SELECT 1 FROM activation_runtime WHERE team_id=?',(team_id,)).fetchone()
            c.execute('INSERT INTO admin_audit(email,action,at,detail) VALUES(?,?,?,?)',(app.current_admin(),'remove_member',now,team_id+' '+email))
            if not activation or not runtime:
                # No runtime state means provisioning never started: nothing was ever granted in Cloud.
                c.execute('DELETE FROM team_members WHERE email=? AND team_id=?',(email,team_id))
                return jsonify(removed=True,cloud_status='removed'),200
            # Any status with runtime state (failed/running/queued too) may already hold granted roles
            # (stage 3 grants project-level and actAs roles), so revocation is always queued.
            c.execute("UPDATE team_members SET cloud_status='removing',cloud_error=NULL WHERE email=? AND team_id=?",(email,team_id))
        try:enqueue(app.config,team_id,now,retry=True,kind='members')
        except Exception:
            with app.db() as c:c.execute("UPDATE team_members SET cloud_error=? WHERE team_id=? AND email=? AND cloud_status='removing'",(QUEUE_FAILED,team_id,email))
        return jsonify(removed=False,cloud_status='removing'),202

    def set_team_enabled(team_id,enabled):
        now=int(time.time())
        with app.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT id FROM teams WHERE id=? AND demo=0',(team_id,)).fetchone():abort(404)
            c.execute('UPDATE teams SET enabled=? WHERE id=?',(1 if enabled else 0,team_id))
            c.execute('INSERT INTO admin_audit(email,action,at,detail) VALUES(?,?,?,?)',(app.current_admin(),'enable_team' if enabled else 'disable_team',now,team_id))
            runtime=c.execute('SELECT 1 FROM activation_runtime WHERE team_id=?',(team_id,)).fetchone()
        if not runtime:return jsonify(enabled=enabled,cloud_sync='not_needed'),200
        # Disabling revokes every user principal of the group; enabling re-grants them. Idempotent: pressing again re-queues.
        try:enqueue(app.config,team_id,now,retry=True,kind='members');sync='queued'
        except Exception:sync='queue_failed'
        return jsonify(enabled=enabled,cloud_sync=sync),200

    @app.post('/api/admin/teams/<team_id>/disable')
    @admin
    def disable_team(team_id):return set_team_enabled(team_id,False)

    @app.post('/api/admin/teams/<team_id>/enable')
    @admin
    def enable_team(team_id):return set_team_enabled(team_id,True)


def classify(exc,revoke=False):
    """Return (status,error,retry) for a failed Cloud call."""
    if revoke and isinstance(exc,RevokeIncomplete):
        return 'removing',REVOKE_GENERIC+REVOKE_TARGETS+', '.join(exc.failed[:6])+')',exc.transient
    if isinstance(exc,CloudError) and exc.status in (400,404):
        # Google rejected the request itself (e.g. a nonexistent user principal): retrying cannot help.
        return ('removing' if revoke else 'failed'),(REVOKE_GENERIC if revoke else BAD_MEMBER),False
    return ('removing' if revoke else 'pending'),(REVOKE_GENERIC if revoke else GENERIC),True


def process_members(app,team_id,api=None):
    """Grant pending members and revoke removed ones (all members when the team is disabled).

    Revocation runs for any activation status that has runtime state; grants only once ready. Everything runs
    under the same lease/token fencing as the activation workers."""
    now=int(time.time());token_=secrets.randbelow(1_000_000_000)+1
    with app.db() as c:
        c.execute('BEGIN IMMEDIATE')
        team=c.execute('SELECT * FROM teams WHERE id=? AND demo=0',(team_id,)).fetchone()
        if not team:return {'status':'no_pending_members'},200
        enabled=bool(team['enabled'])
        rows=c.execute("SELECT email,cloud_status FROM team_members WHERE team_id=?",(team_id,)).fetchall()
        job=c.execute("SELECT * FROM activations WHERE team_id=? AND mode='live'",(team_id,)).fetchone()
        runtime=c.execute('SELECT state FROM activation_runtime WHERE team_id=?',(team_id,)).fetchone()
        state=json.loads(runtime['state']) if runtime else None
        revoked_all=bool(state and state.get('access_revoked_at'))
        removing=[r['email'] for r in rows if r['cloud_status']=='removing']
        pending=[r['email'] for r in rows if r['cloud_status'] in GRANTABLE] if enabled else []
        ready_emails=[r['email'] for r in rows if r['cloud_status']=='ready']
        regrant=enabled and revoked_all  # team re-enabled after a full revocation
        if enabled:revoke=removing
        else:revoke=[] if revoked_all else sorted({team['email']}|{r['email'] for r in rows})  # disabled: everyone loses access
        if not (revoke or pending or regrant):return {'status':'no_pending_members'},200
        if not job:return {'status':'waiting_activation'},200
        if job['lease_until']>now:return {'status':'waiting_activation'},503
        if not runtime:return {'status':'missing_state'},503
        can_grant=job['status']=='ready'
        if not can_grant and not revoke:return {'status':'waiting_activation'},503
        team=dict(team);team['member_emails']=member_emails(c,team)
        c.execute('UPDATE activations SET attempts=?,lease_until=? WHERE team_id=?',(token_,now+150,team_id))
    def save(value):
        with app.db() as c:
            c.execute('BEGIN IMMEDIATE')
            current=c.execute('SELECT attempts FROM activations WHERE team_id=?',(team_id,)).fetchone()
            if current['attempts']!=token_:raise LeaseLost('Membership lease changed')
            c.execute('UPDATE activations SET lease_until=? WHERE team_id=?',(int(time.time())+150,team_id))
    def provisioner():return Provisioner(team,state['identity'],state,save,api)
    outcome={};retry=False;removed=[];revoke_ok=False;regrant_ok=False
    # Revoke first: access removal must not wait behind a failing grant.
    if revoke:
        try:
            provisioner().revoke_members(['user:'+e for e in revoke]);revoke_ok=True
            removed=list(removing)
        except Exception as exc:
            status,error,again=classify(exc,revoke=True);retry=retry or again
            for e in revoke:outcome[e]=(status,error)
    if can_grant and regrant:
        try:
            provisioner().grant_members(['user:'+e for e in sorted({team['email']}|set(ready_emails))]);regrant_ok=True
        except Exception as exc:
            retry=classify(exc)[2] or retry
    if can_grant and pending:
        try:
            provisioner().grant_members()
            for e in pending:outcome[e]=('ready',None)
        except Exception:
            # One rejected principal fails the whole IAM policy: grant each member on its own so valid
            # members succeed and the bad one gets its own readable error.
            for e in pending:
                try:
                    provisioner().grant_members(['user:'+e]);outcome[e]=('ready',None)
                except Exception as exc:
                    status,error,again=classify(exc);retry=retry or again;outcome[e]=(status,error)
    with app.db() as c:
        c.execute('BEGIN IMMEDIATE')
        current=c.execute('SELECT attempts FROM activations WHERE team_id=?',(team_id,)).fetchone()
        if current['attempts']!=token_:return {'status':'lease_changed'},503
        for e,(status,error) in outcome.items():
            guard=("'removing'" if status=='removing' else "'waiting','pending'")
            c.execute(f'UPDATE team_members SET cloud_status=?,cloud_error=? WHERE email=? AND team_id=? AND cloud_status IN ({guard})',(status,error,e,team_id))
        for e in removed:
            c.execute("DELETE FROM team_members WHERE email=? AND team_id=? AND cloud_status='removing'",(e,team_id))
            c.execute('INSERT INTO events(team_id,action,at,detail) VALUES(?,?,?,?)',(team_id,'member_removed',int(time.time()),'Group member cloud permissions revoked'))
        if not enabled and revoke_ok:state['access_revoked_at']=int(time.time())
        if regrant_ok:state.pop('access_revoked_at',None)
        if (not enabled and revoke_ok) or regrant_ok:c.execute('UPDATE activation_runtime SET state=? WHERE team_id=?',(json.dumps(state),team_id))
        c.execute('UPDATE activations SET lease_until=0 WHERE team_id=?',(team_id,))
        if pending and all(outcome.get(e,('',))[0]=='ready' for e in pending):c.execute('INSERT INTO events(team_id,action,at,detail) VALUES(?,?,?,?)',(team_id,'members_synced',int(time.time()),'Group member cloud permissions synchronized'))
        remaining=c.execute("SELECT email,cloud_status FROM team_members WHERE team_id=? AND cloud_status IN ('waiting','pending','removing','failed')",(team_id,)).fetchall()
    if not enabled:return {'status':'pending' if retry else 'revoked' if revoke_ok else 'attention'},503 if retry else 200
    # Transient failures keep Cloud Tasks retrying; permanent per-member errors are recorded and answered 200.
    state_name='pending' if retry else ('failed' if any(r['cloud_status']=='failed' for r in remaining) else 'ready' if not remaining else 'attention')
    return {'status':state_name},503 if retry else 200
