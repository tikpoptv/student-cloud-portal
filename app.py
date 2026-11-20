"""Single-host course portal. Preview provisions a plan, never cloud resources."""
import csv
import requests
import hashlib
import io
import zipfile
import json
import os
import re
import secrets
import time
from datetime import timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from database import connect
from activation import activate_live, process_live
from localization import translate, localize_payload, language_for_request
from authlib.integrations.flask_client import OAuth
from flask import Flask, abort, jsonify, redirect, render_template, request, session, send_file

ROOT = Path(__file__).parent
STEPS = [
    ('registry', 'เตรียมที่เก็บ Docker image', 'Artifact Registry'),
    ('database', 'เตรียมฐานข้อมูลของกลุ่ม', 'Cloud SQL · PostgreSQL'),
    ('identity', 'เตรียมบัญชีสำหรับแอป', 'Runtime service account'),
    ('secrets', 'เตรียมการเชื่อมต่อฐานข้อมูล', 'Secret Manager'),
    ('deployment', 'เตรียมพื้นที่สำหรับ deploy', 'Cloud Run service + migration job'),
    ('github', 'เตรียม logs และการเชื่อมต่อเพิ่มเติม', 'Logs · GitHub (ถ้าเลือก)'),
]


def env_int(name, default):
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        return default
    return value if value > 0 else default


def normalize_email(value):
    # Do not remove dots or plus suffixes: matching the approved address is intentional.
    return ''.join(c for c in value.strip().lower() if c not in '\u200e\u200f\ufeff').strip()


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get('SESSION_SECRET', ''),
        DATABASE=os.environ.get('DATABASE', str(ROOT / 'private' / 'portal.sqlite3')),
        DATABASE_URL=os.environ.get('DATABASE_URL', ''),
        PREVIEW=os.environ.get('PORTAL_MODE', 'preview') == 'preview',
        BASE_URL=os.environ.get('BASE_URL', 'http://127.0.0.1:8876').rstrip('/'),
        AUTH_MODE=os.environ.get('AUTH_MODE', ''),
        GOOGLE_CLIENT_ID=os.environ.get('GOOGLE_CLIENT_ID', ''),
        GOOGLE_CLIENT_SECRET=os.environ.get('GOOGLE_CLIENT_SECRET', ''),
        LIVE_ACTIVATION_ENABLED=os.environ.get('LIVE_ACTIVATION_ENABLED') == '1',
        LIVE_WORKER=os.environ.get('LIVE_WORKER') == '1',
        ENFORCE_CANONICAL_HOST=os.environ.get('ENFORCE_CANONICAL_HOST') == '1',
        WORKER_URL=os.environ.get('WORKER_URL', '').rstrip('/'),
        TASK_IDENTITY='cpe334-tasks@cpe-se-course-2026.iam.gserviceaccount.com',
        # Course has ~38 teams; Cloud SQL allows 40 instances including the portal DB (guard in live_provision.database).
        TEAM_ACTIVATION_LIMIT=env_int('TEAM_ACTIVATION_LIMIT',39),
        ACTIVATE_MIN_INTERVAL=5,REVIEW_MIN_INTERVAL=15,REVIEW_INFLIGHT_SECONDS=60,
        BILLING_SINCE=os.environ.get('BILLING_SINCE','2026-11-01'),
        TA_EMAILS=os.environ.get('TA_EMAILS', ''),
        BILLING_EXPORT_TABLE=os.environ.get('BILLING_EXPORT_TABLE', ''),
        BILLING_EXPORT_LOCATION=os.environ.get('BILLING_EXPORT_LOCATION', 'US'),
        # Web Push (optional): without all three the chat works but sends no notifications.
        VAPID_PUBLIC_KEY=os.environ.get('VAPID_PUBLIC_KEY', ''), VAPID_PRIVATE_KEY=os.environ.get('VAPID_PRIVATE_KEY', ''), VAPID_SUBJECT=os.environ.get('VAPID_SUBJECT', ''),
        PROJECT_ID='cpe-se-course-2026', REGION='asia-southeast1',
        MAX_CONTENT_LENGTH=16384,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=4),
    )
    if overrides:
        app.config.update(overrides)
    app.config['AUTH_MODE'] = app.config['AUTH_MODE'] or ('demo' if app.config['PREVIEW'] else 'google')
    if app.config['AUTH_MODE'] not in ('demo', 'google'):
        raise RuntimeError('AUTH_MODE must be demo or google')
    if app.config['AUTH_MODE'] == 'demo' and not app.config['PREVIEW']:
        raise RuntimeError('Demo authentication requires preview mode')
    base = urlsplit(app.config['BASE_URL'])
    if app.config['AUTH_MODE'] == 'google' and (base.scheme != 'https' and not (base.scheme == 'http' and base.hostname in ('localhost', '127.0.0.1', '::1'))):
        raise RuntimeError('Google login requires HTTPS except on loopback')
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
    if not app.config['SECRET_KEY']:
        if not app.config['PREVIEW'] or app.config['AUTH_MODE'] == 'google':
            raise RuntimeError('SESSION_SECRET is required for Google authentication')
        keyfile = Path(app.config['DATABASE']).with_suffix('.key')
        if not keyfile.exists():
            keyfile.write_text(secrets.token_hex(32))
            keyfile.chmod(0o600)
        app.config['SECRET_KEY'] = keyfile.read_text()
    app.config['SESSION_COOKIE_SECURE'] = base.scheme == 'https'
    if not app.config['PREVIEW'] and not app.config['BASE_URL'].startswith('https://'):
        raise RuntimeError('HTTPS BASE_URL is required outside preview')

    def db():
        return connect(app.config['DATABASE'], app.config['DATABASE_URL'])

    app.db = db

    def throttle(key, interval, hold=0, wait_message=''):
        """Per-key minimum interval counting every attempt (failures too), optional in-flight guard.
        Returns a Thai 429 message, or None when allowed (the attempt time is recorded before any GitHub call)."""
        now = int(time.time())
        with db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT at,busy_until FROM rate_limits WHERE key=?', (key,)).fetchone()
            if row and row['busy_until'] > now:
                return REVIEW_BUSY
            if row and now - row['at'] < interval:
                return wait_message.format(seconds=interval)
            conn.execute('INSERT INTO rate_limits(key,at,busy_until) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET at=excluded.at,busy_until=excluded.busy_until',
                         (key, now, now + hold if hold else 0))
        return None

    def release(key):
        with db() as conn:
            conn.execute('UPDATE rate_limits SET busy_until=0 WHERE key=?', (key,))
    with db() as conn:
        conn.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS teams (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
          prefix TEXT UNIQUE NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
          google_sub TEXT, demo INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS activations (
          team_id TEXT PRIMARY KEY REFERENCES teams(id), repo TEXT NOT NULL,
          mode TEXT NOT NULL, status TEXT NOT NULL, step INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
          lease_until INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
          error TEXT, outputs TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, team_id TEXT NOT NULL,
          action TEXT NOT NULL, at INTEGER NOT NULL, detail TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS repo_reviews (
          team_id TEXT PRIMARY KEY REFERENCES teams(id), repo TEXT NOT NULL,
          report TEXT NOT NULL, created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS activation_runtime (
          team_id TEXT PRIMARY KEY REFERENCES teams(id), repository_id TEXT UNIQUE NOT NULL,
          state TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS repo_snapshots (
          team_id TEXT PRIMARY KEY REFERENCES teams(id), sha TEXT NOT NULL, files TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rate_limits (
          key TEXT PRIMARY KEY, at INTEGER NOT NULL DEFAULT 0, busy_until INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS oauth_states (
          digest TEXT PRIMARY KEY, expires INTEGER NOT NULL
        );
        ''')
        # Worker heartbeat and GitHub-link sub-state live beside, not inside, the resource status.
        for column in ('worker_seen_at INTEGER','github_link_status TEXT','github_link_error TEXT','github_link_at INTEGER'):
            if app.config['DATABASE_URL']:
                conn.execute('ALTER TABLE activations ADD COLUMN IF NOT EXISTS '+column)
            elif column.split()[0] not in {r['name'] for r in conn.execute('PRAGMA table_info(activations)').fetchall()}:
                conn.execute('ALTER TABLE activations ADD COLUMN '+column)
        if app.config['PREVIEW']:
            conn.execute('INSERT OR IGNORE INTO teams(id,name,email,prefix,demo) VALUES(?,?,?,?,1)',
                         ('preview', 'KitLoop · กลุ่มทดลอง', 'student@example.test', 'demo437'))
    if not app.config['DATABASE_URL']:
        Path(app.config['DATABASE']).chmod(0o600)

    from admin_dashboard import register_admin
    def current_admin():
        email = session.get('admin_email', '')
        allowed = {normalize_email(e) for e in app.config['TA_EMAILS'].split(',') if e.strip()}
        return email if email in allowed and session.get('admin_sub') else None
    app.current_admin = current_admin
    register_admin(app)

    oauth = OAuth(app)
    oauth.register('google', client_id=app.config['GOOGLE_CLIENT_ID'],
                   client_secret=app.config['GOOGLE_CLIENT_SECRET'],
                   server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
                   client_kwargs={'scope': 'openid email profile', 'code_challenge_method': 'S256'})

    @app.before_request
    def protect():
        if app.config['ENFORCE_CANONICAL_HOST'] and not app.config['LIVE_WORKER'] and request.method == 'GET' and request.path in ('/', '/auth/google') and request.host != urlsplit(app.config['BASE_URL']).netloc:
            return redirect(app.config['BASE_URL'] + request.full_path.rstrip('?'))
        if request.path == '/internal/provision' and app.config['LIVE_WORKER']:
            return
        if app.config['AUTH_MODE'] == 'demo' and not app.config.get('TESTING'):
            if request.remote_addr not in ('127.0.0.1', '::1'):
                abort(403)
        if request.method == 'POST':
            supplied = request.headers.get('X-CSRF-Token', request.form.get('csrf', ''))
            if not supplied or not secrets.compare_digest(supplied, session.get('csrf', '')):
                abort(403, 'กรุณาโหลดหน้าใหม่แล้วลองอีกครั้ง')
        session.setdefault('csrf', secrets.token_urlsafe(32))
        if session.get('team_id') and request.path.startswith('/api/') and int(time.time())-session.get('activity_at',0)>=60:
            now=int(time.time())
            with db() as conn:
                conn.execute('INSERT INTO team_activity(team_id,last_seen) SELECT id,? FROM teams WHERE id=? AND enabled=1 ON CONFLICT(team_id) DO UPDATE SET last_seen=excluded.last_seen',(now,session['team_id']))
            session['activity_at']=now

    @app.after_request
    def headers(response):
        language = language_for_request(request)
        response.headers['Content-Language'] = language
        if response.is_json:
            payload = response.get_json()
            if isinstance(payload, dict) and isinstance(payload.get('error'), str):
                payload['error_source'] = payload['error']
            response.set_data(app.json.dumps(localize_payload(payload, language)))
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'"
        return response

    def current_team():
        tid = session.get('team_id')
        if not tid:
            return None
        with db() as conn:
            team = conn.execute('SELECT * FROM teams WHERE id=? AND enabled=1', (tid,)).fetchone()
        if team and (not team['demo'] or app.config['AUTH_MODE'] == 'demo'):
            email=session.get('member_email',team['email'])
            if email!=team['email']:
                with db() as conn:
                    if not conn.execute("SELECT email FROM team_members WHERE email=? AND team_id=? AND cloud_status!='removing'",(email,tid)).fetchone():return None
            return {**dict(team),'login_email':email}
        return None

    app.current_team = current_team
    app.throttle = throttle
    from chat import register_chat
    register_chat(app)

    def authenticated(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not current_team():
                abort(401)
            return fn(*args, **kwargs)
        return wrapped

    @app.context_processor
    def language_context():
        language = language_for_request(request)
        return {'language':language,'tr':lambda value:translate(value,language)}

    @app.get('/')
    def home():
        return render_template('index.html', team=current_team(), admin_email=current_admin(), steps=STEPS,
                               preview=app.config['PREVIEW'], csrf=session['csrf'],
                               demo_login=app.config['AUTH_MODE'] == 'demo',
                               oauth_ready=bool(app.config['AUTH_MODE'] == 'google' and app.config['GOOGLE_CLIENT_ID'] and app.config['GOOGLE_CLIENT_SECRET']))

    @app.post('/preview/login')
    def preview_login():
        if app.config['AUTH_MODE'] != 'demo':
            abort(404)
        session.clear()
        session.update(team_id='preview', csrf=secrets.token_urlsafe(32))
        return redirect('/')

    @app.get('/auth/google')
    def login():
        if app.config['AUTH_MODE'] != 'google' or not app.config['GOOGLE_CLIENT_ID'] or not app.config['GOOGLE_CLIENT_SECRET']:
            abort(503, 'ยังไม่ได้ตั้งค่า Google OAuth ใช้ปุ่มทดลองสำหรับดูระบบก่อน')
        state = secrets.token_urlsafe(32)
        with db() as conn:
            conn.execute('DELETE FROM oauth_states WHERE expires < ?', (int(time.time()),))
            conn.execute('INSERT INTO oauth_states VALUES(?,?)',
                         (hashlib.sha256(state.encode()).hexdigest(), int(time.time()) + 600))
        return oauth.google.authorize_redirect(app.config['BASE_URL'] + '/auth/callback',
                                               state=state, nonce=secrets.token_urlsafe(32), prompt='select_account')

    @app.get('/auth/callback')
    def callback():
        if app.config['AUTH_MODE'] != 'google':
            abort(404)
        state = request.args.get('state', '')
        with db() as conn:
            consumed = conn.execute('DELETE FROM oauth_states WHERE digest=? AND expires>=?',
                                   (hashlib.sha256(state.encode()).hexdigest(), int(time.time())))
            if consumed.rowcount != 1:
                abort(400, 'คำขอเข้าสู่ระบบหมดอายุแล้ว')
        try:
            # Authlib verifies issuer, signature, audience, expiry, state and nonce.
            token = oauth.google.authorize_access_token()
            user = token['userinfo']
        except Exception:
            abort(401, 'ยืนยันบัญชี Google ไม่สำเร็จ กรุณาลองใหม่')
        if user.get('email_verified') is not True or not user.get('sub'):
            abort(403)
        email = normalize_email(user.get('email', ''))
        if not email.endswith('@gmail.com') and not user.get('hd'):
            abort(403, 'บัญชีนี้ต้องให้ TA ตรวจสอบความเป็นเจ้าของอีเมลก่อน')
        allowed = {normalize_email(e) for e in app.config['TA_EMAILS'].split(',') if e.strip()}
        if email in allowed:
            with db() as conn:
                conn.execute('INSERT INTO admin_audit(email,action,at,detail) VALUES(?,?,?,?)',(email,'login',int(time.time()),'Google OIDC verified'))
            session.clear()
            session.update(admin_email=email,admin_sub=user['sub'],csrf=secrets.token_urlsafe(32))
            session.permanent=True
            return redirect('/')
        with db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            from membership import identity
            team = conn.execute('SELECT * FROM teams WHERE email=? AND enabled=1 AND demo=0', (email,)).fetchone()
            if not team:
                # Google returns the canonical Gmail address; match dotted/undotted variants by identity().
                team = next((r for r in conn.execute('SELECT * FROM teams WHERE enabled=1 AND demo=0').fetchall() if identity(r['email'])==identity(email)), None)
            if team:
                email = team['email']
                if team['google_sub'] and team['google_sub'] != user['sub']:
                    abort(403, 'ไม่พบอีเมลนี้ในรายชื่อที่ได้รับสิทธิ์ กรุณาติดต่อ TA')
                conn.execute('UPDATE teams SET google_sub=? WHERE id=?', (user['sub'], team['id']))
            else:
                member=conn.execute("SELECT * FROM team_members WHERE email=? AND cloud_status!='removing'",(email,)).fetchone()
                if not member:
                    member = next((r for r in conn.execute("SELECT * FROM team_members WHERE cloud_status!='removing'").fetchall() if identity(r['email'])==identity(email)), None)
                if member:email=member['email']
                if not member or (member['google_sub'] and member['google_sub']!=user['sub']):
                    abort(403, 'ไม่พบอีเมลนี้ในรายชื่อที่ได้รับสิทธิ์ กรุณาติดต่อ TA')
                team=conn.execute('SELECT * FROM teams WHERE id=? AND enabled=1 AND demo=0',(member['team_id'],)).fetchone()
                if not team:abort(403)
                conn.execute('UPDATE team_members SET google_sub=? WHERE email=?',(user['sub'],email))
            conn.execute('INSERT INTO events(team_id,action,at,detail) VALUES(?,?,?,?)',
                         (team['id'], 'login', int(time.time()), 'Google OIDC verified'))
        session.clear()
        session.update(team_id=team['id'],member_email=email, csrf=secrets.token_urlsafe(32))
        session.permanent = True
        return redirect('/')

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect('/')

    @app.get('/api/status')
    @authenticated
    def status():
        team = current_team()
        with db() as conn:
            row = conn.execute('SELECT * FROM activations WHERE team_id=?', (team['id'],)).fetchone()
            history = conn.execute('SELECT action,at,detail FROM events WHERE team_id=? ORDER BY id DESC LIMIT 12',
                                   (team['id'],)).fetchall()
        activation = dict(row) if row else None
        if activation:
            activation['outputs'] = (build_plan(team, activation['repo'], app.config['PROJECT_ID'], app.config['REGION'])
                                     if activation['mode'] == 'preview' else json.loads(activation['outputs']))
        progress=None
        if activation:
            with db() as conn:
                previous=conn.execute("SELECT MAX(at) at FROM events WHERE team_id=? AND action='live_step' AND detail=?",(team['id'],'Infrastructure stage '+str(activation['step'])+' completed')).fetchone()
            progress={'worker_last_seen_at':activation['worker_seen_at'],
                      'step_started_at':max(activation['created_at'],previous['at'] or activation['created_at'])}
        return jsonify(team={k: team[k] for k in ('name','email','prefix')},
                       activation=activation, progress=progress, server_time=int(time.time()),history=[dict(r) for r in history],
                       project=app.config['PROJECT_ID'], region=app.config['REGION'],
                       preview=app.config['PREVIEW'])

    @app.post('/api/activate')
    @authenticated
    def activate():
        team = current_team()
        data = request.get_json(silent=True) or {}
        if not isinstance(data,dict):abort(400)
        resources_only=data.get('resources_only') is True
        repo = data.get('repo', '')
        if not isinstance(repo, str):
            abort(400)
        repo = repo.strip().removeprefix('https://github.com/').removesuffix('/').removesuffix('.git')
        if resources_only and repo:return jsonify(error='เลือกเปิดทรัพยากรอย่างเดียวโดยไม่ระบุ repo'),400
        if not resources_only and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}', repo):
            return jsonify(error='ใส่ GitHub repository ในรูปแบบ owner/repository'), 400
        if not app.config['PREVIEW']:
            if not app.config['LIVE_ACTIVATION_ENABLED'] or not app.config['WORKER_URL']:
                return jsonify(error='TA กำลังเตรียมระบบเปิดทรัพยากรจริง ยังไม่มีการสร้างหรือคิดค่าใช้จ่าย'), 503
            wait = throttle('activate:' + team['id'], app.config['ACTIVATE_MIN_INTERVAL'], wait_message='กดเร็วเกินไป กรุณารอ {seconds} วินาทีแล้วกด Activate อีกครั้ง')
            if wait:
                return jsonify(error=wait), 429
            return activate_live(app,team,repo,resources_only=resources_only)
        now = int(time.time())
        with db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            existing = conn.execute('SELECT * FROM activations WHERE team_id=?', (team['id'],)).fetchone()
            if existing:
                if resources_only or existing['repo'].casefold() == repo.casefold():
                    return jsonify(status=existing['status'], duplicate=True), 200
                if existing['repo']:
                    return jsonify(error='กลุ่มนี้เริ่มเตรียมระบบแล้ว กรุณาใช้ repository เดิม'), 409
                # Same transition as live: connect a repository to resources that are already ready.
                if existing['status'] != 'ready':
                    return jsonify(error='รอสร้างทรัพยากรให้พร้อมก่อนเชื่อม GitHub'), 409
                conn.execute('UPDATE activations SET repo=? WHERE team_id=?', (repo, team['id']))
                conn.execute('INSERT INTO events(team_id,action,at,detail) VALUES(?,?,?,?)',
                             (team['id'], 'github_connected', now, 'จำลอง: เชื่อม repository กับทรัพยากรที่พร้อมแล้ว'))
                return jsonify(status='ready', github_connected=True), 202
            conn.execute('INSERT INTO activations(team_id,repo,mode,status,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                         (team['id'], repo, 'preview', 'queued', now, now))
            conn.execute('INSERT INTO events(team_id,action,at,detail) VALUES(?,?,?,?)',
                         (team['id'], 'queued', now, 'เริ่มจำลองการเตรียมระบบ ไม่มีการเรียก Google Cloud'))
        return jsonify(status='queued'), 202

    @app.post('/internal/provision')
    def provision_task():
        if not app.config['LIVE_WORKER']:
            abort(404)
        try:
            from google.oauth2 import id_token
            from google.auth.transport.requests import Request
            token=request.headers.get('Authorization','').removeprefix('Bearer ')
            claims=id_token.verify_oauth2_token(token,Request(),audience=app.config['WORKER_URL'])
            if claims.get('email')!=app.config['TASK_IDENTITY'] or claims.get('email_verified') is not True:
                abort(403)
        except (ValueError,KeyError):
            abort(403)
        data=request.get_json(silent=True) or {}
        if data.get('kind')=='members':
            from membership import process_members
            return process_members(app,data.get('team_id',''))
        return process_live(app,data.get('team_id',''))

    @app.get('/api/handoff')
    @authenticated
    def handoff():
        team = current_team()
        with db() as conn:
            row = conn.execute('SELECT * FROM activations WHERE team_id=?', (team['id'],)).fetchone()
        if not row or row['status'] != 'ready':
            abort(409)
        outputs = activation_outputs(team, row, app.config['PROJECT_ID'], app.config['REGION'])
        response = jsonify(outputs)
        response.headers['Content-Disposition'] = 'attachment; filename=lab5-'+team['prefix']+'-handoff.json'
        return response

    @app.get('/api/kit/download')
    def kit_download():
        team = current_team()
        if not team:
            abort(403 if session.get('admin_sub') and current_admin() else 401)
        with db() as conn:
            row = conn.execute('SELECT * FROM activations WHERE team_id=?', (team['id'],)).fetchone()
        if not row:
            abort(404)
        kit_dir = ROOT / 'project-kit'
        if not kit_dir.is_dir() or not (kit_dir / 'kit.sh').is_file():
            return jsonify(error='Project Kit ยังไม่พร้อมบนเซิร์ฟเวอร์ กรุณาแจ้ง TA'), 503
        outputs = activation_outputs(team, row, app.config['PROJECT_ID'], app.config['REGION'])
        planned = build_plan(team, row['repo'], app.config['PROJECT_ID'], app.config['REGION'])
        outputs = {**planned, **outputs, 'prefix': team['prefix'],
                   'resources': {**planned['resources'], **(outputs.get('resources') or {})}}
        env_text = kit_resources_env(outputs, ready=row['status'] == 'ready' and bool(outputs.get('created_in_google_cloud')))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            for rel in kit_files(kit_dir):
                info = zipfile.ZipInfo('project-kit/' + rel, (2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3  # Unix: required for the mode bits below to be honoured
                # S_IFREG type bits are required: without them Finder/Archive Utility extracts kit.sh as -rw-r--r--.
                info.external_attr = (0o100755 if rel in KIT_EXECUTABLES else 0o100644) << 16
                z.writestr(info, (kit_dir / rel).read_bytes())
            info = zipfile.ZipInfo('project-kit/resources.env', (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            z.writestr(info, env_text)
        response = app.response_class(buf.getvalue(), mimetype='application/zip')
        response.headers['Content-Disposition'] = 'attachment; filename=cpe334-project-kit-' + team['prefix'] + '.zip'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/api/lab5-kit/download')
    def lab5_kit_download():
        from repo_review import zip_lab5_kit
        team = current_team()
        if not team:
            abort(403 if session.get('admin_sub') and current_admin() else 401)
        ref = ROOT / 'reference-kit'
        if not all((ref / n).is_file() for n in ('deploy.sh', 'release.sh', 'deploy.yml', 'README-LAB5.template.md')):
            return jsonify(error='Lab 5 Starter Kit ยังไม่พร้อมบนเซิร์ฟเวอร์ กรุณาแจ้ง TA'), 503
        try:
            data = zip_lab5_kit(team['prefix'], app.config['PROJECT_ID'], app.config['REGION'], ref)
        except (ValueError, OSError):
            return jsonify(error='Lab 5 Starter Kit ยังไม่พร้อมบนเซิร์ฟเวอร์ กรุณาแจ้ง TA'), 503
        response = app.response_class(data, mimetype='application/zip')
        response.headers['Content-Disposition'] = 'attachment; filename=cpe334-lab5-starter-kit-' + team['prefix'] + '.zip'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/api/repo-review')
    @authenticated
    def get_repo_review():
        team = current_team()
        with db() as conn:
            row = conn.execute('SELECT report FROM repo_reviews WHERE team_id=?', (team['id'],)).fetchone()
        return jsonify(review=json.loads(row['report']) if row else None)

    @app.post('/api/repo-review')
    @authenticated
    def prepare_repo_review():
        from repo_review import normalize_repo, fetch_snapshot, inspect_files
        team = current_team()
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            abort(400)
        try:
            repo = normalize_repo(data.get('repo', ''))
            with db() as conn:
                activation = conn.execute('SELECT * FROM activations WHERE team_id=?', (team['id'],)).fetchone()
            if activation and activation['repo'] and activation['repo'].casefold() != repo.casefold():
                return jsonify(error='กลุ่มนี้มีแผนของ repository อื่นแล้ว กรุณาใช้ repo เดิมหรือให้ TA ตรวจ'), 409
            # Every attempt counts (failures too) and only one review per team runs at a time: each one can make up
            # to 10 GitHub calls and hold a thread for 45 s of the shared GitHub quota.
            wait = throttle('review:' + team['id'], app.config['REVIEW_MIN_INTERVAL'], hold=app.config['REVIEW_INFLIGHT_SECONDS'], wait_message='กรุณารอ {seconds} วินาทีก่อนอ่าน GitHub อีกครั้ง')
            if wait:
                return jsonify(error=wait), 429
            try:
                sha, files = fetch_snapshot(repo)
                can_live=bool(activation and activation['mode']=='live' and activation['status']=='ready')
                report = inspect_files(repo, sha, files, team['prefix'], preview=not can_live)
            finally:
                release('review:' + team['id'])
        except (ValueError, requests.RequestException, KeyError) as err:
            return jsonify(error=str(err) if isinstance(err, ValueError) else 'อ่าน GitHub ไม่สำเร็จ ลองใหม่อีกครั้ง'), 400
        with db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT id FROM teams WHERE id=? AND enabled=1', (team['id'],)).fetchone():
                abort(403)
            latest = conn.execute('SELECT * FROM activations WHERE team_id=?', (team['id'],)).fetchone()
            if latest and latest['repo'] and latest['repo'].casefold() != repo.casefold():
                abort(409, 'Repository ของแผนเปลี่ยนระหว่างตรวจ กรุณาโหลดใหม่')
            conn.execute('INSERT INTO repo_reviews VALUES(?,?,?,?) ON CONFLICT(team_id) DO UPDATE SET repo=excluded.repo,report=excluded.report,created_at=excluded.created_at',
                         (team['id'], repo, json.dumps(report, ensure_ascii=False), int(time.time())))
            conn.execute('INSERT INTO repo_snapshots VALUES(?,?,?) ON CONFLICT(team_id) DO UPDATE SET sha=excluded.sha,files=excluded.files',
                         (team['id'],sha,json.dumps(files)))
        return jsonify(review=report)

    @app.get('/api/repo-patch')
    @authenticated
    def download_repo_patch():
        from repo_review import patch_bytes, zip_review
        team = current_team()
        with db() as conn:
            row = conn.execute('SELECT report FROM repo_reviews WHERE team_id=?', (team['id'],)).fetchone()
        if not row:
            abort(409, 'ตรวจ repo ก่อนดาวน์โหลด')
        report = json.loads(row['report'])
        if report['status'] != 'prepared':
            abort(409, 'repo นี้ต้องให้ TA ตรวจ ยังไม่มีไฟล์แก้ไขอัตโนมัติ')
        if request.args.get('format') == 'zip':
            return send_file(zip_review(report), mimetype='application/zip', as_attachment=True,
                             download_name=f"lab5-{team['prefix']}-review.zip")
        return send_file(io.BytesIO(patch_bytes(report)), mimetype='text/plain', as_attachment=True,
                         download_name=f"lab5-{team['prefix']}.patch")

    @app.get('/api/student-kit')
    @app.get('/api/student-guide')
    @authenticated
    def retired_config_download():
        return jsonify(error='ใช้หน้า ตรวจ repo และดู diff แทน ชุด config ใหม่ถูกยกเลิกแล้ว'), 410

    @app.post('/api/preview/reset')
    @authenticated
    def reset():
        if not app.config['PREVIEW'] or current_team()['id'] != 'preview':
            abort(404)
        with db() as conn:
            conn.execute('DELETE FROM activations WHERE team_id=?', ('preview',))
            conn.execute('DELETE FROM repo_reviews WHERE team_id=?', ('preview',))
            conn.execute('DELETE FROM events WHERE team_id=?', ('preview',))
        return jsonify(ok=True)

    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(403)
    @app.errorhandler(409)
    @app.errorhandler(503)
    @app.errorhandler(404)
    @app.errorhandler(405)
    @app.errorhandler(429)
    def error(err):
        if request.path.startswith('/api/'):
            return jsonify(error=str(err.description)), err.code
        return render_template('error.html', message=err.description, code=err.code,
                               error_kind='account_access' if err.code == 403 and err.description == 'ไม่พบอีเมลนี้ในรายชื่อที่ได้รับสิทธิ์ กรุณาติดต่อ TA' else 'generic',
                               oauth_ready=bool(app.config['AUTH_MODE'] == 'google' and app.config['GOOGLE_CLIENT_ID'] and app.config['GOOGLE_CLIENT_SECRET'])), err.code

    return app


REVIEW_BUSY = 'กำลังตรวจ repo ของกลุ่มนี้อยู่ กรุณารอให้เสร็จก่อน แล้วลองอีกครั้ง'


KIT_EXECUTABLES = {'kit.sh', 'from-portal-json.sh'}
KIT_ALLOWED_TOP = {'kit.sh', 'from-portal-json.sh', 'README.md', 'README.th.md', 'resources.example.env', 'app.env.example', 'secrets.map.example', '.gitattributes'}


def kit_files(kit_dir):
    """Allowlist of student-facing kit files (never tests, caches or stray files)."""
    out = [n for n in sorted(KIT_ALLOWED_TOP) if (kit_dir / n).is_file()]
    tdir = kit_dir / 'templates'
    if tdir.is_dir():
        out += ['templates/' + p.name for p in sorted(tdir.iterdir()) if p.is_file() and not p.name.endswith('.pyc') and not p.name.startswith('.')]
    return out


def activation_outputs(team, row, project, region):
    """Single source for the Team resources handoff and the Project Kit."""
    return (build_plan(team, row['repo'], project, region)
            if row['mode'] == 'preview' else json.loads(row['outputs']))


def kit_resources_env(outputs, ready=True):
    r = outputs.get('resources') or {}
    p = outputs['prefix']
    lines = ['# resources.env - generated by the portal for team ' + p + ' only (no passwords or secrets)',
             '# resources.env - สร้างโดย portal เฉพาะกลุ่ม ' + p + ' (ไม่มีรหัสผ่านหรือความลับ)']
    if not ready:
        lines += ['# WARNING: the resources may not exist yet (not activated). The values below are planned names only.',
                  '# คำเตือน: ทรัพยากรอาจยังไม่ถูกสร้างจริง (ยังไม่ activate) ค่าด้านล่างเป็นชื่อตามแผนเท่านั้น',
                  '# Test with ./project-kit/kit.sh doctor before you deploy.',
                  '# ทดสอบด้วย ./project-kit/kit.sh doctor ก่อน deploy']
    pairs = [('PREFIX', p), ('PROJECT_ID', outputs.get('project_id')), ('REGION', outputs.get('region')),
             ('SERVICE_NAME', r.get('cloud_run_service')), ('MIGRATE_JOB_NAME', r.get('migration_job')),
             ('REGISTRY', r.get('registry')), ('IMAGE_NAME', (r.get('image_repository') or '').rsplit('/', 1)[-1] or r.get('registry')),
             ('RUNTIME_SA', r.get('runtime_service_account')), ('SQL_CONNECTION_NAME', r.get('sql_connection_name'))]
    for k, v in pairs:
        v = str(v or '')
        if v and re.fullmatch(r'[A-Za-z0-9_.:@/-]+', v):
            lines.append(f'{k}={v}')
    # STACK is intentionally NOT written: `init` must make the student choose a stack instead of silently using node.
    lines += ['PORT=8080', '']
    return '\n'.join(lines)


def build_plan(team, repo, project='cpe-se-course-2026', region='asia-southeast1'):
    p = team['prefix']
    if not re.fullmatch('[a-z][a-z0-9]{2,9}', p):
        raise ValueError('Invalid assigned prefix')
    plan = {
        'mode': 'preview', 'created_in_google_cloud': False,
        'project_id': project, 'region': region, 'prefix': p, 'github_repository': repo,
        'resources': {'cloud_run_service': p, 'migration_job': p+'-migrate',
                      'sql_instance': p+'-pg', 'database': p, 'sql_tier': 'db-f1-micro',
                      'registry': p, 'runtime_service_account': f'{p}-runner@{project}.iam.gserviceaccount.com',
                      'deployer_service_account': f'{p}-deployer@{project}.iam.gserviceaccount.com',
                      'database_secret': p+'-database-url', 'admin_password_secret': p+'-admin-password',
                      'demo_password_secret': p+'-demo-password', 'database_user': p,
                      'sql_connection_name': f'{project}:{region}:{p}-pg',
                      'image_repository': f'{region}-docker.pkg.dev/{project}/{p}/{p}',
                      'wif_pool': p+'-pool', 'wif_provider': p+'-provider'},
        'github_variables': {'GCP_PROJECT_ID': project, 'GCP_REGION': region,
                             'WIF_SERVICE_ACCOUNT': f'{p}-deployer@{project}.iam.gserviceaccount.com',
                             'WIF_PROVIDER': f'projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/{p}-pool/providers/{p}-provider'},
        'notice': 'แผนทดลองเท่านั้น ยังไม่มีทรัพยากรจริง PROJECT_NUMBER ต้องมาจากระบบจริง',
        'next_steps': ['ทำ Episode 5.0–5.2: เตรียม Dockerfile, CI และอ่านแผน infrastructure ที่ระบบจัดให้',
                       'เมื่อระบบจริงพร้อม: build image แล้ว push ไปยัง registry ของกลุ่ม',
                       'ตรวจ diff ของ deploy/deploy.sh และ release.sh เดิม: คง port/migration ของแอปและปรับส่วน shared project แล้วให้เพื่อน review' ,
                       'ทำ Episode 5.5–5.8 ตรวจแอปและหลักฐาน จากนั้นตั้ง GitHub environment demo: GCP_PROJECT_ID, GCP_REGION, WIF_PROVIDER, WIF_SERVICE_ACCOUNT ตาม Episode 6.4',
                       'ทำ merge gate, auto deploy, smoke test และ persistence ตามไกด์'],
    }

    plan['github_connected']=bool(repo)
    if not repo:
        plan['github_repository']=None
        for key in ('wif_pool','wif_provider'):plan['resources'].pop(key,None)
        plan['github_variables']={}
        plan['next_steps']=['ตรวจชื่อทรัพยากรของกลุ่ม แล้ว build และ deploy แอปของตัวเอง','GitHub และคู่มือ Lab 5 เป็นทางเลือก ไม่จำเป็นสำหรับการใช้ทรัพยากร']
    return plan


def work_once(app, delay=2):
    """Durable preview worker; leases fence concurrent workers and resume after restart."""
    now = int(time.time())
    with app.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('''SELECT a.*,t.name,t.prefix FROM activations a JOIN teams t ON t.id=a.team_id
                              WHERE a.mode='preview' AND a.status IN ('queued','running') AND a.lease_until<=?
                              ORDER BY a.created_at LIMIT 1''', (now,)).fetchone()
        if not row:
            return False
        token = secrets.randbelow(1_000_000_000) + 1
        conn.execute('UPDATE activations SET status=\'running\',lease_until=?,attempts=?,worker_seen_at=? WHERE team_id=?',
                     (now+60, token, now, row['team_id']))
    time.sleep(delay)
    step = row['step'] + 1
    outputs = build_plan(dict(row), row['repo'], app.config['PROJECT_ID'], app.config['REGION'])
    with app.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        changed = conn.execute('''UPDATE activations SET step=?,status=?,outputs=?,updated_at=?,worker_seen_at=?,lease_until=0
                                 WHERE team_id=? AND attempts=?''',
                               (step, 'ready' if step == len(STEPS) else 'running',
                                json.dumps(outputs, ensure_ascii=False), int(time.time()), int(time.time()), row['team_id'], token))
        if changed.rowcount:
            conn.execute('INSERT INTO events(team_id,action,at,detail) VALUES(?,?,?,?)',
                         (row['team_id'], 'preview_step', int(time.time()), 'จำลอง: '+STEPS[step-1][1]))
    return True


if __name__ == '__main__':
    import sys
    application = create_app()
    if '--worker' in sys.argv:
        if not application.config['PREVIEW']:
            raise SystemExit('Preview worker cannot run in production')
        while True:
            if not work_once(application):
                time.sleep(1)
    else:
        application.run(host='127.0.0.1', port=int(os.environ.get('PORT', '8876')), debug=False)
