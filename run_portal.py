"""Local Google-login run; private runtime config is never served to the browser."""
import json
import os
from pathlib import Path

config=Path('private/runtime.json')
if not config.exists():raise SystemExit('Configure the OAuth Web client first: see OAUTH-SETUP.md')
for key,value in json.loads(config.read_text()).items():
    if key in {'AUTH_MODE','PORTAL_MODE','BASE_URL','GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET','SESSION_SECRET'}:
        os.environ[key]=value
from app import create_app
application=create_app()
if __name__=='__main__':application.run(host='127.0.0.1',port=int(os.environ.get('PORT','8876')),debug=False)
