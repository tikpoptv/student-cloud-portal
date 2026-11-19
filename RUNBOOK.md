# RUNBOOK - CPE334 Student Cloud Portal operations

> **สรุปภาษาไทย (อ่านก่อน)**
> - ระบบ: เว็บ `cpe334-student-cloud` + worker ส่วนตัว `cpe334-provisioner` (image เดียวกัน) + คิว Cloud Tasks `cpe334-activation` + Cloud SQL `cpe334-portal-db` เก็บสถานะ ทุกทีมมีทรัพยากรของตัวเอง (Cloud SQL db-f1-micro 1 ตัว/ทีม คิดเงินตลอด 24 ชม.)
> - เครดิตทั้งโครงการใช้ร่วมกัน (~THB 9.7k หมด 24 ม.ค. 2027) ความเสี่ยงหลักคือค่าใช้จ่าย: ตั้ง Budget alert (คำสั่งอยู่ในหัวข้อ Cost control, **ยังไม่ได้รันจริง**)
> - หยุดจ่ายชั่วคราว: `ops_pause_team.py` / เปิดคืน: `ops_resume_team.py` / ลบถาวร: `ops_teardown_team.py` ทุกตัวเป็น dry-run โดยปริยาย ต้องใส่ `--apply` เอง ส่วน teardown ต้องพิมพ์ `--confirm-delete <prefix>` ด้วย และลบเฉพาะของที่ผ่านการตรวจความเป็นเจ้าของ
> - ก่อน deploy: คิวต้องว่าง, backup DB, deploy worker ก่อนเว็บ, ตรวจ checklist ท้ายเอกสาร
> - สคริปต์เปิดระบบครั้งเดียวในอดีตถูกถอดออกจากที่เก็บนี้แล้ว (ห้ามนำกลับมารันซ้ำ)
> - คำสั่งทั้งหมดในเอกสารนี้ยังไม่เคยทดสอบกับ Google จริงในรอบเขียนเอกสาร ให้ลอง dry-run ก่อนเสมอ

Conventions: `PROJECT=cpe-se-course-2026`, `REGION=asia-southeast1`. Commands assume
`gcloud config set project cpe-se-course-2026` and an account with owner rights. Items marked **NOT YET EXECUTED**
or **UNVERIFIED** have never been run against the real project.

## 1. Architecture (10 lines)

1. One image (this repo) runs two Cloud Run services: web `cpe334-student-cloud` (public, `PORTAL_MODE=live`) and worker `cpe334-provisioner` (private, `LIVE_WORKER=1`, concurrency 1, max instances 1, timeout 180s).
2. Students log in with Google OIDC; only roster Gmails (and TA-added members) are allowed. TAs come from the `TA_EMAILS` env var on the web service.
3. "Activate" enqueues a task on Cloud Tasks queue `cpe334-activation` (1 concurrent dispatch, OIDC to the worker, SA `cpe334-tasks`).
4. The worker runs the six-stage `Provisioner` (`live_provision.py`) with SA `cpe334-provisioner`; state and leases live in PostgreSQL.
5. Portal state: Cloud SQL `cpe334-portal-db` (db `portal`). Web and worker both use it via Secret Manager references.
6. Per team (prefix `P`): Cloud Run service `P` + job `P-migrate`, Cloud SQL `P-pg` (db-f1-micro, 10 GB), Artifact Registry repo `P`, secrets `P-database-password|database-url|admin-password|demo-password|app-secret-1..5`, SAs `P-runner`/`P-deployer`, WIF pool `P-pool` + provider (only with GitHub), log view `P`.
7. Ownership: every resource carries label `cpe334-team=<team_id>` or a description marker `CPE334 portal group:<id>;prefix:<P>;v1`; code refuses anything else (`Provisioner.owned`).
8. Costs: BigQuery detailed billing export `cpe-se-course-2026.cpe334_billing.gcp_billing_export_resource_v1_01EB56_DF44A5_45A3EB` (US), read by the TA dashboard (delayed by hours).
9. Billing account `<BILLING_ACCOUNT_ID>` (TA personal); credits are shared, not per team.
10. Limits: `TEAM_ACTIVATION_LIMIT` (default 39) and Cloud SQL 40 instances per project **including** `cpe334-portal-db`; max 2 SQL creates pending at once.

## 2. Deploy

Build context is an **allowlist**: both `.gcloudignore` and `.dockerignore` start with `**` and list wanted files with `!`.
If you add a new top-level file or directory that the app needs, add it to BOTH files (and the `Dockerfile` `COPY`), or the image silently lacks it. `ops_*.py`, `private/`, `tests/` must stay out.

```sh
# 0. Queue must be empty (no activation in flight)
gcloud tasks list --queue=cpe334-activation --location=asia-southeast1
# 1. Back up the portal DB
gcloud sql backups create --instance=cpe334-portal-db
# 2. Tests + frontend build
.venv/bin/python -m pytest -q && npm --prefix ui ci && npm --prefix ui run build
# 3. Build (tag = date + short label; look at the currently deployed image first)
gcloud run services describe cpe334-student-cloud --region=asia-southeast1 --format='value(spec.template.spec.containers[0].image)'
TAG=$(date +%Y%m%d)-rel1
IMAGE=asia-southeast1-docker.pkg.dev/cpe-se-course-2026/cpe334-portal/portal:$TAG   # reuse the repo/name shown by the line above
gcloud builds submit --tag "$IMAGE" .
# 4. WORKER FIRST, then web (do not change env vars unless needed; use --update-*, never --set-*)
gcloud run deploy cpe334-provisioner --image="$IMAGE" --region=asia-southeast1
gcloud run deploy cpe334-student-cloud --image="$IMAGE" --region=asia-southeast1
```

Smoke tests: see section 12. Record the new revision names (`gcloud run revisions list --service=...`) for rollback.

## 3. Rollback

```sh
# Web or worker: send traffic back to the previous revision (names from `gcloud run revisions list`)
gcloud run services update-traffic cpe334-student-cloud --region=asia-southeast1 --to-revisions=PREVIOUS_REVISION=100
gcloud run services update-traffic cpe334-provisioner  --region=asia-southeast1 --to-revisions=PREVIOUS_REVISION=100
```
Roll back web and worker together if the DB schema changed (schema changes are additive; older revisions tolerate them).

Database restore (destructive; overwrites current portal data, **UNVERIFIED**):
```sh
gcloud sql backups list --instance=cpe334-portal-db
gcloud sql backups restore BACKUP_ID --restore-instance=cpe334-portal-db
```
Stop activations first (empty queue, no TA actions). Restore is only for data corruption; code problems are fixed by rollback.

## 4. TA management (`TA_EMAILS`)

TAs are the comma-separated `TA_EMAILS` env var on the **web** service. Removing an address revokes that TA's session on its next request.
**Never use `--set-env-vars` or `--update-env-vars TA_EMAILS=a,b` blindly**: `--set-env-vars` wipes every other variable, and an unquoted comma splits the value.

```sh
# See current value
gcloud run services describe cpe334-student-cloud --region=asia-southeast1 --format=json \
  | python3 -c "import json,sys;[print(e['name'],'=',e.get('value')) for e in json.load(sys.stdin)['spec']['template']['spec']['containers'][0]['env'] if e['name']=='TA_EMAILS']"
# Set the FULL new list (custom delimiter ^@^ lets commas live inside the value); only this var changes
gcloud run services update cpe334-student-cloud --region=asia-southeast1 \
  --update-env-vars='^@^TA_EMAILS=ta1@gmail.com,ta2@gmail.com'
```
Caveat: `ops_admin_dashboard.py` writes `private/hosted-admin-env.json` with `TA_EMAILS` from its `--ta-email` flags (now repeatable; the old version overwrote the list with one hardcoded account). Pass every TA, or ignore that file and use the command above. TAs do not need a roster row.

## 5. GITHUB_API_TOKEN (repo review rate limit)

`repo_review.py` reads `GITHUB_API_TOKEN` from the environment to raise the GitHub rate limit. Use a fine-grained, read-only token for public repos (no repository permissions, no scopes beyond public read). Store it in Secret Manager and mount it on the **web service only**; never put it in an env var value, the image or the worker.

```sh
# Create the secret (paste token on stdin; do not put it in shell history)
gcloud secrets create cpe334-github-token --replication-policy=automatic
printf '%s' "$TOKEN" | gcloud secrets versions add cpe334-github-token --data-file=-
# Let the web runtime SA read it, then mount it (WEB only)
gcloud secrets add-iam-policy-binding cpe334-github-token \
  --member=serviceAccount:cpe334-portal@cpe-se-course-2026.iam.gserviceaccount.com --role=roles/secretmanager.secretAccessor
gcloud run services update cpe334-student-cloud --region=asia-southeast1 --update-secrets=GITHUB_API_TOKEN=cpe334-github-token:latest
```
Rotate: add a new version, then `gcloud run services update ... --update-secrets=GITHUB_API_TOKEN=cpe334-github-token:latest` again (forces a new revision). Unverified: whether the app's runtime SA name matches `cpe334-portal`; check `gcloud run services describe`.

## 6. Operator scripts (all dry-run by default)

All team scripts read team ids from the portal DB, so start the Cloud SQL proxy (separate terminal) and keep `private/hosted-secrets.json`:
```sh
cloud-sql-proxy cpe-se-course-2026:asia-southeast1:cpe334-portal-db --port 55440
```
Run from the repo root with the project venv. `--account you@gmail.com` selects the gcloud login (otherwise application default credentials). Never run an `ops_*` script from the Cloud Run image; they are not in it.

### Backfill secret slots (`app-secret-1..5`) for already-ready teams
```sh
.venv/bin/python ops_backfill_secret_slots.py                  # dry-run, all ready teams
.venv/bin/python ops_backfill_secret_slots.py --group TEAM_ID  # dry-run one team
.venv/bin/python ops_backfill_secret_slots.py --apply          # really create slots + grant IAM
```

### Pause / resume (stop or restart the 24h/day Cloud SQL charge)
```sh
.venv/bin/python ops_pause_team.py  --group TEAM_ID --account you@gmail.com           # dry-run: prints what would change
.venv/bin/python ops_pause_team.py  --all-ready --apply --account you@gmail.com       # SQL activationPolicy NEVER for all ready teams
.venv/bin/python ops_pause_team.py  --group TEAM_ID --scale-run-to-zero --apply       # also Cloud Run minInstanceCount -> 0
.venv/bin/python ops_resume_team.py --group TEAM_ID --apply --account you@gmail.com   # activationPolicy ALWAYS
```
Paused teams' apps cannot reach their database until resumed (starting takes a few minutes). Storage still bills (small). Resume does not restore Cloud Run min instances (the old value is not stored). Tell students before pausing.

### Teardown (permanent) - see also section 9
```sh
.venv/bin/python ops_teardown_team.py --group TEAM_ID                                   # dry-run: lists every resource
.venv/bin/python ops_teardown_team.py --group TEAM_ID --confirm-delete PREFIX --apply   # irreversible
```
It deletes Cloud Run service+job, SQL `PREFIX-pg`, Artifact Registry repo, all team secrets (incl. app-secret-1..5), WIF provider+pool, log view, the team's project-level IAM bindings and both service accounts. If ANY existing resource fails the ownership check the whole team is refused and nothing is deleted. `--all-ready` is rejected. Back up first if the data matters: `gcloud sql backups create --instance=PREFIX-pg`. A deleted SQL instance name cannot be reused for about a week. The portal DB rows (team, activation) are NOT removed: to let a team activate again, TA must reset its activation row in the portal DB deliberately.

Other scripts: `ops_bootstrap_live.py --account you@gmail.com [--apply]` (idempotent queue/identity bootstrap), `ops_admin_dashboard.py` (dashboard IAM/dataset, see section 4), `ops_verify_admin_telemetry.py --account you@gmail.com` (read-only check). One-shot scripts from the launch are in `ops/archive/` and must not be re-run.

## 7. Raising `TEAM_ACTIVATION_LIMIT`

The limit is currently the constant `TEAM_ACTIVATION_LIMIT=36` in `app.py`; it is being changed to an env var with default **39** (a code change owned by the app maintainers; check `grep -n TEAM_ACTIVATION_LIMIT app.py` before relying on this). Cloud SQL allows 40 instances per project and the portal DB uses one, so **39 is the hard ceiling** without a quota increase. Once it is an env var:
```sh
gcloud run services update cpe334-student-cloud --region=asia-southeast1 --update-env-vars=TEAM_ACTIVATION_LIMIT=39
gcloud sql instances list --format='value(name,state)' | wc -l   # current instance count
```
Raising above 39 needs a Cloud SQL quota increase request in the console first, and also credits headroom (each team is about one more db-f1-micro running 24h).

## 8. Adding members and teams (TA UI)

Sign in with a TA Gmail. **Add team** creates a roster group and approves its first Gmail (no cloud resources until the students Activate). In a team's drawer, **Members -> Add member** approves another Gmail; for an active team the private worker syncs IAM through a membership task. **Remove** marks the member `removing` and revokes only that user's bindings on the team's own resources (service accounts and teammates untouched). If a member shows pending/error, use the retry action, and check the worker logs (section 11). Details: `TEAM-MEMBERS.md`.

## 9. End of course

1. Grading done and TA approval given (cleanup is TA-managed, never automatic).
2. Optionally `ops_pause_team.py --all-ready --apply` right after the last demo to stop charges while grading.
3. Back up anything to keep: per-team `gcloud sql backups create --instance=PREFIX-pg`, export grades/costs from the dashboard.
4. Dry-run teardown for every team: `ops_teardown_team.py --group ID` and read the plan. Then delete team by team with `--confirm-delete PREFIX --apply`.
5. Verify nothing is left: `gcloud sql instances list`, `gcloud run services list --region=asia-southeast1`, `gcloud artifacts repositories list`, `gcloud secrets list --filter='labels.cpe334-team:*'`.
6. Finally scale the portal itself down or delete `cpe334-portal-db` and the queue when the course data is archived.

## 10. Cost control

Credits are shared (about THB 9.7k, expire **24 January 2027**); there is no per-team hard cap. The TA dashboard shows delayed (hours) costs from the billing export. A Billing budget only alerts, it does not stop spending.
**NOT YET EXECUTED, UNVERIFIED** - create a budget with alerts at 50/80/100% (amount in the billing account currency, THB; check the credit/cost basis in the console, the default budget may not include credits):
```sh
gcloud services enable billingbudgets.googleapis.com
gcloud billing budgets create --billing-account=<BILLING_ACCOUNT_ID> \
  --display-name="cpe334-course" --budget-amount=9000THB \
  --filter-projects=projects/cpe-se-course-2026 \
  --threshold-rule=percent=0.5 --threshold-rule=percent=0.8 --threshold-rule=percent=1.0
```
Or Console -> Billing -> Budgets & alerts. Add the TA emails as notification recipients there.
If spend runs hot: `ops_pause_team.py --all-ready --apply` is the fastest lever (Cloud SQL dominates).

**Credit nearing expiry (24 Jan 2027):** when credits end the billing account falls back to its payment method; if none is valid, billing is disabled and **all resources in the project may stop together** (UNVERIFIED exact behaviour). Before ~10 January: finish grading, back up, pause or tear down all teams, tell students to export their work, and decide whether the portal stays up on a paid account.

## 11. Failure playbook

- **Activate stuck > 20 min.** Check the team in the TA dashboard (stage, last worker checkpoint). `gcloud tasks list --queue=cpe334-activation --location=asia-southeast1` (a task present = still retrying). Worker logs: `gcloud run services logs read cpe334-provisioner --region=asia-southeast1 --limit=100`. SQL create takes several minutes; only 2 can be pending at once, others wait. If failed with a permanent error, fix the cause and use the Retry button; retry resumes owned resources and never rotates passwords.
- **Worker 503 loop.** Worker is max-instances 1 / concurrency 1, so a long stage can return 503 to Cloud Tasks and the queue retries (normal, up to 15-60 s backoff). If it never clears: check worker revision is Ready and has 100% traffic, the `cpe334-provisioner` SA still has its roles (`ops_bootstrap_live.py --account ... ` dry-run), DB reachable, then `gcloud tasks queues describe cpe334-activation --location=asia-southeast1` is not paused (`gcloud tasks queues resume ...`).
- **"Billing quota exceeded".** Google limits how many projects/resources a billing account may be linked to or use. Check the project is linked and enabled: `gcloud billing projects describe cpe-se-course-2026`; if it is a quota on API usage, request an increase in Console -> IAM & Admin -> Quotas, then retry the team. UNVERIFIED wording; read the exact error in the worker log.
- **Cloud SQL PENDING_CREATE limit / count limit.** The provisioner allows at most 2 `PENDING_CREATE` instances and 40 instances in total; the team waits (`Pending`) or fails with "Course database count limit reached; TA review required". Free slots with teardown of abandoned teams, or raise the Cloud SQL quota. List: `gcloud sql instances list --format='table(name,state,settings.activationPolicy)'`.
- **Repo review GitHub rate limit.** Unauthenticated GitHub allows ~60 requests/hour per IP; Cloud Run shares IPs. Set `GITHUB_API_TOKEN` (section 5). Students can retry later; resource-only Activate does not need GitHub.
- **A team's resource has a foreign owner** ("Resource name already exists without this group ownership; TA review required"). Do not delete it. Find who owns it (`gcloud ... describe`, labels/description), resolve manually, retry.
- **Wrong person has access.** Remove the member in the TA UI (section 8), do not hand-edit IAM.

## 12. Verification checklist after each deploy

- [ ] `gcloud run revisions list --service=cpe334-provisioner --region=asia-southeast1` and same for `cpe334-student-cloud`: new revision Ready, 100% traffic, worker deployed before web.
- [ ] `gcloud run services describe cpe334-student-cloud --region=asia-southeast1` still has `PORTAL_MODE=live`, `LIVE_ACTIVATION_ENABLED=1`, `WORKER_URL`, `TA_EMAILS`, `BILLING_EXPORT_TABLE`, and the secret mounts (compare with the previous revision).
- [ ] Open the portal URL: login page loads, EN/TH switch works; sign in as a TA: dashboard loads with no source errors.
- [ ] Sign in as a student (or a TA-created test team in a throwaway state): status page loads; **Project Kit** and **Lab 5 starter-kit** downloads work (`/api/kit/download`, `/api/lab5-kit/download`).
- [ ] Anonymous `curl -i https://<worker-url>/internal/provision -X POST` returns 401/403/404 (never 200).
- [ ] `gcloud tasks list --queue=cpe334-activation --location=asia-southeast1` is still empty / not paused.
- [ ] Worker and web logs for the last 10 minutes: no tracebacks (`gcloud run services logs read ... --limit=50`).
- [ ] `ops_backfill_secret_slots.py` dry-run reports "already up to date" for ready teams (proves worker code and IAM agree).
- [ ] Save the previous revision names for rollback (section 3).
