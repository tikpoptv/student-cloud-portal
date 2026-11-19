# CPE334 Student Cloud Portal

A web portal that gives each student team in the CPE334 Software Engineering course a controlled, isolated slice of Google Cloud, and lets teaching assistants (TAs) supervise it.

Teams sign in with Google, press **Activate**, and receive their own Cloud Run service, Cloud SQL database, Artifact Registry repository, runtime and deployer service accounts, and Secret Manager slots. Access is granted per team through narrowly scoped IAM roles. TAs manage groups and members and monitor activation and cost from a dashboard.

> สรุปภาษาไทยอยู่ท้ายเอกสาร (Thai summary at the end of this document).

## Contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [Repository structure](#repository-structure)
4. [Running locally](#running-locally)
5. [Testing](#testing)
6. [Deployment and operations](#deployment-and-operations)
7. [Security model](#security-model)
8. [Documentation](#documentation)
9. [Scope and limitations](#scope-and-limitations)
10. [สรุปภาษาไทย](#สรุปภาษาไทย)

## Features

**For students**

- Google sign-in restricted to the reviewed course roster (verified email and subject pinning).
- **Team resources:** the identifiers, Secret Manager names (never values), SQL connection name and image repository assigned to the team, downloadable as JSON.
- **Final Project Kit:** a stack-agnostic command-line kit (`kit.sh`) for building and deploying any containerised project to the team's Cloud Run service, with guides in English and Thai.
- **Lab 5:** repository review and per-file diff against the Lab 5 layout, with a downloadable patch or a tailored starter kit. The portal reads only a fixed list of public GitHub paths pinned to a verified commit SHA; it never clones or executes student code.
- Resources can be activated without a GitHub repository.
- Interface in Thai and English.

**For teaching assistants**

- Dashboard of all teams: activation state, Cloud Run, Cloud SQL and registry inventory, request counts and estimated cost from Cloud Billing export.
- Add or remove groups and members, with the corresponding IAM grants and revocations.
- Operator scripts (all dry-run by default) to pause, resume, or tear down a team.

## Architecture

```
Browser ──► Cloud Run: portal web (Flask + React/Ant Design)
                 │  enqueue
                 ▼
          Cloud Tasks queue ──► Cloud Run: private provisioner worker (same image)
                                      │  six idempotent stages
                                      ▼
   per team:  Artifact Registry · Cloud SQL (PostgreSQL) · service accounts + IAM
              Secret Manager slots · Cloud Run service + migrate job · GitHub link

Portal state: Cloud SQL (PostgreSQL)   ·   Cost data: BigQuery billing export
```

- **Web service** serves the interface and API. **Worker** runs the provisioning stages, is not publicly invokable, and only the Cloud Tasks service account may call it.
- Provisioning is resumable: each stage is idempotent, uses lease and token fencing, and records progress and a worker heartbeat.
- Backend: Flask, Authlib, PostgreSQL (SQLite for local preview only). Frontend: React 19 and Ant Design 6, built with Vite into `static/ui`.

## Repository structure

```
app.py, activation.py, live_provision.py   web routes, activation flow, provisioning stages
membership.py, admin_dashboard.py          member management, TA dashboard
repo_review.py, database.py, localization.py
ui/                  React source and frontend tests (build output is committed in static/ui)
project-kit/         Final Project Kit (kit.sh, templates, docs, tests)
reference-kit/       Lab 5 reference deployment files
locales/, templates/, static/
ops_*.py             operator scripts (dry-run by default)
tests/               backend tests
RUNBOOK.md           operating procedures
```

## Running locally

```sh
./start.sh
```

Open <http://127.0.0.1:8876>. Local preview uses a synthetic team and simulates provisioning; it does not touch Google Cloud.

Frontend:

```sh
npm --prefix ui ci
npm --prefix ui run build
```

For real Google sign-in, see [OAUTH-SETUP.md](OAUTH-SETUP.md).

## Testing

```sh
python -m pytest -q          # backend; PostgreSQL tests are skipped unless a local database is provided
npm test --prefix ui         # frontend
python -m unittest discover project-kit/tests   # Project Kit
```

The PostgreSQL integration tests run only against a disposable local database (set `PORTAL_TEST_POSTGRES`) and refuse non-local hosts.

## Deployment and operations

The portal is deployed to Cloud Run as two services built from one image. Deployment, rollback, database restore, team pause/resume/teardown, cost control and a failure playbook are documented in [RUNBOOK.md](RUNBOOK.md).

Provisioning creates billable resources, chiefly one Cloud SQL instance per team. Review the cost guidance and configure a budget alert before opening activation to a class.

## Security model

- Credentials, roster data and local state belong in an untracked `private/` directory and are never committed. This repository contains no secrets.
- No service account keys or cloud credentials are placed in browser code or downloads.
- Members receive least-privilege roles scoped to their own service, job, registry and secrets, plus an instance-conditioned Cloud SQL client role.
- CSRF protection, session pinning, request throttling and a per-team activation limit are enforced server side.
- The portal's own tests use fictitious data only.

## Documentation

| Document | Content |
|---|---|
| [RUNBOOK.md](RUNBOOK.md) | Deploy, rollback, restore, team operations, cost control |
| [LIVE-ACTIVATION.md](LIVE-ACTIVATION.md) | Provisioning stages and live activation |
| [ADMIN-DASHBOARD.md](ADMIN-DASHBOARD.md) | TA dashboard and billing export |
| [TEAM-MEMBERS.md](TEAM-MEMBERS.md) | Group and member management |
| [RESOURCE-ONLY.md](RESOURCE-ONLY.md) | Activation without GitHub |
| [ACTIVATION-STATUS-UX.md](ACTIVATION-STATUS-UX.md) | Activation progress display |
| [OAUTH-SETUP.md](OAUTH-SETUP.md) | Google sign-in setup |
| [project-kit/README.md](project-kit/README.md) | Project Kit guide (Thai: [README.th.md](project-kit/README.th.md)) |

## Scope and limitations

- The code targets one specific Google Cloud project and course environment. Several identifiers, such as project, queue and service names, are specific to it and must be adapted before reuse.
- Provisioning is verified against the real environment, but the pause and teardown operator scripts have not been exercised against live Google Cloud.
- The Project Kit was tested on macOS; Windows and Safari have not been tested.
- A team receives a single Cloud Run service and a single database. Separate frontend and backend services are not provisioned.
- Some historical notes in the documents describe the system at the time they were written.

## สรุปภาษาไทย

พอร์ทัลสำหรับวิชา CPE334 ที่ให้แต่ละกลุ่มนักศึกษาได้พื้นที่ Google Cloud ของตัวเองแบบแยกจากกัน และให้ TA ดูแลได้

- นักศึกษาล็อกอินด้วย Google แล้วกด **Activate** ระบบจะสร้าง Cloud Run, Cloud SQL, Artifact Registry, service account และช่องเก็บ Secret ให้ทีม พร้อมสิทธิ์ที่จำกัดเฉพาะของทีมตัวเอง
- มี **Final Project Kit** (`kit.sh`) สำหรับ build และ deploy โปรเจกต์ที่เป็น container ได้ทุกภาษา มีคู่มือภาษาไทยและอังกฤษ
- TA มีแดชบอร์ดดูสถานะทุกทีม จัดการกลุ่มและสมาชิก และมีสคริปต์ pause/resume/teardown (ค่าเริ่มต้นเป็น dry-run)
- รันในเครื่อง: `./start.sh` แล้วเปิด <http://127.0.0.1:8876> (โหมดจำลอง ไม่แตะ Google Cloud)
- ความลับและรายชื่อนักศึกษาเก็บในโฟลเดอร์ `private/` ที่ไม่ถูก commit repo นี้ไม่มีความลับ
- ข้อควรระวัง: ระบบสร้างทรัพยากรที่มีค่าใช้จ่าย (Cloud SQL ต่อทีม) ควรตั้ง budget alert ก่อนเปิดให้ใช้ ดูรายละเอียดใน [RUNBOOK.md](RUNBOOK.md)
