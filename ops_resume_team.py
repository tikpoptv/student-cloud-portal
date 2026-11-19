"""Resume paused team resources: set the team's Cloud SQL activationPolicy back to ALWAYS.

DRY-RUN by default; nothing changes without --apply. Only resources passing the Provisioner ownership check are touched.
Usage: python ops_resume_team.py --group TEAM_ID [--group ...] | --all-ready  [--apply] [--account you@gmail.com]
All-ready needs the Cloud SQL proxy: cloud-sql-proxy cpe-se-course-2026:asia-southeast1:cpe334-portal-db --port 55440
"""
import argparse,sys
import ops_common as common


def main(argv=None,api=None,groups=None,out=print):
    ap=argparse.ArgumentParser(description=__doc__.split('\n')[0])
    common.add_common_args(ap)
    args=ap.parse_args(argv)
    teams=common.select_groups(args,groups,out)
    if teams is None:return 2
    if api is None:api=common.make_api(args.account)
    api=api if args.apply else common.ReadOnlyAPI(api)
    out(('APPLY' if args.apply else 'DRY-RUN (no changes; pass --apply to execute)')+f': set activationPolicy=ALWAYS for {len(teams)} team(s)')
    worst=0
    for team in teams:worst=max(worst,common.set_sql_policy(team,api,args.apply,out,'ALWAYS'))
    return worst


if __name__=='__main__':
    sys.exit(main())
