> Resource-only activation now skips GitHub/repo review; see [RESOURCE-ONLY.md](RESOURCE-ONLY.md). Repository-first steps below describe the optional Lab 5 path.

> Current operations: [RUNBOOK.md](RUNBOOK.md). Verification figures below are launch-day evidence (19 November 2026); see `tests/` for the current suite.

# Live activation — 19 November 2026

Production: https://cpe334-student-cloud-4d7hbszvwq-as.a.run.app

Google OAuth identifies the approved Gmail for one of 36 teams imported from the reviewed course spreadsheet. This is a roster snapshot, not automatic trust of future sheet edits. The student first enters a public GitHub repository and reviews the proposed edits to existing Lab 5 files. Activate freezes the verified repository identity and creates only the server-assigned group's resources. Students apply the downloaded patch themselves; the portal does not push or run student source.

## What Activate creates

One per-team Artifact Registry repository; PostgreSQL 16 Enterprise db-f1-micro instance (10 GB, auto-resize disabled), database and user; runtime/deployer service accounts; database and application secrets (`<prefix>-database-password`, `-database-url`, `-admin-password`, `-demo-password`) plus five empty student secret slots `<prefix>-app-secret-1..5` that students fill themselves (members get secretAccessor and secretVersionAdder only, never version destroy/delete; the runtime and deployer SAs can read them; existing teams are backfilled with `ops_backfill_secret_slots.py`); Cloud Run service and migration job; GitHub Workload Identity pool/provider; and a restricted logging view. Names use the assigned team prefix. Cloud Run starts with a trusted placeholder, not a deployed student application.

The student's existing build → migration → deploy remains their responsibility. The patch adapts existing scripts/workflow and resource names to the provisioned resources, uses an amd64 image and caps Cloud Run at one instance. GitHub variables and resource identifiers are available on the resource page/JSON. No new configuration file format is required.

## Members and downloads

TA can add a team and add/remove members from the portal. Adding a member to an active team queues a membership task for the private worker, which grants that user the same scoped bindings as the team owner (own service/job, registry, runtime actAs, SQL client condition, admin/demo and slot secrets, log view, project identity roles). Removing a member marks them `removing` and **revokes** only that user from those bindings; teammates, service accounts and other teams are untouched (`Provisioner.revoke_members`). See [TEAM-MEMBERS.md](TEAM-MEMBERS.md).

Students download from the portal: the **Project Kit** (final project on Cloud Run, any language, no GitHub required; guided in the **Final Project Kit** tab) and the **Lab 5 starter kit**. Resource names/JSON come from the Team resources tab.

## Authorization and operation

The public portal service account can enqueue tasks, use its own database and session/OAuth secrets. It has no provisioning administrator roles. A private Cloud Run provisioner accepts authenticated Cloud Tasks OIDC requests from the dedicated dispatcher only. Its broad bootstrap permissions never go to students.

Jobs and checkpoints persist in PostgreSQL. A fenced lease prevents concurrent writers. Six stages resume across retries and provider long-running operations without recreating resources. Duplicate activation requests reuse the same group job. A permanent error is shown for TA review; retry resumes the owned resources. Existing names without the exact ownership marker are rejected.

Student and deployer access is attached to their own service, job, repository, runtime account, application secrets and log view. Cloud SQL Client uses an instance condition. Legacy project-wide student grants were removed after a private IAM backup. Project owners and service agents were preserved. WIF requires the frozen repository/owner numeric IDs, main branch, demo environment and the existing deploy workflow path.

SQL creation takes several minutes; at most two pending SQL creates are allowed. The portal limits live teams (`TEAM_ACTIVATION_LIMIT`; 36 in the launch build, planned default 39 as an env var) and total SQL instances to 40 including the portal database; underlying provider quotas still apply. Credits are shared; this is not a hard per-team spending cap. Each team database bills around the clock. Use `ops_pause_team.py` / `ops_resume_team.py` to stop and restart it and `ops_teardown_team.py` for end-of-course cleanup (all dry-run by default; see RUNBOOK.md). Region CPU/memory quotas may prevent all teams running simultaneously.

## Deployment

Public service: cpe334-student-cloud, PORTAL_MODE=live, LIVE_ACTIVATION_ENABLED=1, ENFORCE_CANONICAL_HOST=1, WORKER_URL=https://cpe334-provisioner-4d7hbszvwq-as.a.run.app.
Private service: cpe334-provisioner, LIVE_WORKER=1, concurrency=1, max instances=1, timeout=180s, GUNICORN_TIMEOUT=185. Queue cpe334-activation dispatches one task concurrently and retries pending stages. Both services use the persistent portal PostgreSQL database and Secret Manager references. No credentials are included in images or resource downloads.

Required APIs include cloudtasks, sts and cloudresourcemanager in addition to Run, SQL Admin, IAM, Secret Manager, Artifact Registry and Logging. Bootstrap operator: ops_bootstrap_live.py --account <you> (dry-run by default). Local operators and private evidence are excluded from build context.

## Verification and limits (launch-day evidence, historical)

Backend suite at launch: 41 passed, 1 optional PostgreSQL test skipped. Frontend translation tests and production build passed. Two owned disposable groups were actually provisioned; a synthetic app was built/pushed, migrated and deployed using one group's restricted deployer. Its database row persisted after a new revision. 32 actual access checks passed in both directions, including denied cross-group service mutation, runtime impersonation, SQL, registry, secrets and logs.

The production Cloud Tasks queue and private worker completed all six stages for a demo-only fixture using the web enqueue identity. The real roster rows were preserved; fixture resources and fixture DB records were removed afterwards. Evidence remains privately under private/.

No real student application was run. No GitHub Actions OIDC workflow was executed or GitHub repository changed. No browser/UI acceptance was performed for this release, per the user's instruction; student OAuth and visual acceptance are for the user to check.
