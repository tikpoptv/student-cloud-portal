> Sections below are dated 19 November 2026 release notes. The billing and TA sections are current; the deployment and verification notes at the end are historical evidence for that release (revision names and test counts are not maintained). Operations: [RUNBOOK.md](RUNBOOK.md).

# Current billing — 19 November 2026

Course project `cpe-se-course-2026` is now linked to TA **My Billing Account <BILLING_ACCOUNT_ID>**. The user approved retiring empty `My First Project` (`project-a49e9120-384e-4edc-860`); its default-only inventory was rechecked, billing detached, and project shutdown requested (Google recovery period applies). The resulting free billing slot was used for the existing course project. No new course project or resource copy was needed. Existing apps/SQL in `<other-project-1>` and `<other-project-2>` remain on the same TA billing account.

The user clicked Save for Detailed usage cost export. The Console was read back as **Enabled**, project CPE-SE-Course-2026, dataset `cpe334_billing` (US). Expected table configured in the portal:
`cpe-se-course-2026.cpe334_billing.gcp_billing_export_resource_v1_01EB56_DF44A5_45A3EB`.

Credits were checked directly in Google: **THB 9,665.84**, original THB 10,077.76, Available 96%, expiry **24 January 2027**. The portal stores this as a timestamped manual observation with the source billing account; it is not an API/live balance. Billing export may take hours to populate and costs remain delayed. Historical usage before transfer was billed to the previous account and is not moved retroactively.

This section supersedes earlier billing limitations (the old account <OTHER_BILLING_ACCOUNT_ID> was replaced).

# TA dashboard — 19 November 2026

Sign in at the existing portal using a TA Gmail listed in `TA_EMAILS` (more than one TA is supported). A fresh Google login is required if an older student/denied session is still open. TA access comes from the server-side `TA_EMAILS` allowlist and verified Google OIDC; spreadsheet membership cannot grant TA privileges. Removing an address from the allowlist revokes existing admin sessions on their next request. Student API sessions cannot call any admin endpoint; TA sessions do not impersonate student teams.

The dashboard includes all non-demo roster teams, enablement, repo review, login counts and last login, last portal activity (sampled once per minute), activation stage/errors, live Cloud Run readiness/revision/placeholder distinction, migration execution, SQL state/tier/disk/activation policy, Artifact Registry size, 24-hour request and 5xx totals and an hourly chart. Group drawers show cloud logs (100 most recent entries; severity and 1h/24h/7d filters), portal activity and resource metadata. Infrastructure readiness is not application health. Recent activity is not confirmed online presence.

Cloud metadata is cached persistently for 60 seconds. Available costs are cached for 15 minutes; pending/failed billing sources retry after 60 seconds while the visible dashboard polls every minute. Monitoring has provider latency. Each cloud-source failure is shown separately; unavailable values remain missing, not zero. Logging reads and balance observations are audited. Secret values, raw service env and arbitrary structured log bodies are not returned. Common password/connection-string/token formats are redacted from log messages; redaction does not guarantee removal of all sensitive text applications may log.

## Finance (current)

Billing account **<BILLING_ACCOUNT_ID>** (TA My Billing Account). Detailed usage cost export is enabled to `cpe-se-course-2026.cpe334_billing` (US). The portal reads the table configured in `BILLING_EXPORT_TABLE` (`cpe-se-course-2026.cpe334_billing.gcp_billing_export_resource_v1_01EB56_DF44A5_45A3EB`). Console: https://console.cloud.google.com/billing/<BILLING_ACCOUNT_ID>/export and credits at https://console.cloud.google.com/billing/<BILLING_ACCOUNT_ID>/credits .

Costs are delayed billing data (hours), not real-time spend. The query is limited to this project and a maximum 1 GB processed per query. Team labels and exact assigned resource names attribute costs. Ambiguous or unattributed rows remain in a separate shared-cost bucket. Gross cost, applied credits and net cost are kept separate, and currencies are never mixed. Totals cover available export history, not guaranteed lifetime history. The shared credit balance cannot be inferred by subtracting this project's net spend. `awaiting_export` / `awaiting_data` means Google has not written the table or rows yet; it is not an error.

Credits tab permits TA to record a balance **actually checked in Google**, with currency, observation date/time and a note. This is a manual historical observation, never a live API value. A budget alert is **not** configured yet; see RUNBOOK.md (Cost control).

Google's export documentation: https://docs.cloud.google.com/billing/docs/how-to/export-data-bigquery-setup
Credit visibility: https://docs.cloud.google.com/billing/docs/how-to/resolve-issues

## Access and deployment

The public runtime has read-only Run, SQL, registry, logging and monitoring permissions plus the existing project-identity permission. BigQuery job execution is project-scoped; billing dataset read access is limited to the prepared billing dataset. No new student grants or provisioning administrator roles were added. Existing queue/provisioner separation is retained. This is an observation dashboard; there are no stop/delete or IAM-edit buttons.

Operators: `ops_admin_dashboard.py --account ... --ta-email ... [--apply]` (dry-run by default) prepares the dataset, IAM and private deployment env file; pass every TA with repeated `--ta-email` (it used to overwrite TA_EMAILS with one account). Production image includes `admin_dashboard.py`; private operator scripts/evidence stay outside the build context. Public env adds TA_EMAILS, BILLING_EXPORT_TABLE and BILLING_EXPORT_LOCATION. Web and worker run the same image and are deployed worker first (RUNBOOK.md); both tolerate additive tables.

Backend tests cover verified TA login, student/anonymous denial, allowlist revocation, activity/cache, scoped logs/redaction, validated/audited credit observations and billing attribution/query bounds. Real PostgreSQL tests cover dashboard SQL and observation writes. EN/TH tests cover the new screen. Browser/UI acceptance is intentionally left to the user.

Historical production verification (19 November 2026): image `20261119-admin1`, revision `cpe334-student-cloud-00006-phd`, Ready and 100% traffic. 50 backend tests passed (including local PostgreSQL), 3 frontend tests passed, and production bundle built. All six telemetry sources returned without errors under the actual runtime identity. A real BigQuery synthetic CTE verified the export SQL/parser; no real costs were invented. The hosted additive schema retained 36 approved teams. Temporary operator impersonation permission was removed after verification.
