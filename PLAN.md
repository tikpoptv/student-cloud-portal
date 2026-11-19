> Current release: real activation is enabled through a private provisioner and persistent PostgreSQL. See [LIVE-ACTIVATION.md](LIVE-ACTIVATION.md) for current state and evidence; preview-only notes below describe earlier milestones.

# Student Cloud Portal — implementation and launch plan

> **HISTORICAL planning document (written 19 November 2026 before launch).** Statements below such as "/api/activate returns 503", "live provisioner unimplemented" or "no IAM changes have been made" described the pre-launch state and are **no longer true**: live activation is deployed. For current operation use [RUNBOOK.md](RUNBOOK.md) and [LIVE-ACTIVATION.md](LIVE-ACTIVATION.md).

## Build at the time of writing (19 November 2026, historical)

Local preview is functional: login with a demo team, repository validation, server-assigned prefix, one activation per team, durable SQLite queue, sequential worker, resume after process restart, progress, and downloadable handoff. Every step and output is labelled preview. No cloud mutation API is called.

Google OIDC authorization-code flow is implemented using Authlib (state, PKCE, nonce and verified ID token). The server checks verified Gmail/Workspace email against the imported roster and pins the Google subject on first successful login. Session cookies contain only session identifiers/CSRF/OIDC transient state, not access/refresh tokens. Preview is loopback-only and impossible through the demo endpoint in production mode. Real OAuth has not been tested with a Google Client yet.

Roster: read-only snapshot of the course's approved one-email-per-team tab. One Gmail is imported per row. Emails, roster and SQLite live under ignored private/, never static assets. Prefixes are deterministic from approved email, rather than student ID (the sheet contains duplicate IDs). Reimport never changes existing assignments. Reconcile any previously assigned/used prefix before live provisioning; do not move an existing team's resources automatically.

## Before cloud activation can be enabled

1. Obtain OAuth web Client ID and Secret; register exact HTTPS callback /auth/callback. Store credentials server-side. Add test users while OAuth app is in Testing, or publish an appropriate consent configuration before class use. No extra Drive/Gmail/Cloud scopes are requested.
2. Resolve existing project-wide student grants. Live read on 19 November found project bindings for run.developer, artifactregistry.writer, cloudsql.client, iam.serviceAccountUser and secretmanager.secretAccessor. Per-resource grants are additive and do not remove those broad grants. Prepare a reviewed migration per student/service account without interrupting current teams. **Done since:** the legacy grants were removed with a private IAM backup (script now archived in ops/archive/; never re-run it, it would also strip the conditional cloudsql.client grants).
3. Implement and integration-test the live provisioner against one explicitly allocated test prefix, including resumable provider operations. At the time of writing /api/activate rejected production requests (503). **Done since:** the guard was lifted after the provisioner and integration checks passed; production Activate is live.
4. Check quotas for approximately 36 independent Cloud SQL instances, SQL regional CPU, service accounts, Cloud Run and WIF pools. A web queue does not increase quotas or credits. Cap concurrent SQL creation, per-team count and course total. If the project cannot accommodate one instance per team, agree an alternative with the instructor before opening activation.
5. Choose persistent hosting. Current SQLite implementation supports one host with a durable local disk and local worker. Do not deploy it to Cloud Run's ephemeral filesystem, mount SQLite on a network share, or use multiple hosts. For Cloud Run production replace storage with transactional Firestore/PostgreSQL and dispatch via authenticated Cloud Tasks; retain unique group keys and leases.

## Live worker contract

Only the roster's team ID, assigned prefix and a frozen GitHub repository may identify a job. Never accept caller-supplied project, roles, shell command, secret, image or resource name. Resolve immutable GitHub owner/repository IDs before creating the WIF binding. Repo changes after activation require TA review.

Steps replacing Episode 5.3 infrastructure / 5.4 / 6.2–6.3:

- API enablement performed once by TA.
- Create team Artifact Registry repository, PostgreSQL Enterprise smallest supported tier (db-f1-micro if region/quota permits), fixed initial disk with auto-increase disabled, database and DB user; region/edition/tier chosen by TA, not student.
- Create separate runtime and deployer identities. Generate passwords on the server and deliver DB URL directly into Secret Manager; never emit passwords, tokens, URL credentials or secret payloads in status/logs/handoff. No service-account JSON keys.
- Create team's initial Cloud Run service and migration job, then assign run.developer only on those existing resources, run.invoker on migration job as needed, artifactregistry.writer on team's repository and iam.serviceAccountUser only on team's runtime identity. Scope student access similarly; use GitHub runner to build/push (not an unconstrained shared Cloud Build identity).
- Runtime gets secretAccessor only on its own secrets and Cloud SQL Client with an IAM Condition for its own instance, as documented by Google. Avoid granting students project Secret Accessor, SA User or Admin. Students' ability to deploy their own code intentionally implies access to their own runtime's data, never another team's.
- WIF condition binds immutable owner/repo IDs, main ref, exact deploy workflow and GitHub environment demo. Binding on deployer admits only that matching identity. Create a dedicated pool/provider or verify quota and safely partition a shared pool with exact repo mappings.
- Preflight every proposed name before creation. Existing resources must carry matching portal ownership metadata; conflicting or unowned resources stop the job for TA review. Keep durable operation IDs, leases and stage checkpoints. Retry resumes the same operations/secrets without password rotation, duplicates, or adopting unrelated resources.
- Adapt student deploy/release scripts to update existing resources without API/IAM/SQL-create steps. Creating initial service/job may need a neutral placeholder; do not run untrusted student source as the privileged provisioner. Runtime images and migration commands are built and deployed with the scoped student/deployer identity.

## Acceptance gates

- OAuth rejects wrong audience, nonce/state replay, unverified identity, unapproved/disabled email, and mismatching Google subject. Browser sign-in with two actual approved students must pass.
- Concurrent activation/retries create one resource set per approved team. Restart/failure resumes a Cloud SQL operation; it does not start another instance.
- Two-team test: A cannot deploy/read/mutate B's service/job, impersonate B's runtime/deployer, read B's secrets, push B's registry, or connect to B's SQL. Test runtime/deployer credentials as well as student credentials; check inherited grants too.
- Student deploy with approved scripts, migration, smoke test, WIF pipeline and handoff must pass for a real sample app. Only then label status resources-ready and enable class access.
- No claim of hard per-team budget caps. Credits are shared; verify billing/quotas and report costs separately. Cleanup remains TA-managed and only after grading approval.

## Sources

- Local Student Guide V1.1, Episode 5.2–5.7 and 6.2–6.4; Lab sheet governs assessment.
- Google OIDC: https://developers.google.com/identity/openid-connect/openid-connect
- Resource-scoped Cloud Run deployment: https://docs.cloud.google.com/run/docs/deploying
- Cloud SQL conditional instance access: https://docs.cloud.google.com/sql/docs/mysql/iam-conditions
- Durable authenticated task dispatch: https://docs.cloud.google.com/tasks/docs/creating-http-target-tasks

## Lab 5 source audit correction — 19 November

Read LAB5-INTEGRATION-REVIEW-TH.md before implementing live activation. The authoritative kit uses GitHub variables **GCP_PROJECT_ID / GCP_REGION**, mapped to shell PROJECT_ID / REGION. Preview handoff is corrected. Portal replaces infrastructure steps 1–8 of deploy.sh (plus 5.4 SQL setting), not all of Episode 5.3. Students still configure their own migration command/port/env and deploy using a shared-project script; CI stays mandatory. Bootstrap secrets depend on the actual stack. Existing release.sh only changes the image, so runtime/job configuration must be completed before the first release. Public service IAM and pause/teardown are TA/platform responsibilities in the shared-project adaptation.

## Superseding flow: adapt existing repository files

The separate course-app.json/course-deploy.py kit and download-first guide are retired. Current UI accepts a public repo, pins main SHA and proposes diffs on the existing Lab 5 Starter Kit paths. Unknown layouts return needs_review; no code is executed or pushed. Students review port/migration/env and apply a patch in their own branch, retaining teammate review, CI and staging→main lineage. Original CI is unchanged. First-deploy infrastructure blocks become preflight/update-only; manual build uses Docker rather than a shared Cloud Build identity. WIF/CD, migration-first fail-stop, digest deployment and protected main remain. Preview patch explicitly blocks live deploy/CD. (At the time of writing the live provisioner was unimplemented; it has since been implemented, see LIVE-ACTIVATION.md.)

Live adapter acceptance also requires original per-team admin/demo secrets, public service IAM, initial service/job skeleton, appropriate log view, authenticated student/deployer and current resource grants. A diff does not prove app functionality, cost readiness, CI success or independent review. Existing broad project IAM must still be migrated before production launch.
