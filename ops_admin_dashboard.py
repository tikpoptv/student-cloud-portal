"""Enable read-only telemetry for the authenticated TA dashboard (portal runtime SA read roles + billing dataset).

DRY-RUN by default: reads, prints the IAM/dataset changes, writes nothing. Pass --apply to change them.
The env file written with --apply sets TA_EMAILS to ALL --ta-email values (repeat the flag for every TA).
This only writes private/hosted-admin-env.json; to change TA_EMAILS on the live service see RUNBOOK.md.
Usage: python ops_admin_dashboard.py --account you@gmail.com --ta-email ta1@gmail.com --ta-email ta2@gmail.com [--apply]
"""
import argparse,json,subprocess,sys
from pathlib import Path
P='cpe-se-course-2026';SA=f'cpe334-portal@{P}.iam.gserviceaccount.com'
ROLES=['roles/run.viewer','roles/cloudsql.viewer','roles/artifactregistry.reader','roles/logging.viewer','roles/monitoring.viewer','roles/bigquery.jobUser',f'projects/{P}/roles/cpe334ProjectIdentity']


def main(argv=None,session=None,out=print):
    ap=argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--account',required=True)
    ap.add_argument('--ta-email',action='append',required=True,help='every TA address (repeatable); the full list replaces TA_EMAILS in the env file')
    ap.add_argument('--apply',action='store_true')
    args=ap.parse_args(argv)
    if session is None:  # pragma: no cover
        import requests
        session=requests.Session()
        session.headers['Authorization']='Bearer '+subprocess.check_output(['gcloud','auth','print-access-token','--account='+args.account],text=True,timeout=30).strip()
    def call(method,url,body=None,allow404=False):
        r=session.request(method,url,json=body,timeout=30)
        if allow404 and r.status_code==404:return None
        r.raise_for_status();return r.json()
    out('APPLY' if args.apply else 'DRY-RUN (no changes; pass --apply)')
    u=f'https://cloudresourcemanager.googleapis.com/v1/projects/{P}'
    policy=call('POST',u+':getIamPolicy',{'options':{'requestedPolicyVersion':3}})
    backup=Path('private/iam-before-ta-dashboard.json')
    if args.apply and not backup.exists():backup.write_text(json.dumps(policy));backup.chmod(0o600)
    for role in ROLES:
        binding=next((b for b in policy['bindings'] if b['role']==role and 'condition' not in b),None)
        if binding is None:binding={'role':role,'members':[]};policy['bindings'].append(binding)
        if 'serviceAccount:'+SA not in binding['members']:binding['members'].append('serviceAccount:'+SA);out('  would add '+role+' for portal SA')
    if args.apply:call('POST',u+':setIamPolicy',{'policy':policy});out('Read-only telemetry and bounded-query execution roles configured.')
    dataset=f'https://bigquery.googleapis.com/bigquery/v2/projects/{P}/datasets/cpe334_billing'
    data=call('GET',dataset,allow404=True)
    if data is None:
        out('  billing dataset cpe334_billing is missing')
        if not args.apply:data=None
        else:data=call('POST',f'https://bigquery.googleapis.com/bigquery/v2/projects/{P}/datasets',{'datasetReference':{'projectId':P,'datasetId':'cpe334_billing'},'location':'US','description':'Course billing detailed usage export; no student data','labels':{'managed-by':'cpe334-portal'}})
    if data is not None:
        assert data['location']=='US'
        access=data.get('access',[])
        if not any(a.get('userByEmail')==SA for a in access):
            out('  would grant portal SA READER on the billing dataset')
            if args.apply:access.append({'role':'READER','userByEmail':SA});call('PATCH',dataset,{'access':access,'etag':data['etag']})
    billing_id=call('GET','https://cloudbilling.googleapis.com/v1/projects/'+P+'/billingInfo')['billingAccountName'].split('/')[-1].replace('-','_')
    env=json.loads(Path('private/hosted-live-env.json').read_text())
    env.update(TA_EMAILS=','.join(args.ta_email),BILLING_EXPORT_TABLE=P+'.cpe334_billing.gcp_billing_export_resource_v1_'+billing_id,BILLING_EXPORT_LOCATION='US')
    out('  env file would contain TA_EMAILS='+env['TA_EMAILS']+' BILLING_EXPORT_TABLE='+env['BILLING_EXPORT_TABLE'])
    if args.apply:
        p=Path('private/hosted-admin-env.json');p.write_text(json.dumps(env));p.chmod(0o600);out('Wrote '+str(p))
    return 0


if __name__=='__main__':
    sys.exit(main())
