> Feature note (19 November 2026). Test counts here are as of that release; removal/revoke of members is also described in LIVE-ACTIVATION.md and RUNBOOK.md.

# TA group and membership management

Use the existing portal with the TA Gmail. **Add team** creates a named roster group, assigns a server-generated prefix and approves its first Gmail. It creates no cloud resources. The student signs in, reviews the repository and activates normally; existing live-activation/quota limits still apply.

Open a team's drawer → **Members** → **Add member** to approve another Gmail for that same workspace. The primary email remains unchanged. The member's verified Google subject is pinned independently, and no TA access is granted. Exact approved emails are used for login. Gmail dot/plus aliases are checked for registration conflicts to prevent assigning the same Gmail identity to multiple groups. There is no silent transfer or deletion of existing users.

Members added before activation are included in provisioning. Members added during provisioning are synchronized after resources are ready. For already-active teams, an authenticated Cloud Tasks request runs a membership synchronization in the private provisioner. The public web service has no new IAM administrator permissions. The payload contains only group ID and the membership task kind, never a caller-supplied principal or role. All emails/assigned resource names come from server records. Ownership is checked across all affected resources before any IAM change.

Cloud permissions match the existing group owner: own Cloud Run service and migration job developer, own registry writer, own runtime actAs, own SQL Client condition, own admin/demo app secrets, and own logging view. No project-wide Owner/Editor, database password secret, database URL secret or unrelated group resources are granted. Project identity/service-usage metadata roles remain as for the original student. Add-only policy updates preserve etags and existing bindings. Leases serialize activation and membership operations. Permissions are marked ready only after successful synchronization. Queue or cloud failures preserve the roster and allow retries; the UI shows pending/error/waiting status and a retry action.

The primary roster remains in `teams`; additional Gmail records are in `team_members`. TA mutations are CSRF protected and audited in `admin_audit`. New table/schema additions preserve existing group IDs, repos, prefixes, jobs and costs. All UI text uses the existing EN/TH catalogue. No emails are sent and no GitHub repository is modified.

Verification: 61 backend tests passed, including real local PostgreSQL, member Google login/subject pinning, cross-team and alias rejection, new-group boundaries, queue failure/resume and fast-dispatch race handling. Cloud-policy tests check all ownership before writes and scoped SQL conditions, no admin grants and no password/URL secret access. Frontend 3 tests and production build passed; both Gmail form validators were checked. Browser UI and login with a real student's account are left to the user.

OAuth remains limited to openid/email/profile. Google documents the basic-identity exception to the external testing allowlist: https://developers.google.com/identity/protocols/oauth2/production-readiness/overview
