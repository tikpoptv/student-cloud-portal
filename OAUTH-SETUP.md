> Current release: real activation is enabled through a private provisioner and persistent PostgreSQL. See [LIVE-ACTIVATION.md](LIVE-ACTIVATION.md) for current state and evidence; preview-only notes below describe earlier milestones.

# Google login setup

Status on 19 November 2026: deployed to https://cpe334-student-cloud-4d7hbszvwq-as.a.run.app in the TA account. The user created the Web OAuth client and provided its downloaded JSON. Client secret, session secret and database URL are stored in Secret Manager; none are included in the build context. A real Google consent/token callback was verified with an unlisted account, which correctly received the portal's roster-denied 403. A real approved student's positive sign-in remains to be tested. Group resource activation remains simulated.

## Course identity and roster

- Google project: `cpe-se-course-2026`, number `670075229477`.
- Project account verified through Cloud Console: `<course-admin-account>`.
- Source: <course sheet URL, kept private>
- Read-only source range: `summary_clear!A1:E50` (four populated columns).
- Latest bounded connector snapshot: `private/roster-current.json`. Its 36 normalized team emails and names match all 36 enabled non-demo database entries. No access grants or identity changes were needed.
- This is a reviewed local roster, not an automatic live Sheet authorization feed. The intake Sheet has historically allowed link editing. Changes require TA review; a new Sheet row alone never enables login. Existing Google subject bindings, prefixes and activation ownership must not be reassigned.
- Check a newly fetched snapshot with `.venv/bin/python check_roster.py`; it prints counts only and exits nonzero for discrepancies. Refresh the snapshot via an authenticated bounded Sheet read, keeping the same source/tab and headers. The checker does not add, remove or modify users.

## Google Auth Platform

1. Under the course account, open https://console.cloud.google.com/auth/overview?project=cpe-se-course-2026
2. App name: `CPE334 Student Cloud Portal`. Support and developer contact: `<course-admin-account>`. Audience: External, because students use personal Gmail.
3. The user must read and accept Google's API Services User Data Policy themselves. The user accepted this policy and completed branding creation.
4. Create an OAuth client with application type **Web application**. Confirm the website's final origin first; a production client should not include local testing origins.
5. Authorized redirect URI must match `BASE_URL` plus `/auth/callback` exactly. For a separate local test client it is `http://127.0.0.1:8876/auth/callback`. For students use the actual HTTPS site origin plus `/auth/callback`.
6. Request only `openid email profile`. Do not request Drive, Sheets, Gmail, Cloud Platform or offline access from students. Sheet roster review is a separate TA operation.
7. Review Audience status and testing restrictions for the actual configured scopes before class access. A Google account being able to consent does not grant portal access: the local approved roster remains the authorization boundary.
8. Download the client JSON directly into private storage. Do not paste the client secret in chat or upload it into the repository. Public-client ID alone is insufficient for this server flow.

## Install credentials locally

After creating the **separate test Web client** and downloading its JSON:

```sh
.venv/bin/python configure_oauth.py --client-json /absolute/path/to/downloaded-client.json --base-url http://127.0.0.1:8876
.venv/bin/python run_portal.py
```

For a hosted site, pass its actual HTTPS origin instead. `configure_oauth.py` validates that the callback is registered in the downloaded JSON, writes `private/runtime.json` with mode 0600, generates a session secret and preserves it on reconfiguration. It does not print credentials. Stop the existing local preview server before starting another on port 8876.

`AUTH_MODE=google` enables Google login and disables the demo login route and demo sessions. `PORTAL_MODE=preview` is deliberately independent: real users can review a simulated activation without receiving unverified live resources. Secure session cookies are required for HTTPS; loopback HTTP is allowed only for local testing. `start.sh` is still the demo launcher; use `run_portal.py` for the configured Google-login run.

## Public hosting and acceptance

Hosted service: Cloud Run `cpe334-student-cloud`, region `asia-southeast1`, with one Gunicorn worker/four threads, 512 MiB, max two instances and min zero. A separate PostgreSQL 16 Cloud SQL instance `cpe334-portal-db` (db-f1-micro, 10GB SSD, backups and deletion protection enabled) stores the roster, identity bindings, reviews, sessions' one-use OAuth state and activation records. It incurs time-based cost even while Cloud Run scales to zero. Runtime session cookies are Secure/HttpOnly/SameSite=Lax. The hosted database has 36 approved teams imported from the reviewed snapshot, preserving their original IDs and prefixes.

Runtime identity: `cpe334-portal@cpe-se-course-2026.iam.gserviceaccount.com`, Cloud SQL Client and access only to the three portal secrets. Cloud Run mounts Cloud SQL through its authenticated Unix socket. No service-account key was created. Secrets are pinned to versions: cpe334-portal-session:1, cpe334-portal-database:2, cpe334-portal-oauth:1. Version 1 of the database URL was disabled; version 2 is the configured version. The initially generated draft was never accepted as a database credential.

SQLite remains available for local demos only. Hosted `DATABASE_URL` selects PostgreSQL. `database.py` preserves parameterized SQL and serialized writer sections using a PostgreSQL transaction advisory lock. `entrypoint.sh` runs the simulation-only durable worker alongside Gunicorn while PORTAL_MODE is preview. The worker never calls cloud provisioning APIs. Public landing pages are reachable; all group-data APIs still require roster-authorized app sessions. Do not publish the private directory or OAuth download.

Before claiming sign-in is live, verify in the browser:

- An approved student's real Google account signs in to the correct existing team.
- An unlisted account is denied without exposing the roster.
- An existing demo session cannot access the real login mode.
- A disabled team loses access, including through an existing session.
- A second Google subject cannot take over an already bound team email.
- Redirect errors, cancellation, replay and expired state fail safely.
- Browser cookies are Secure/HttpOnly on the actual HTTPS origin.

Automated checks: 27 Python tests (including local PostgreSQL concurrency and restart persistence) plus 3 frontend tests passing. Positive approved-student tests mock the token exchange; the live negative-path callback was verified separately before the user asked to take over browser testing. Provisioning, IAM isolation and student deployment still have separate launch gates.

References:
- https://developers.google.com/identity/openid-connect/openid-connect
- https://developers.google.com/identity/protocols/oauth2/web-server
- https://support.google.com/cloud/answer/15549257

## Current deployment workflow

Build using the explicit .gcloudignore allowlist. Private roster and credential files are excluded. `gcloud builds submit` builds the Dockerfile and pushes to Artifact Registry `cpe334-portal`; update only the Cloud Run image to preserve configured environment and Secret Manager references. Verify the new revision reports Ready. Do not deploy a blank SQLite-backed revision with OAuth enabled. The first private bootstrap revision had no OAuth credentials and accepted no student logins; subsequent revisions use persistent PostgreSQL.

The `summary_clear` Sheet is the reviewed source, not an automatic grant feed. Fetch/review/import changes as a TA; students cannot self-enroll by editing the issue sheet. Google Auth Platform is External with identity-only scopes; the live real consent worked without additional API scopes. An approved student should now verify positive access.
