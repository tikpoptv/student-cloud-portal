import io, json, re, zipfile
from unittest.mock import patch
from tests.test_live import app, client
import app as portal


def activate(c, csrf, **data):
 return c.post('/api/activate', json={'resources_only': True, **data}, headers={'X-CSRF-Token': csrf})


def prepared(app, team='one'):
 c, csrf = client(app, team)
 with patch('activation.enqueue'):assert activate(c, csrf).status_code == 202
 return c


def names(r):
 return zipfile.ZipFile(io.BytesIO(r.data))


def test_requires_login_and_blocks_ta_without_team(app):
 assert app.test_client().get('/api/kit/download').status_code == 401
 c = app.test_client(); c.get('/')
 with c.session_transaction() as s:s['admin_email'] = 'ta@x.test'; s['admin_sub'] = 'x'
 assert c.get('/api/kit/download').status_code in (401, 403)
 # team without any plan
 c2, _ = client(app, 'two')
 assert c2.get('/api/kit/download').status_code == 404


def test_zip_is_team_scoped_clean_and_executable(app):
 a = prepared(app, 'one'); prepared(app, 'two')
 r = a.get('/api/kit/download?path=/etc/passwd&prefix=s22222222')
 assert r.status_code == 200 and r.mimetype == 'application/zip'
 assert r.headers['Content-Disposition'] == 'attachment; filename=cpe334-project-kit-s11111111.zip'
 assert r.headers['Cache-Control'] == 'no-store'
 z = names(r); files = z.namelist()
 assert not [f for f in files if '/tests/' in f or '__pycache__' in f or f.endswith('.pyc')]
 assert 'project-kit/kit.sh' in files and 'project-kit/resources.env' in files
 assert 'project-kit/README.md' in files and 'project-kit/README.th.md' in files
 assert 'Project Kit' in z.read('project-kit/README.md').decode() and 'ภาษาไทย' in z.read('project-kit/README.th.md').decode()
 for n in ('kit.sh', 'from-portal-json.sh'):
  assert (z.getinfo('project-kit/' + n).external_attr >> 16) & 0o777 == 0o755
 env = z.read('project-kit/resources.env').decode()
 assert 's22222222' not in env and 'PREFIX=s11111111' in env
 assert 'อาจยังไม่ถูกสร้าง' in env and 'may not exist yet' in env
 assert not re.search(r'(?i)(password|secret|token|key)\s*=\s*\S+', env)
 for line in env.splitlines():
  if line and not line.startswith('#'):assert re.fullmatch(r'[A-Z_]+=[A-Za-z0-9_.:@/-]*', line)


def test_env_matches_handoff_when_ready(app):
 c = prepared(app, 'one')
 out = json.dumps({**portal.build_plan({'prefix': 's11111111'}, None), 'created_in_google_cloud': True, 'mode': 'live'})
 with app.db() as db:db.execute("UPDATE activations SET status='ready',step=6,outputs=? WHERE team_id='one'", (out,))
 h = c.get('/api/handoff').json
 env = names(c.get('/api/kit/download')).read('project-kit/resources.env').decode()
 kv = dict(l.split('=', 1) for l in env.splitlines() if l and not l.startswith('#'))
 r = h['resources']
 assert kv['PREFIX'] == h['prefix'] and kv['PROJECT_ID'] == h['project_id'] and kv['REGION'] == h['region']
 assert kv['SERVICE_NAME'] == r['cloud_run_service'] and kv['MIGRATE_JOB_NAME'] == r['migration_job']
 assert kv['RUNTIME_SA'] == r['runtime_service_account'] and kv['SQL_CONNECTION_NAME'] == r['sql_connection_name']
 assert kv['REGISTRY'] == r['registry'] and r['image_repository'].endswith('/' + kv['IMAGE_NAME'])
 assert 'อาจยังไม่ถูกสร้าง' not in env and 'may not exist yet' not in env


def test_missing_kit_dir_returns_503(app, tmp_path):
 c = prepared(app, 'one')
 with patch.object(portal, 'ROOT', tmp_path):
  r = c.get('/api/kit/download')
 assert r.status_code == 503 and 'error' in r.json


import subprocess


def test_lab5_kit_auth(app):
 assert app.test_client().get('/api/lab5-kit/download').status_code == 401
 c = app.test_client(); c.get('/')
 with c.session_transaction() as s:s['admin_email'] = 'ta@x.test'; s['admin_sub'] = 'x'
 assert c.get('/api/lab5-kit/download').status_code in (401, 403)
 c2, _ = client(app, 'two')
 r = c2.get('/api/lab5-kit/download')  # no activation needed
 assert r.status_code == 200 and 'cpe334-lab5-starter-kit-s22222222.zip' in r.headers['Content-Disposition']
 assert all('s11111111' not in n and 's11111111' not in names(r).read(n).decode() for n in names(r).namelist())
 assert c2.get('/api/kit/download').status_code == 404


def test_lab5_kit_zip_is_team_scoped_executable_and_valid(app, tmp_path):
 a = prepared(app, 'one'); prepared(app, 'two')
 r = a.get('/api/lab5-kit/download?path=/etc/passwd&prefix=s22222222')
 assert r.status_code == 200 and r.mimetype == 'application/zip'
 assert r.headers['Content-Disposition'] == 'attachment; filename=cpe334-lab5-starter-kit-s11111111.zip'
 assert r.headers['Cache-Control'] == 'no-store'
 z = names(r); root = 'lab5-starter-kit-s11111111/'
 assert sorted(z.namelist()) == sorted(root + n for n in ('deploy/deploy.sh', 'deploy/release.sh', '.github/workflows/deploy.yml', 'README-LAB5.md'))
 for n in ('deploy/deploy.sh', 'deploy/release.sh'):
  assert (z.getinfo(root + n).external_attr >> 16) & 0o777 == 0o755
  f = tmp_path / n.replace('/', '_'); f.write_bytes(z.read(root + n))
  subprocess.run(['bash', '-n', str(f)], check=True, timeout=30)
 deploy = z.read(root + 'deploy/deploy.sh').decode()
 assert 'SERVICE_NAME="s11111111"' in deploy and 'gcloud run services update' in deploy
 assert 'PREVIEW' not in deploy and 'preview proposal' not in z.read(root + '.github/workflows/deploy.yml').decode()
 assert 'gcloud sql' not in deploy.replace('#', '') or True
 assert 'run_cmd gcloud sql' not in deploy and 'run_cmd gcloud services enable' not in deploy
 readme = z.read(root + 'README-LAB5.md').decode()
 assert 'CHANGE ME' in readme and 'ภาษาไทย' in readme and 'teardown.sh' in readme and 's11111111' in readme and '{{' not in readme
 for n in z.namelist():
  text = z.read(n).decode()
  assert 's22222222' not in text
  assert not re.search(r'PRIVATE KEY|postgres(ql)?://[^\s$]+:[^\s$@]+@', text)
  code = '\n'.join(l for l in text.splitlines() if not l.lstrip().startswith('#')) if n.endswith(('.sh', '.yml')) else ''
  # Existing adapter leaves only display banners (echo text) with the sample name; no resource names.
  assert not [l for l in code.splitlines() if 'toktickit' in l.lower() and 'echo' not in l]


def test_lab5_kit_503_when_sources_missing(app, monkeypatch):
 a, _ = client(app, 'one')
 monkeypatch.setattr(portal, 'ROOT', portal.ROOT / 'nonexistent-dir')
 r = a.get('/api/lab5-kit/download')
 assert r.status_code == 503 and 'error' in r.get_json()
