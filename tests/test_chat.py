import base64
import json
import os
import time
from unittest.mock import patch

import pytest

import chat
from tests.test_admin import app, admin_client
from tests.test_oauth_setup import callback

EP_FCM = 'https://fcm.googleapis.com/fcm/send/abc123'
EP_APPLE = 'https://web.push.apple.com/QGxyz'
KEYS = {'p256dh': 'B' * 87, 'auth': 'a' * 22}


def auth(c):
    with c.session_transaction() as s:
        return {'X-CSRF-Token': s['csrf']}


def student(app, email='one@gmail.com'):
    c = app.test_client()
    assert callback(c, app, email).status_code == 302
    return c


def add_member(app, team_id, email):
    with app.db() as db:
        db.execute("INSERT INTO team_members(email,team_id,google_sub,added_at,added_by,cloud_status) VALUES(?,?,NULL,?,?,'ready')",
                   (email, team_id, int(time.time()), 'ta@gmail.com'))


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(chat, 'SEND_INTERVAL', 0)


def say(c, text, path='/api/chat'):
    return c.post(path, json={'body': text}, headers=auth(c))


def enable_push(app):
    app.config.update(VAPID_PRIVATE_KEY='p' * 43, VAPID_PUBLIC_KEY='K' * 87, VAPID_SUBJECT='mailto:ta@example.org')


def subscribe(c, endpoint=EP_FCM, keys=KEYS):
    return c.post('/api/push/subscribe', json={'subscription': {'endpoint': endpoint, 'keys': keys}}, headers=auth(c))


# ---------- chat ----------
def test_chat_needs_a_login_and_ta_routes_need_a_ta(app):
    c = app.test_client()
    c.get('/')
    assert c.get('/api/chat').status_code == 401
    assert c.post('/api/chat', json={'body': 'hi'}, headers=auth(c)).status_code == 401
    assert c.get('/api/chat/unread').status_code == 401
    s = student(app)
    assert s.get('/api/admin/chat/summary').status_code == 403
    assert s.get('/api/admin/chat/one').status_code == 403
    assert say(s, 'hi', '/api/admin/chat/one').status_code == 403


def test_team_thread_is_shared_and_isolated(app):
    add_member(app, 'one', 'mate@gmail.com')
    a, mate, other = student(app), student(app, 'mate@gmail.com'), student(app, 'two@gmail.com')
    assert say(a, 'hello from leader').status_code == 201
    assert say(mate, 'hello from mate').status_code == 201
    assert say(other, 'team two secret').status_code == 201
    seen = [m['body'] for m in a.get('/api/chat').json['messages']]
    assert seen == ['hello from leader', 'hello from mate']
    assert [m['body'] for m in mate.get('/api/chat').json['messages']] == seen
    assert [m['body'] for m in other.get('/api/chat').json['messages']] == ['team two secret']
    assert a.get('/api/chat?after=0').json['messages'][0]['sender'] == 'one@gmail.com'
    assert 'team two secret' not in a.get('/api/chat?after=0').text


def test_removed_member_loses_the_thread(app):
    add_member(app, 'one', 'mate@gmail.com')
    mate = student(app, 'mate@gmail.com')
    assert say(mate, 'hi').status_code == 201
    with app.db() as db:
        db.execute("UPDATE team_members SET cloud_status='removing' WHERE email='mate@gmail.com'")
    assert mate.get('/api/chat').status_code == 401


@pytest.mark.parametrize('payload', [{}, {'body': ''}, {'body': '   \n  '}, {'body': 5}, {'body': None}, [], 'text'])
def test_empty_or_malformed_messages_are_rejected(app, payload):
    s = student(app)
    assert s.post('/api/chat', json=payload, headers=auth(s)).status_code == 400
    assert s.get('/api/chat').json['messages'] == []


def test_message_length_limit_and_whitespace_trim(app):
    s = student(app)
    assert say(s, 'x' * 1001).status_code == 400
    assert say(s, 'ก' * 1000).status_code == 201
    r = say(s, '  สวัสดี\r\nครับ  ')
    assert r.status_code == 201 and r.json['message']['body'] == 'สวัสดี\nครับ'
    assert s.post('/api/chat', data='not json', headers={**auth(s), 'Content-Type': 'application/json'}).status_code == 400


def test_rate_limit_and_daily_cap(app, monkeypatch):
    s = student(app)
    monkeypatch.setattr(chat, 'SEND_INTERVAL', 60)
    assert say(s, 'first').status_code == 201
    assert say(s, 'second').status_code == 429
    monkeypatch.setattr(chat, 'SEND_INTERVAL', 0)
    monkeypatch.setattr(chat, 'STUDENT_DAILY_LIMIT', 3)
    assert say(s, 'two').status_code == 201 and say(s, 'three').status_code == 201
    assert say(s, 'four').status_code == 429
    ta = admin_client(app)
    assert say(ta, 'ta can still reply', '/api/admin/chat/one').status_code == 201


def test_html_is_stored_as_text_not_interpreted(app):
    s = student(app)
    body = '<img src=x onerror=alert(1)>'
    assert say(s, body).status_code == 201
    r = s.get('/api/chat')
    assert r.json['messages'][0]['body'] == body and r.mimetype == 'application/json'


def test_ta_reply_does_not_expose_the_ta_email(app):
    s, ta = student(app), admin_client(app)
    assert say(ta, 'ได้ครับ', '/api/admin/chat/one').status_code == 201
    msg = s.get('/api/chat').json['messages'][0]
    assert msg['role'] == 'ta' and msg['sender'] == 'TA' and 'ta@gmail.com' not in s.get('/api/chat').text
    assert say(ta, 'x', '/api/admin/chat/nope').status_code == 404
    assert ta.get('/api/admin/chat/nope').status_code == 404


def test_unread_counters_and_summary(app):
    s, ta = student(app), admin_client(app)
    say(s, 'q1')
    say(s, 'q2')
    assert ta.get('/api/admin/chat/summary').json['unread_total'] == 2
    row = ta.get('/api/admin/chat/summary').json['threads'][0]
    assert row['team_id'] == 'one' and row['unread'] == 2
    assert s.get('/api/chat/unread').json['unread'] == 0
    ta.get('/api/admin/chat/one')  # reading marks the thread read
    assert ta.get('/api/admin/chat/summary').json['unread_total'] == 0
    say(ta, 'answer', '/api/admin/chat/one')
    assert s.get('/api/chat/unread').json['unread'] == 1
    s.get('/api/chat')
    assert s.get('/api/chat/unread').json['unread'] == 0
    say(s, 'q3')
    assert ta.get('/api/admin/chat/summary').json['unread_total'] == 1


def test_after_cursor_returns_only_new_messages(app):
    s = student(app)
    ids = [say(s, f'm{i}').json['message']['id'] for i in range(3)]
    assert [m['body'] for m in s.get(f'/api/chat?after={ids[0]}').json['messages']] == ['m1', 'm2']
    assert s.get('/api/chat?after=abc').status_code == 200
    assert s.get('/api/chat?after=-5').status_code == 200


def test_only_the_latest_page_is_returned(app, monkeypatch):
    monkeypatch.setattr(chat, 'PAGE', 5)
    s = student(app)
    for i in range(8):
        say(s, f'm{i}')
    assert [m['body'] for m in s.get('/api/chat').json['messages']] == ['m3', 'm4', 'm5', 'm6', 'm7']


# ---------- push subscriptions ----------
def test_push_is_off_until_keys_are_configured(app):
    s = student(app)
    cfg = s.get('/api/push/config').json
    assert cfg == {'enabled': False, 'public_key': ''}
    assert subscribe(s).status_code == 503
    enable_push(app)
    assert s.get('/api/push/config').json == {'enabled': True, 'public_key': 'K' * 87}
    assert subscribe(s).status_code == 201


def test_push_config_needs_a_login(app):
    c = app.test_client()
    c.get('/')
    assert c.get('/api/push/config').status_code == 401


@pytest.mark.parametrize('endpoint', [
    'http://fcm.googleapis.com/x', 'https://localhost/x', 'https://127.0.0.1/x', 'https://evil.example/x',
    'https://fcm.googleapis.com.evil.example/x', 'https://evil.example/fcm.googleapis.com', 'https://fcm.googleapis.com:8443/x',
    'https://user:pw@fcm.googleapis.com/x', 'https://169.254.169.254/latest', 'https://notpush.apple.com.evil.test/x',
    'ftp://web.push.apple.com/x', '', None, 7, 'https://' + 'a' * 700 + '.push.apple.com/x',
])
def test_push_endpoint_must_be_a_real_push_service(app, endpoint):
    enable_push(app)
    s = student(app)
    assert subscribe(s, endpoint).status_code == 400
    with app.db() as db:
        assert db.execute('SELECT COUNT(*) n FROM push_subscriptions').fetchone()['n'] == 0


@pytest.mark.parametrize('endpoint', [EP_FCM, EP_APPLE, 'https://updates.push.services.mozilla.com/wpush/v2/x',
                                      'https://a.notify.windows.com/?token=x', 'https://web.push.apple.com:443/x'])
def test_real_push_services_are_accepted(app, endpoint):
    enable_push(app)
    assert subscribe(student(app), endpoint).status_code == 201


@pytest.mark.parametrize('keys', [{}, {'p256dh': KEYS['p256dh']}, {'auth': KEYS['auth']}, {'p256dh': 'short', 'auth': KEYS['auth']},
                                  {'p256dh': KEYS['p256dh'], 'auth': 'bad key!'}, {'p256dh': 5, 'auth': 6}, 'x', None])
def test_push_keys_are_validated(app, keys):
    enable_push(app)
    assert subscribe(student(app), EP_FCM, keys).status_code == 400


def test_malformed_subscription_bodies_are_rejected(app):
    enable_push(app)
    s = student(app)
    for payload in ({}, [], 'x', {'subscription': 'x'}, {'subscription': {'endpoint': EP_FCM}}):
        assert s.post('/api/push/subscribe', json=payload, headers=auth(s)).status_code == 400


def test_subscription_roles_and_account_cap(app):
    enable_push(app)
    s, ta = student(app), admin_client(app)
    assert subscribe(s).status_code == 201 and subscribe(ta, EP_APPLE).status_code == 201
    with app.db() as db:
        rows = {r['endpoint']: dict(r) for r in db.execute('SELECT endpoint,role,team_id,email FROM push_subscriptions').fetchall()}
    assert rows[EP_FCM]['role'] == 'student' and rows[EP_FCM]['team_id'] == 'one' and rows[EP_FCM]['email'] == 'one@gmail.com'
    assert rows[EP_APPLE]['role'] == 'ta' and rows[EP_APPLE]['team_id'] is None
    for i in range(8):
        assert subscribe(s, f'https://fcm.googleapis.com/fcm/send/dev{i}').status_code == 201
    with app.db() as db:
        n = db.execute("SELECT COUNT(*) n FROM push_subscriptions WHERE email='one@gmail.com'").fetchone()['n']
    assert n == chat.SUBSCRIPTIONS_PER_ACCOUNT


def test_resubscribing_an_endpoint_rebinds_it_and_unsubscribe_is_owner_only(app):
    enable_push(app)
    a, b = student(app), student(app, 'two@gmail.com')
    assert subscribe(a).status_code == 201
    b.post('/api/push/unsubscribe', json={'endpoint': EP_FCM}, headers=auth(b))
    with app.db() as db:
        assert db.execute('SELECT COUNT(*) n FROM push_subscriptions').fetchone()['n'] == 1  # b is not the owner
    assert subscribe(b).status_code == 201  # same device, new account: rebinds
    with app.db() as db:
        row = db.execute('SELECT team_id,email FROM push_subscriptions').fetchone()
    assert row['team_id'] == 'two' and row['email'] == 'two@gmail.com'
    b.post('/api/push/unsubscribe', json={'endpoint': EP_FCM}, headers=auth(b))
    with app.db() as db:
        assert db.execute('SELECT COUNT(*) n FROM push_subscriptions').fetchone()['n'] == 0


# ---------- push delivery ----------
def seed_subs(app):
    enable_push(app)
    ta, s1, s2 = admin_client(app), student(app), student(app, 'two@gmail.com')
    assert subscribe(ta, 'https://web.push.apple.com/ta1').status_code == 201
    assert subscribe(s1, 'https://fcm.googleapis.com/fcm/send/one').status_code == 201
    assert subscribe(s2, 'https://fcm.googleapis.com/fcm/send/two').status_code == 201
    return ta, s1, s2


def test_student_message_notifies_only_tas_and_never_leaks_the_text(app):
    ta, s1, s2 = seed_subs(app)
    with patch('chat.webpush') as push:
        assert say(s1, 'รหัสผ่านคือ hunter2').status_code == 201
    assert push.call_count == 1
    kw = push.call_args.kwargs
    assert kw['subscription_info']['endpoint'] == 'https://web.push.apple.com/ta1'
    assert 'hunter2' not in kw['data'] and 'รหัสผ่าน' not in kw['data'] and 'Team One' in json.loads(kw['data'])['body']
    assert kw['vapid_claims'] == {'sub': 'mailto:ta@example.org'}


def test_ta_reply_notifies_only_that_teams_students(app):
    ta, s1, s2 = seed_subs(app)
    with patch('chat.webpush') as push:
        assert say(ta, 'ตอบแล้ว secret-answer', '/api/admin/chat/one').status_code == 201
    assert [c.kwargs['subscription_info']['endpoint'] for c in push.call_args_list] == ['https://fcm.googleapis.com/fcm/send/one']
    assert 'secret-answer' not in push.call_args.kwargs['data']


def test_no_keys_means_no_push_attempt(app):
    s = student(app)
    with patch('chat.webpush') as push:
        assert say(s, 'hello').status_code == 201
    push.assert_not_called()


def test_a_failing_push_service_never_breaks_the_chat(app):
    ta, s1, s2 = seed_subs(app)
    with patch('chat.webpush', side_effect=RuntimeError('network down')):
        assert say(s1, 'still delivered').status_code == 201
    assert s1.get('/api/chat').json['messages'][0]['body'] == 'still delivered'
    with app.db() as db:
        assert db.execute('SELECT COUNT(*) n FROM push_subscriptions').fetchone()['n'] == 3  # transient errors keep the subscription


def test_gone_subscriptions_are_deleted(app):
    ta, s1, s2 = seed_subs(app)

    class Gone(Exception):
        response = type('R', (), {'status_code': 410})()

    with patch('chat.webpush', side_effect=Gone()):
        assert say(s1, 'hi').status_code == 201
    with app.db() as db:
        left = [r['endpoint'] for r in db.execute('SELECT endpoint FROM push_subscriptions').fetchall()]
    assert 'https://web.push.apple.com/ta1' not in left and len(left) == 2


def test_push_batch_and_time_budget_are_bounded(app, monkeypatch):
    enable_push(app)
    ta = admin_client(app)
    with app.db() as db:
        for i in range(40):
            db.execute("INSERT INTO push_subscriptions VALUES(?,?,?,?,?,?,?)", (f'https://fcm.googleapis.com/fcm/send/{i}', 'ta', None, f'ta{i}@gmail.com', 'B' * 87, 'a' * 22, 1))
    s = student(app)
    with patch('chat.webpush') as push:
        say(s, 'hello')
    assert push.call_count == chat.PUSH_BATCH
    clock = iter(range(0, 1000, 5))
    monkeypatch.setattr(chat.time, 'monotonic', lambda: next(clock))
    with patch('chat.webpush') as push:
        say(s, 'hello again')
    assert push.call_count <= 3


def test_real_web_push_encryption_round_trips():
    """Build a real subscription, let pywebpush encrypt for it, then decrypt with the receiver's private key."""
    import http_ece
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from pywebpush import webpush as real

    def b64(raw):
        return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()

    receiver = ec.generate_private_key(ec.SECP256R1())
    secret = os.urandom(16)
    pub = receiver.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    server = ec.generate_private_key(ec.SECP256R1())
    server_priv = b64(server.private_numbers().private_value.to_bytes(32, 'big'))
    server_pub = b64(server.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    seen = {}

    class Session:
        def post(self, url, data=None, headers=None, timeout=None, **kw):
            seen.update(url=url, data=data, headers=headers)
            return type('R', (), {'status_code': 201, 'ok': True, 'text': '', 'headers': {}})()

    payload = {'title': 'CPE334', 'body': 'มีข้อความใหม่', 'url': '/'}
    real(subscription_info={'endpoint': EP_FCM, 'keys': {'p256dh': b64(pub), 'auth': b64(secret)}}, data=json.dumps(payload, ensure_ascii=False),
         vapid_private_key=server_priv, vapid_claims={'sub': 'mailto:ta@example.org'}, ttl=3600, timeout=3, requests_session=Session())
    plain = http_ece.decrypt(seen['data'], private_key=receiver, auth_secret=secret, version='aes128gcm')
    assert json.loads(plain.decode()) == payload
    assert seen['headers']['Authorization'].startswith('vapid t=') and server_pub in seen['headers']['Authorization']
    assert seen['headers']['Content-Encoding'] == 'aes128gcm' and seen['headers']['TTL'] == '3600'


# ---------- installable web app ----------
def test_service_worker_manifest_and_icons_are_served(app):
    c = app.test_client()
    sw = c.get('/sw.js')
    assert sw.status_code == 200 and sw.mimetype in ('application/javascript', 'text/javascript')
    assert sw.headers['Service-Worker-Allowed'] == '/' and b'showNotification' in sw.data
    assert b'.text()' not in sw.data  # message text is never read by the worker
    m = c.get('/manifest.webmanifest')
    assert m.status_code == 200 and m.json['display'] == 'standalone' and m.json['start_url'] == '/'
    for icon in m.json['icons']:
        assert c.get(icon['src']).status_code == 200
    assert c.get('/static/icons/apple-touch-icon.png').status_code == 200
    page = c.get('/').text
    assert 'rel="manifest"' in page and 'apple-touch-icon' in page


def test_vapid_generator_writes_private_files_and_refuses_to_overwrite(tmp_path, monkeypatch, capsys):
    import ops_generate_vapid as gen
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gen, 'PRIVATE', gen.Path('private/vapid-private.txt'))
    monkeypatch.setattr(gen, 'PUBLIC', gen.Path('private/vapid-public.txt'))
    assert gen.main() == 0
    out = capsys.readouterr().out
    private = (tmp_path / 'private/vapid-private.txt').read_text()
    public = (tmp_path / 'private/vapid-public.txt').read_text()
    assert private not in out and public in out and len(public) == 87 and len(private) == 43
    assert oct((tmp_path / 'private/vapid-private.txt').stat().st_mode & 0o777) == '0o600'
    assert gen.main() == 1 and (tmp_path / 'private/vapid-private.txt').read_text() == private


def test_summary_is_sorted_unread_first_and_carries_a_short_preview(app):
    ta, s1, s2 = admin_client(app), student(app), student(app, 'two@gmail.com')
    say(s1, 'old question\nwith   spaces')
    time.sleep(1.1)
    say(s2, 'x' * 500)
    ta.get('/api/admin/chat/two')  # team two is read, team one is not
    rows = ta.get('/api/admin/chat/summary').json['threads']
    assert [r['team_id'] for r in rows] == ['one', 'two'] and rows[0]['unread'] == 1 and rows[1]['unread'] == 0
    assert rows[0]['last_body'] == 'old question with spaces' and rows[0]['last_role'] == 'student'
    assert len(rows[1]['last_body']) == 120
    time.sleep(1.1)
    say(ta, 'answer', '/api/admin/chat/one')
    rows = ta.get('/api/admin/chat/summary').json['threads']
    assert rows[0]['team_id'] == 'one' and rows[0]['last_role'] == 'ta' and rows[0]['last_body'] == 'answer'
    # replying does not mark the student's messages as read (the TA may not have seen the newest ones); only reading does
    assert rows[0]['unread'] == 1
    ta.get('/api/admin/chat/one')
    rows = ta.get('/api/admin/chat/summary').json['threads']
    assert [r['team_id'] for r in rows] == ['one', 'two'] and all(r['unread'] == 0 for r in rows)  # newest first when nothing is unread
