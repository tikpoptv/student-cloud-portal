# Lab 5 Starter Kit, adapted for team {{PREFIX}}

This is the course Starter Kit (deploy.sh, release.sh, deploy.yml) already adapted for your team.
You do not need `git apply`. Just copy the files into your repo and edit them.

## 1. How to use it

1. In your repo, create a branch from `staging`:
   `git switch staging && git switch -c lab5/shared-cloud`
2. Unzip this file and copy the folders `deploy/` and `.github/` into the ROOT of your repo.
   Overwrite the old `deploy/deploy.sh`, `deploy/release.sh` and `.github/workflows/deploy.yml`.
3. Keep the executable bit: `chmod +x deploy/deploy.sh deploy/release.sh`
4. Fix the CHANGE ME points below, then run `DRY_RUN=1 bash deploy/deploy.sh`.
5. Open a PR into `staging`. A teammate must review it. Then open a release PR from `staging` to `main`. CI must be green before you merge.

## 2. What we changed for you

- All resource names now use your team prefix `{{PREFIX}}` (service, migration job, database,
  Cloud SQL `{{PREFIX}}-pg`, registry, service account, secret names).
- Shared project `{{PROJECT}}` and region `{{REGION}}` are fixed.
- The steps that create infrastructure and IAM (enable APIs, Cloud SQL, secrets, public access)
  are removed. The portal and the TA create them for you. Never add them back.
- The script builds the image, pushes it by commit SHA, updates the migration job and the service.

## 3. CHANGE ME points you must check yourself

Open `deploy/deploy.sh` and `.github/workflows/deploy.yml` and search for `CHANGE ME`.

- Port: `--port` must match the port your app listens on.
- Migration / seed command: `--command` and `--args` of the migration job must run YOUR migration (and seed) command.
- Database and URL format: `DATABASE_URL` format must match what your app expects.
  The secret value is made by the portal; never write a password in a file.
- Memory / scaling: `--memory`, `--cpu`, `--max-instances` for your app.

## 4. What is NOT in this zip

- `deploy/teardown.sh`: do NOT use the old one. Ask a TA for pause or cleanup.
- `ci-docker.yml`, `deploy/smoke_test.py`, `Dockerfile`, `deploy/tests/`: take them from your own
  Starter Kit zip / your app, unchanged. We did not invent them.
- No secret values. Secrets stay in Secret Manager.

---

# ภาษาไทย

ชุดนี้คือ Starter Kit ของวิชา (deploy.sh, release.sh, deploy.yml) ที่ปรับให้ทีม `{{PREFIX}}` แล้ว
ไม่ต้องใช้ `git apply` แค่คัดลอกไปวางใน repo แล้วแก้ต่อ

1. สร้าง branch จาก `staging`: `git switch staging && git switch -c lab5/shared-cloud`
2. แตก zip แล้วคัดลอกโฟลเดอร์ `deploy/` และ `.github/` ไปวางที่ root ของ repo (ทับ 3 ไฟล์เดิม)
3. `chmod +x deploy/deploy.sh deploy/release.sh` แล้วรัน `DRY_RUN=1 bash deploy/deploy.sh`
4. เปิด PR เข้า `staging` ให้เพื่อน review จากนั้นเปิด release PR เข้า `main` และต้องให้ CI ผ่านก่อน merge

สิ่งที่ปรับให้: ชื่อ resource ทั้งหมดใช้ prefix `{{PREFIX}}`, ใช้โปรเจกต์ `{{PROJECT}}` และ region `{{REGION}}`,
ตัดขั้นสร้าง infrastructure/IAM ออก เพราะพอร์ทัลและ TA สร้างให้แล้ว

จุด CHANGE ME ที่ต้องตรวจเอง: port, คำสั่ง migration/seed, ฐานข้อมูลและรูปแบบ DATABASE_URL, memory/scaling

ไม่มีใน zip: `teardown.sh` (ห้ามใช้ ขอ TA ถ้าต้องการหยุด/ลบ), `ci-docker.yml`, `smoke_test.py`, `Dockerfile`
และ `deploy/tests/` ให้ใช้ของเดิมจาก Starter Kit/แอปของกลุ่มโดยไม่แก้ ไม่มีรหัสผ่านหรือ secret ในไฟล์ใดเลย
