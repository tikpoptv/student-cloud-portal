"""Backend-only verification with the actual portal runtime identity (read-only; needs token-creator rights on the portal SA).
Usage: python ops_verify_admin_telemetry.py --account you@gmail.com
"""
import argparse,json,subprocess,sys
from pathlib import Path
import requests
from live_provision import GoogleAPI
from admin_dashboard import collect_cloud,collect_costs
SA='cpe334-portal@cpe-se-course-2026.iam.gserviceaccount.com'
HEALTHY_COSTS=('available','awaiting_data','awaiting_export')  # export may legitimately still be empty


def main(argv=None):  # pragma: no cover - real cloud
    ap=argparse.ArgumentParser(description=__doc__.split('\n')[0]);ap.add_argument('--account',required=True)
    args=ap.parse_args(argv)
    token=subprocess.check_output(['gcloud','auth','print-access-token','--account='+args.account],text=True,timeout=30).strip()
    r=requests.post('https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/'+SA+':generateAccessToken',headers={'Authorization':'Bearer '+token,'x-goog-user-project':'cpe-se-course-2026'},json={'scope':['https://www.googleapis.com/auth/cloud-platform'],'lifetime':'600s'},timeout=30)
    r.raise_for_status()
    s=requests.Session();s.headers['Authorization']='Bearer '+r.json()['accessToken'];api=GoogleAPI(s)
    cloud=collect_cloud(api)
    print('Cloud source errors:',cloud['errors'])
    assert not cloud['errors'],'Runtime read permissions or API data access failed'
    config=json.loads(Path('private/hosted-admin-env.json').read_text());costs=collect_costs(config,api)
    print('Billing export status:',costs['status'])
    assert costs['status'] in HEALTHY_COSTS,'Billing export query failed: '+costs['status']
    p=Path('private/admin-telemetry-evidence.json');p.write_text(json.dumps({'cloud':cloud,'costs':costs},indent=2));p.chmod(0o600)
    print('Inventory counts:',{k:len(cloud[k]) for k in ('services','jobs','sql','registry')})
    return 0


if __name__=='__main__':
    sys.exit(main())
