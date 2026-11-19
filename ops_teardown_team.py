"""Permanently delete one team's cloud resources (end of course / abandoned team). IRREVERSIBLE.

Deletes: Cloud Run service+job, Cloud SQL instance (data is lost; the name cannot be reused for about a week),
Artifact Registry repo, all team secrets (incl. app-secret-1..5), WIF provider+pool, log view, the team's project-level
IAM bindings, runner/deployer service accounts. Every resource must pass the Provisioner ownership check first; if
ANY existing resource is not owned by the team the whole team is REFUSED and nothing is deleted.
DRY-RUN by default. To delete: --apply AND --confirm-delete <team prefix> (typed, repeat per team). --all-ready is refused.
Usage: python ops_teardown_team.py --group TEAM_ID --confirm-delete PREFIX --apply [--account you@gmail.com]
Back up first if the team's data matters (gcloud sql backups create --instance=PREFIX-pg).
"""
import argparse,sys
import ops_common as common

def main(argv=None,api=None,groups=None,out=print):
    ap=argparse.ArgumentParser(description=__doc__.split('\n')[0])
    common.add_common_args(ap,allow_all_ready=False)
    ap.add_argument('--all-ready',action='store_true',help='NOT SUPPORTED for teardown (always refused)')
    ap.add_argument('--confirm-delete',action='append',default=[],metavar='PREFIX',help='type the team prefix to allow deleting it (repeatable)')
    ap.set_defaults(allow_all=False)
    args=ap.parse_args(argv)
    if args.all_ready:out('ERROR: teardown refuses --all-ready; name each team with --group');return 2
    teams=common.select_groups(args,groups,out)
    if teams is None:return 2
    if args.apply:
        unconfirmed=[t['prefix'] for t in teams if t['prefix'] not in args.confirm_delete]
        if unconfirmed:
            out('REFUSED: --apply needs --confirm-delete <prefix> for: '+', '.join(unconfirmed)+' (nothing was changed)');return 2
        extra=[c for c in args.confirm_delete if c not in {t['prefix'] for t in teams}]
        if extra:out('REFUSED: --confirm-delete prefix not among selected teams: '+', '.join(extra));return 2
    if api is None:api=common.make_api(args.account)
    api=api if args.apply else common.ReadOnlyAPI(api)
    out(('APPLY - DELETING' if args.apply else 'DRY-RUN (no changes; needs --apply and --confirm-delete PREFIX to delete)')+f': {len(teams)} team(s)')
    worst=0
    for team in teams:worst=max(worst,common.teardown_team(team,api,args.apply,out))
    return worst

if __name__=='__main__':
    sys.exit(main())
