import hashlib
import json
import stat
import time
from unittest.mock import patch
import pytest
from app import create_app
from configure_oauth import configure
from check_roster import reviewed_rows, compare_roster, SHEET_ID, TAB

def google_app(tmp_path):
    a=create_app({'DATABASE':str(tmp_path/'test.sqlite3'),'SECRET_KEY':'test','TESTING':True,'PREVIEW':True,'AUTH_MODE':'google','BASE_URL':'http://127.0.0.1:8876','GOOGLE_CLIENT_ID':'test.apps.googleusercontent.com','GOOGLE_CLIENT_SECRET':'test'})
    with a.db() as conn:conn.execute("INSERT INTO teams VALUES('real','Team','real@gmail.com','real123',1,NULL,0)")
    return a

def callback(client,app,email='real@gmail.com',sub='google-sub'):
    state=str(time.time_ns())
    with app.db() as conn:conn.execute('INSERT INTO oauth_states VALUES(?,?)',(hashlib.sha256(state.encode()).hexdigest(),int(time.time())+60))
    with patch('authlib.integrations.flask_client.apps.FlaskOAuth2App.authorize_access_token',return_value={'userinfo':{'email':email,'sub':sub,'email_verified':True}}):
        return client.get('/auth/callback?state='+state)

def test_real_login_uses_approved_roster_and_never_demo(tmp_path):
    a=google_app(tmp_path);c=a.test_client();c.get('/')
    with c.session_transaction() as s:csrf=s['csrf']
    assert c.post('/preview/login',headers={'X-CSRF-Token':csrf}).status_code==404
    assert callback(c,a,email='unknown@gmail.com').status_code==403
    assert callback(c,a).status_code==302
    assert c.get('/api/status').json['team']['prefix']=='real123'
    assert callback(c,a,sub='different-sub').status_code==403
    with a.db() as conn:conn.execute("UPDATE teams SET enabled=0 WHERE id='real'")
    assert c.get('/api/status').status_code==401

def test_google_authorization_is_code_flow_with_pkce_and_state(tmp_path):
    a=google_app(tmp_path);c=a.test_client()
    with patch('authlib.integrations.flask_client.apps.FlaskOAuth2App.authorize_redirect') as redirect:
        redirect.return_value='redirect';assert c.get('/auth/google').status_code==200
        assert redirect.call_args.args[0]=='http://127.0.0.1:8876/auth/callback'
        assert redirect.call_args.kwargs['nonce'] and redirect.call_args.kwargs['state']
    with a.db() as conn:assert conn.execute('SELECT count(*) FROM oauth_states').fetchone()[0]==1
    assert a.extensions['authlib.integrations.flask_client'].create_client('google').client_kwargs['code_challenge_method']=='S256'

def test_private_client_config_validates_callback_and_preserves_session_key(tmp_path):
    source=tmp_path/'download.json';out=tmp_path/'private/runtime.json'
    source.write_text(json.dumps({'web':{'client_id':'test.apps.googleusercontent.com','client_secret':'keep-private','redirect_uris':['http://127.0.0.1:8876/auth/callback']}}))
    with pytest.raises(ValueError):configure(source,'https://different.test',out)
    configure(source,'http://127.0.0.1:8876',out);first=json.loads(out.read_text())
    assert stat.S_IMODE(out.stat().st_mode)==0o600
    assert first['AUTH_MODE']=='google' and first['PORTAL_MODE']=='preview'
    configure(source,'http://127.0.0.1:8876',out)
    assert json.loads(out.read_text())['SESSION_SECRET']==first['SESSION_SECRET']
    with pytest.raises(ValueError):configure(source,'http://public.example',out)

def test_roster_snapshot_cannot_silently_change_access(tmp_path):
    snapshot={'spreadsheet_id':SHEET_ID,'sheet_name':TAB,'values':[['ชื่อกลุ่ม / Group name','Name','ID','Google email'],['Team','Contact','1','real@gmail.com']]}
    a=google_app(tmp_path)
    assert compare_roster(a,snapshot)['pending_additions']==0
    snapshot['values'].append(['Other','Contact','2','other@gmail.com'])
    assert compare_roster(a,snapshot)['pending_additions']==1
    assert callback(a.test_client(),a,email='other@gmail.com').status_code==403
    snapshot['values'].append(['Duplicate','Contact','3','other@gmail.com'])
    with pytest.raises(ValueError):reviewed_rows(snapshot)

def test_alternate_cloud_run_origin_redirects_before_setting_oauth_state(tmp_path):
    a=google_app(tmp_path);a.config.update(BASE_URL='https://canonical.example.test',ENFORCE_CANONICAL_HOST=True)
    c=a.test_client()
    for path in ['/?lang=en','/auth/google']:
        r=c.get(path,base_url='https://alternate.example.test')
        assert r.status_code==302 and r.headers['Location']=='https://canonical.example.test'+path
    with a.db() as db:assert db.execute('SELECT count(*) FROM oauth_states').fetchone()[0]==0
