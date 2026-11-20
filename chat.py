"""Team <-> TA chat with best-effort Web Push notifications.

One shared thread per team: every member of the team sees it, and any TA can answer. Push is optional: without VAPID
keys the chat still works (the page polls). Notification payloads never contain message text.
"""
import json
import logging
import os
import re
import time
from functools import wraps
from urllib.parse import urlsplit

from flask import abort, jsonify, request, send_from_directory

MAX_BODY = 1000
PAGE = 100
SEND_INTERVAL = 2
STUDENT_DAILY_LIMIT = 200
SUBSCRIPTIONS_PER_ACCOUNT = 5
PUSH_BATCH = 25
PUSH_BUDGET_SECONDS = 8
KEY_RE = re.compile(r'[A-Za-z0-9_-]{16,100}')
# The server posts to the endpoint the browser gives us, so only genuine push services are accepted (no SSRF).
PUSH_HOSTS = ('fcm.googleapis.com', 'android.googleapis.com', 'updates.push.services.mozilla.com', 'web.push.apple.com')
PUSH_SUFFIXES = ('.push.apple.com', '.notify.windows.com', '.push.services.mozilla.com')
EMPTY_NOTE = 'กรุณาพิมพ์ข้อความ'
TOO_LONG = 'ข้อความยาวเกินไป (ไม่เกิน 1,000 ตัวอักษร)'
TOO_FAST = 'ส่งข้อความเร็วเกินไป กรุณารอสักครู่'
DAILY_LIMIT = 'ส่งข้อความครบจำนวนที่กำหนดต่อวันแล้ว กรุณาติดต่อ TA ช่องทางอื่น'
BAD_SUBSCRIPTION = 'ข้อมูลการแจ้งเตือนไม่ถูกต้อง'

log = logging.getLogger(__name__)


def allowed_endpoint(endpoint):
    if not isinstance(endpoint, str) or len(endpoint) > 600:
        return False
    parts = urlsplit(endpoint)
    host = (parts.hostname or '').lower()
    if parts.scheme != 'https' or parts.username or parts.password or parts.port not in (None, 443) or not host:
        return False
    return host in PUSH_HOSTS or any(host.endswith(s) for s in PUSH_SUFFIXES)


def webpush(**kwargs):
    from pywebpush import webpush as send
    return send(**kwargs)


def message_body(data):
    value = data.get('body') if isinstance(data, dict) else None
    if not isinstance(value, str):
        abort(400, EMPTY_NOTE)
    value = value.replace('\r\n', '\n').strip()
    if not value:
        abort(400, EMPTY_NOTE)
    if len(value) > MAX_BODY:
        abort(400, TOO_LONG)
    return value


def register_chat(app):
    with app.db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS chat_messages(
          id INTEGER PRIMARY KEY AUTOINCREMENT,team_id TEXT NOT NULL REFERENCES teams(id),role TEXT NOT NULL,
          sender TEXT NOT NULL,body TEXT NOT NULL,created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS chat_messages_team ON chat_messages(team_id,id);
        CREATE TABLE IF NOT EXISTS chat_reads(
          team_id TEXT NOT NULL,reader TEXT NOT NULL,last_id INTEGER NOT NULL,PRIMARY KEY(team_id,reader)
        );
        CREATE TABLE IF NOT EXISTS push_subscriptions(
          endpoint TEXT PRIMARY KEY,role TEXT NOT NULL,team_id TEXT,email TEXT NOT NULL,
          p256dh TEXT NOT NULL,auth TEXT NOT NULL,created_at INTEGER NOT NULL
        );''')

    def push_ready():
        return bool(app.config.get('VAPID_PRIVATE_KEY') and app.config.get('VAPID_PUBLIC_KEY') and app.config.get('VAPID_SUBJECT'))

    def student():
        team = app.current_team()
        if not team:
            abort(401)
        return team

    def staff(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not app.current_admin():
                abort(403)
            return fn(*args, **kwargs)
        return wrapped

    def after_id():
        try:
            return max(0, int(request.args.get('after', '0')))
        except ValueError:
            return 0

    def messages(team_id, after):
        with app.db() as c:
            if after:
                rows = c.execute('SELECT id,role,sender,body,created_at FROM chat_messages WHERE team_id=? AND id>? ORDER BY id LIMIT ?',
                                 (team_id, after, PAGE)).fetchall()
            else:
                rows = list(reversed(c.execute('SELECT id,role,sender,body,created_at FROM chat_messages WHERE team_id=? ORDER BY id DESC LIMIT ?',
                                               (team_id, PAGE)).fetchall()))
        return [{'id': r['id'], 'role': r['role'], 'sender': r['sender'] if r['role'] == 'student' else 'TA',
                 'body': r['body'], 'created_at': r['created_at']} for r in rows]

    def mark_read(team_id, reader):
        with app.db() as c:
            last = c.execute('SELECT MAX(id) AS m FROM chat_messages WHERE team_id=?', (team_id,)).fetchone()['m']
            if last:
                c.execute('INSERT INTO chat_reads(team_id,reader,last_id) VALUES(?,?,?) ON CONFLICT(team_id,reader) DO UPDATE SET last_id=excluded.last_id',
                          (team_id, reader, last))

    def add_message(team_id, role, sender, body):
        now = int(time.time())
        with app.db() as c:
            row = c.execute('INSERT INTO chat_messages(team_id,role,sender,body,created_at) VALUES(?,?,?,?,?) RETURNING id',
                            (team_id, role, sender, body, now)).fetchone()
        return {'id': row['id'], 'role': role, 'sender': sender if role == 'student' else 'TA', 'body': body, 'created_at': now}

    def notify(role, team_id, payload):
        """Best effort and bounded: a failing push service must never fail or slow the chat itself."""
        if not push_ready():
            return 0
        with app.db() as c:
            if role == 'ta':
                rows = c.execute("SELECT endpoint,p256dh,auth FROM push_subscriptions WHERE role='ta' LIMIT ?", (PUSH_BATCH,)).fetchall()
            else:
                rows = c.execute("SELECT endpoint,p256dh,auth FROM push_subscriptions WHERE role='student' AND team_id=? LIMIT ?", (team_id, PUSH_BATCH)).fetchall()
        started = time.monotonic()
        sent = 0
        for r in rows:
            if time.monotonic() - started > PUSH_BUDGET_SECONDS:
                break
            try:
                webpush(subscription_info={'endpoint': r['endpoint'], 'keys': {'p256dh': r['p256dh'], 'auth': r['auth']}},
                        data=json.dumps(payload, ensure_ascii=False), vapid_private_key=app.config['VAPID_PRIVATE_KEY'],
                        vapid_claims={'sub': app.config['VAPID_SUBJECT']}, ttl=3600, timeout=3)
                sent += 1
            except Exception as err:
                status = getattr(getattr(err, 'response', None), 'status_code', None)
                if status in (404, 410):
                    with app.db() as c:
                        c.execute('DELETE FROM push_subscriptions WHERE endpoint=?', (r['endpoint'],))
                else:
                    log.warning('web push failed (%s)', status or type(err).__name__)
        return sent

    # ---- students ----
    @app.get('/api/chat')
    def chat_read():
        team = student()
        rows = messages(team['id'], after_id())
        mark_read(team['id'], 'student')
        return jsonify(messages=rows)

    @app.post('/api/chat')
    def chat_send():
        team = student()
        body = message_body(request.get_json(silent=True))
        if app.throttle('chat:' + team['id'], SEND_INTERVAL, wait_message=TOO_FAST):
            abort(429, TOO_FAST)
        with app.db() as c:
            used = c.execute("SELECT COUNT(*) AS n FROM chat_messages WHERE team_id=? AND role='student' AND created_at>?",
                             (team['id'], int(time.time()) - 86400)).fetchone()['n']
        if used >= STUDENT_DAILY_LIMIT:
            abort(429, DAILY_LIMIT)
        message = add_message(team['id'], 'student', team['login_email'], body)
        notify('ta', team['id'], {'title': 'CPE334', 'body': 'มีข้อความใหม่จากกลุ่ม ' + team['name'], 'url': '/'})
        return jsonify(message=message), 201

    @app.get('/api/chat/unread')
    def chat_unread():
        team = student()
        with app.db() as c:
            n = c.execute("""SELECT COUNT(*) AS n FROM chat_messages m
                             WHERE m.team_id=? AND m.role='ta' AND m.id>COALESCE((SELECT last_id FROM chat_reads WHERE team_id=m.team_id AND reader='student'),0)""",
                          (team['id'],)).fetchone()['n']
        return jsonify(unread=n)

    # ---- TAs ----
    @app.get('/api/admin/chat/summary')
    @staff
    def chat_summary():
        with app.db() as c:
            last = c.execute('SELECT team_id,role,body,created_at FROM chat_messages WHERE id IN (SELECT MAX(id) FROM chat_messages GROUP BY team_id)').fetchall()
            unread = c.execute("""SELECT m.team_id,COUNT(*) AS n FROM chat_messages m
                                  WHERE m.role='student' AND m.id>COALESCE((SELECT last_id FROM chat_reads WHERE team_id=m.team_id AND reader='ta'),0)
                                  GROUP BY m.team_id""").fetchall()
        counts = {r['team_id']: r['n'] for r in unread}
        threads = [{'team_id': r['team_id'], 'last_at': r['created_at'], 'last_role': r['role'], 'last_body': ' '.join(r['body'].split())[:120],
                    'unread': counts.get(r['team_id'], 0)} for r in last]
        # Unread first, then newest: the inbox shows the list in this order.
        threads.sort(key=lambda x: (x['unread'] == 0, -x['last_at'], x['team_id']))
        return jsonify(threads=threads, unread_total=sum(counts.values()))

    def known_team(team_id):
        with app.db() as c:
            if not c.execute('SELECT id FROM teams WHERE id=?', (team_id,)).fetchone():
                abort(404)

    @app.get('/api/admin/chat/<team_id>')
    @staff
    def admin_chat_read(team_id):
        known_team(team_id)
        rows = messages(team_id, after_id())
        mark_read(team_id, 'ta')
        return jsonify(messages=rows)

    @app.post('/api/admin/chat/<team_id>')
    @staff
    def admin_chat_send(team_id):
        known_team(team_id)
        body = message_body(request.get_json(silent=True))
        message = add_message(team_id, 'ta', app.current_admin(), body)
        notify('student', team_id, {'title': 'CPE334', 'body': 'TA ตอบข้อความของกลุ่มคุณแล้ว', 'url': '/'})
        return jsonify(message=message), 201

    # ---- push subscriptions ----
    def identity():
        admin = app.current_admin()
        if admin:
            return 'ta', None, admin
        team = app.current_team()
        if not team:
            abort(401)
        return 'student', team['id'], team['login_email']

    @app.get('/api/push/config')
    def push_config():
        identity()
        return jsonify(enabled=push_ready(), public_key=app.config.get('VAPID_PUBLIC_KEY', '') if push_ready() else '')

    @app.post('/api/push/subscribe')
    def push_subscribe():
        role, team_id, email = identity()
        if not push_ready():
            abort(503, 'ยังไม่ได้เปิดใช้การแจ้งเตือนบนเซิร์ฟเวอร์')
        data = request.get_json(silent=True)
        sub = data.get('subscription') if isinstance(data, dict) else None
        keys = sub.get('keys') if isinstance(sub, dict) else None
        if not isinstance(keys, dict):
            abort(400, BAD_SUBSCRIPTION)
        endpoint, p256dh, auth = sub.get('endpoint'), keys.get('p256dh'), keys.get('auth')
        if not allowed_endpoint(endpoint) or not (isinstance(p256dh, str) and KEY_RE.fullmatch(p256dh)) or not (isinstance(auth, str) and KEY_RE.fullmatch(auth)):
            abort(400, BAD_SUBSCRIPTION)
        with app.db() as c:
            mine = c.execute('SELECT endpoint FROM push_subscriptions WHERE email=? AND endpoint<>?', (email, endpoint)).fetchall()
            for old in mine[SUBSCRIPTIONS_PER_ACCOUNT - 1:]:
                c.execute('DELETE FROM push_subscriptions WHERE endpoint=?', (old['endpoint'],))
            c.execute('''INSERT INTO push_subscriptions(endpoint,role,team_id,email,p256dh,auth,created_at) VALUES(?,?,?,?,?,?,?)
                         ON CONFLICT(endpoint) DO UPDATE SET role=excluded.role,team_id=excluded.team_id,email=excluded.email,p256dh=excluded.p256dh,auth=excluded.auth''',
                      (endpoint, role, team_id, email, p256dh, auth, int(time.time())))
        return jsonify(subscribed=True), 201

    @app.post('/api/push/unsubscribe')
    def push_unsubscribe():
        _, _, email = identity()
        data = request.get_json(silent=True)
        endpoint = data.get('endpoint') if isinstance(data, dict) else None
        if isinstance(endpoint, str):
            with app.db() as c:
                c.execute('DELETE FROM push_subscriptions WHERE endpoint=? AND email=?', (endpoint, email))
        return jsonify(subscribed=False)

    # ---- installable web app (needed for push on iPhone) ----
    @app.get('/sw.js')
    def service_worker():
        response = send_from_directory(app.static_folder, 'sw.js', mimetype='application/javascript')
        response.headers['Service-Worker-Allowed'] = '/'
        return response

    @app.get('/manifest.webmanifest')
    def manifest():
        # Read into memory (not streamed): the +json type is post-processed by the JSON response hook, which needs a readable body.
        with open(os.path.join(app.static_folder, 'manifest.webmanifest'), 'rb') as handle:
            return app.response_class(handle.read(), mimetype='application/manifest+json')
