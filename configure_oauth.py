"""Install a downloaded Web OAuth client locally without printing its secret."""
import argparse
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit

def configure(client_file,base_url,output=Path('private/runtime.json')):
    base_url=base_url.rstrip('/')
    url=urlsplit(base_url)
    if (url.scheme!='https' and not (url.scheme=='http' and url.hostname in ('localhost','127.0.0.1','::1'))) or url.username or url.password or url.query or url.fragment or url.path:
        raise ValueError('BASE_URL must be an HTTPS origin, or a loopback HTTP origin')
    client=json.loads(Path(client_file).read_text()).get('web',{})
    callback=base_url+'/auth/callback'
    if not client.get('client_id','').endswith('.apps.googleusercontent.com') or not client.get('client_secret'):
        raise ValueError('Download a Google OAuth Web application client JSON')
    if callback not in client.get('redirect_uris',[]):
        raise ValueError('The client must authorize exactly this callback: '+callback)
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True);output.parent.chmod(0o700)
    prior=json.loads(output.read_text()) if output.exists() else {}
    config={'AUTH_MODE':'google','PORTAL_MODE':'preview','BASE_URL':base_url,
            'GOOGLE_CLIENT_ID':client['client_id'],'GOOGLE_CLIENT_SECRET':client['client_secret'],
            'SESSION_SECRET':prior.get('SESSION_SECRET') or secrets.token_hex(32)}
    # File permissions apply before writing credentials. Replace atomically.
    temp=output.with_suffix('.tmp')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(config,f,indent=2)
    temp.chmod(0o600);temp.replace(output)
    return callback

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--client-json',required=True);p.add_argument('--base-url',required=True)
    args=p.parse_args();callback=configure(args.client_json,args.base_url)
    print('OAuth configuration stored privately. Callback: '+callback)
    print('Start with .venv/bin/python run_portal.py. Cloud activation remains a preview.')
