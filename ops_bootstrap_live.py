"""TA-only bootstrap of the isolated provisioner and authenticated task queue (idempotent).

DRY-RUN by default: prints the gcloud commands it would run. Pass --apply to run them.
Usage: python ops_bootstrap_live.py --account you@gmail.com [--apply]
"""
import argparse,subprocess,sys
PROJECT='cpe-se-course-2026'
WORKER='serviceAccount:cpe334-provisioner@'+PROJECT+'.iam.gserviceaccount.com'
ROLES=('roles/run.admin','roles/cloudsql.admin','roles/secretmanager.admin','roles/artifactregistry.admin','roles/iam.serviceAccountAdmin','roles/resourcemanager.projectIamAdmin','roles/iam.workloadIdentityPoolAdmin','roles/logging.admin')


def main(argv=None,runner=None,out=print):
    ap=argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--account',required=True,help='gcloud account of the project owner')
    ap.add_argument('--apply',action='store_true')
    args=ap.parse_args(argv)
    def sh(*a,check=True):
        cmd=['gcloud',*a,'--project='+PROJECT,'--account='+args.account,'--quiet']
        if not args.apply:out('would run: '+' '.join(cmd));return 0
        r=(runner or subprocess.run)(cmd,capture_output=True,text=True,timeout=180)
        if r.returncode and check:raise SystemExit(r.stderr)
        return r.returncode
    out('APPLY' if args.apply else 'DRY-RUN (pass --apply to execute)')
    sh('services','enable','cloudtasks.googleapis.com','sts.googleapis.com','cloudresourcemanager.googleapis.com')
    for name in ('cpe334-provisioner','cpe334-tasks'):
        email=name+'@'+PROJECT+'.iam.gserviceaccount.com'
        if sh('iam','service-accounts','describe',email,check=False) or not args.apply:sh('iam','service-accounts','create',name,'--display-name='+name)
    for role in ROLES:sh('projects','add-iam-policy-binding',PROJECT,'--member='+WORKER,'--role='+role,'--format=value(etag)')
    for secret in ('cpe334-portal-session','cpe334-portal-database'):
        sh('secrets','add-iam-policy-binding',secret,'--member='+WORKER,'--role=roles/secretmanager.secretAccessor','--format=value(etag)')
    exists=sh('tasks','queues','describe','cpe334-activation','--location=asia-southeast1',check=False)==0 and args.apply
    sh('tasks','queues','update' if exists else 'create','cpe334-activation','--location=asia-southeast1','--max-concurrent-dispatches=1','--max-dispatches-per-second=1','--max-attempts=1000','--min-backoff=15s','--max-backoff=60s','--max-doublings=2','--max-retry-duration=86400s')
    portal='serviceAccount:cpe334-portal@'+PROJECT+'.iam.gserviceaccount.com'
    sh('tasks','queues','add-iam-policy-binding','cpe334-activation','--location=asia-southeast1','--member='+portal,'--role=roles/cloudtasks.enqueuer','--format=value(etag)')
    sh('iam','service-accounts','add-iam-policy-binding','cpe334-tasks@'+PROJECT+'.iam.gserviceaccount.com','--member='+portal,'--role=roles/iam.serviceAccountUser','--format=value(etag)')
    out('Private provisioner identities and durable queue '+('configured.' if args.apply else 'plan printed.'))
    return 0


if __name__=='__main__':
    sys.exit(main())
