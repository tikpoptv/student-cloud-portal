"""Pause team resources: set the team's Cloud SQL activationPolicy to NEVER (stops the 24h/day db-f1-micro charge).

DRY-RUN by default; nothing changes without --apply. Only resources passing the Provisioner ownership check are touched.
Optional --scale-run-to-zero also drops a Cloud Run minInstanceCount to 0 (not restored by resume).
Usage: python ops_pause_team.py --group TEAM_ID [--group ...] | --all-ready  [--apply] [--account you@gmail.com]
All-ready needs the Cloud SQL proxy: cloud-sql-proxy cpe-se-course-2026:asia-southeast1:cpe334-portal-db --port 55440
"""
import argparse,sys
import ops_common as common


def main(argv=None,api=None,groups=None,out=print,policy='NEVER'):
    ap=argparse.ArgumentParser(description=__doc__.split('\n')[0])
    common.add_common_args(ap)
    ap.add_argument('--scale-run-to-zero',action='store_true',help='also set Cloud Run minInstanceCount to 0')
    args=ap.parse_args(argv)
    teams=common.select_groups(args,groups,out)
    if teams is None:return 2
    if api is None:api=common.make_api(args.account)
    api=api if args.apply else common.ReadOnlyAPI(api)
    out(('APPLY' if args.apply else 'DRY-RUN (no changes; pass --apply to execute)')+f': set activationPolicy={policy} for {len(teams)} team(s)')
    worst=0
    for team in teams:worst=max(worst,common.set_sql_policy(team,api,args.apply,out,policy,args.scale_run_to_zero))
    return worst


if __name__=='__main__':
    sys.exit(main())
