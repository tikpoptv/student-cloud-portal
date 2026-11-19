# Project Kit — เอาโปรเจกต์ของกลุ่มขึ้น Cloud Run

**ภาษาไทย** | [English](README.md)

ชุดเครื่องมือสำหรับ **โปรเจกต์ปลายภาค** ใช้ทรัพยากรบน Google Cloud ที่ portal เตรียมไว้ให้กลุ่มคุณ
ใช้ได้กับ **ทุกภาษา/เฟรมเวิร์ก** (Node, Python, Java, Go, เว็บ static + API ฯลฯ) ขอแค่มี `Dockerfile`
**ไม่ต้องทำ Lab 5 และไม่ต้องใช้ GitHub** (ถ้าภายหลังอยากเชื่อม GitHub มีตัวอย่าง workflow ให้ แต่เป็นทางเลือก)

## สิ่งที่คุณได้รับจาก portal (สร้างไว้ให้แล้ว ไม่ต้องสร้างเอง)

| ทรัพยากร | ชื่อ (ถ้า prefix ของกลุ่มคือ `grp01`) |
|---|---|
| Cloud Run service (เปิดเป็นสาธารณะ) | `grp01` |
| Cloud Run job สำหรับ migration | `grp01-migrate` |
| ฐานข้อมูล PostgreSQL (Cloud SQL) | instance `grp01-pg` |
| ที่เก็บ Docker image (Artifact Registry) | repo `grp01` |
| service account ที่แอปใช้รัน | `grp01-runner@cpe-se-course-2026.iam.gserviceaccount.com` |
| secret ใน Secret Manager | `grp01-database-url`, `grp01-admin-password`, `grp01-demo-password` |
| มุมมองอ่าน log | view `grp01` |

โปรเจกต์ Google Cloud คือ `cpe-se-course-2026` region `asia-southeast1` — ดูชื่อจริงของกลุ่มคุณได้ที่แท็บ **Team resources** ใน portal

## สิ่งที่ต้องมีก่อน

1. **gcloud CLI** — https://cloud.google.com/sdk/docs/install แล้วรัน `gcloud auth login`
   **ต้องล็อกอินด้วย Gmail เดียวกับที่ลงทะเบียนไว้ใน portal** (ไม่งั้นจะไม่มีสิทธิ์)
2. **Docker Desktop** (เปิดไว้ก่อน build) พร้อม `docker buildx`
3. **bash** (macOS/Linux มีอยู่แล้ว; Windows ใช้ WSL หรือ Git Bash — ดูหัวข้อ [Windows](#windows))
4. โปรเจกต์ของคุณมี `Dockerfile` และแอป **ฟังพอร์ตจากตัวแปร `PORT`** และ bind `0.0.0.0`
   (ยังไม่มี? ดูขั้นที่ 2)

## Quickstart 5 ขั้น

คัดลอกโฟลเดอร์ `project-kit/` ไปไว้ในโปรเจกต์ของคุณ (หรือรันจากที่ไหนก็ได้ แต่ให้ `cd` ไปที่โฟลเดอร์โปรเจกต์ก่อนรัน เพราะ `build` ใช้ Dockerfile ของโฟลเดอร์ปัจจุบัน) ตัวอย่างด้านล่างสมมติว่าอยู่ใน `./project-kit/`

**1) ตรวจข้อมูลทรัพยากรของกลุ่ม**
zip ที่โหลดจาก portal **มี `project-kit/resources.env` ที่กรอกให้กลุ่มคุณแล้ว** **อย่าเขียนทับ** ด้วย `cp resources.example.env resources.env` (ไฟล์ example เป็นแค่ตัวอย่างของ `grp01`) ให้เปิด `project-kit/resources.env` แล้วแก้ `STACK` (node|python|java|go|static|custom) และ `PORT` ให้ตรงกับแอปของคุณ
เฉพาะกรณีที่ไม่มี `resources.env` (เช่น คัดลอก kit มาจากที่อื่น) ให้สร้างด้วยวิธีใดวิธีหนึ่ง:
```sh
# a) โหลดไฟล์ JSON จาก portal (ปุ่ม Team resources บันทึกเป็น <prefix>-resources.json ส่วนชื่อเก่าคือ lab5-<prefix>-handoff.json ใช้ได้ทั้งสองชื่อ) แล้วแปลง:
./project-kit/from-portal-json.sh ~/Downloads/<prefix>-resources.json
# b) หรือคัดลอกตัวอย่างแล้วแก้ PREFIX และค่าอื่นให้ตรงกับแท็บ Team resources:
cp project-kit/resources.example.env resources.env
```
ถ้ามีฐานข้อมูลต้อง migrate ให้ตั้ง `MIGRATE_COMMAND` (ดู FAQ)

**kit.sh หาไฟล์ config ที่ไหน** — สำหรับ `resources.env`, `app.env`, `secrets.map` จะหาที่ **โฟลเดอร์ปัจจุบัน** (ที่คุณรันคำสั่ง) ก่อน แล้วค่อยหาใน **โฟลเดอร์ของ kit** (โฟลเดอร์ที่มี `kit.sh` เช่น `project-kit/`) ใช้ไฟล์แรกที่เจอ ส่วน `--env-file`, `--app-env`, `--secrets-map` ชี้ไปที่ไฟล์โดยตรง (ถ้าใส่ flag เหล่านี้แล้วไม่มีไฟล์ kit.sh จะหยุดพร้อม error ไม่ข้ามเงียบๆ) `from-portal-json.sh` เขียน `./resources.env` ในโฟลเดอร์ปัจจุบัน เว้นแต่ระบุ `-o` ส่วน `Dockerfile` (ของ `build`) ใช้จากโฟลเดอร์ปัจจุบันเสมอ

**2) ตรวจ Dockerfile** (ข้ามได้ถ้ามีแล้ว)
```sh
./project-kit/kit.sh --stack python init     # สร้าง Dockerfile + .dockerignore ตัวอย่าง ถ้ายังไม่มี
```
`init` ไม่เดา stack ให้: ถ้าไม่ใส่ `--stack` (และไม่มีบรรทัด `STACK=` ใน `resources.env`) จะหยุดพร้อมรายการ stack ที่ใช้ได้ `node|python|java|go|static` และ `--stack` ชนะค่าใน `resources.env` เสมอ **`Dockerfile` และ `.dockerignore` ที่มีอยู่แล้วจะไม่ถูกเขียนทับเด็ดขาด** ถ้าอยากเริ่มใหม่ให้ลบไฟล์ (`rm Dockerfile`) แล้วรัน `init` อีกครั้ง
`init` ยังเพิ่ม `.kit-state/`, `resources.env`, `app.env`, `secrets.map` ลงใน `.gitignore` ให้ด้วย (สร้างไฟล์ให้ถ้ายังไม่มี) เพื่อไม่ให้ commit ไฟล์เหล่านี้และไม่ทำให้แท็ก image ขึ้น `-dirty` สำหรับ `--stack static` ไฟล์ `.dockerignore` จะไม่ตัด `dist/` และ `build/` (Dockerfile ของ static คัดลอก `dist/`) และ `build` จะเตือนถ้า Dockerfile คัดลอก `dist/` หรือ `build/` แต่ `.dockerignore` ตัดทิ้ง template ของ Node เป็นแบบ multi-stage: ติดตั้ง dependency ทั้งหมด รัน `npm run build` ถ้ามี script build แล้วเก็บเฉพาะ dependency สำหรับ production (ติดตั้งด้วย `npm ci` ถ้ามี `package-lock.json` ไม่เช่นนั้นใช้ `npm install` โปรเจกต์ yarn / pnpm จึงใช้ได้) **ผู้ใช้ Prisma:** `npm prune --omit=dev` ลบ devDependencies รวมถึง `prisma` CLI ให้ย้าย `prisma` ไปไว้ใน `dependencies` หรือลบบรรทัด `npm prune` ใน Dockerfile (ไม่เช่นนั้น `npx prisma migrate deploy` จะล้มเหลว) template ของ Python, Node, Java ยก `/app` ให้ผู้ใช้ non-root แอปจึงเขียนไฟล์ได้ ส่วน template ของ Go ใช้ alpine (มี shell จึงใช้ `MIGRATE_COMMAND=/app/server migrate` ได้) และแอปที่เขียนไฟล์ให้เขียนที่ `/tmp`

**3) ตรวจความพร้อม**
```sh
./project-kit/kit.sh doctor
```
ถ้ามี `[ไม่ผ่าน]` จะบอกวิธีแก้ใต้บรรทัดนั้น (ล็อกอินผิดบัญชีเป็นสาเหตุที่พบบ่อยที่สุด)

**4) Build และ push image**
```sh
./project-kit/kit.sh build
```
build เป็น `linux/amd64` (Mac M1/M2/M3 ก็ใช้ได้), ติดแท็กด้วย git SHA หรือเวลา (ขึ้น `-dirty-` เฉพาะเมื่อไฟล์โปรเจกต์ที่ติดตามหรือไฟล์ใหม่เปลี่ยน; `.kit-state/`, `resources.env`, `app.env`, `secrets.map` ไม่นับ) แล้วเก็บ digest ที่แก้ไขไม่ได้ไว้ใน `.kit-state/`

**5) Deploy**
```sh
./project-kit/kit.sh deploy
./project-kit/kit.sh status      # ดู URL
./project-kit/kit.sh open        # เปิดในเบราว์เซอร์
```
`deploy` จะรัน migration ก่อน (ถ้าตั้ง `MIGRATE_COMMAND`) ถ้า migration ล้มเหลวจะ **หยุดและไม่ deploy** แล้วบอกวิธีดู log

> ทุกคำสั่งใส่ `--dry-run` ได้ เพื่อ **ดูคำสั่งที่จะรันโดยไม่รันจริง** — แนะนำให้ลองก่อนเสมอ เช่น `./project-kit/kit.sh --dry-run deploy`

## คำสั่งทั้งหมด

| คำสั่ง | ทำอะไร |
|---|---|
| `doctor` | ตรวจ gcloud/docker/ล็อกอิน/สิทธิ์/ทรัพยากร |
| `init` | สร้าง Dockerfile ตัวอย่างตาม `--stack` |
| `build [--tag T] [--dockerfile F] [--context DIR]` | build + push + เก็บ digest |
| `migrate [--image REF]` | รัน migration job อย่างเดียว |
| `deploy [--skip-migrate] [--image REF] [--replace-env]` | migrate แล้ว deploy |
| `env list` / `env set K=V [--job]` / `env unset K [--job]` | ดู/ตั้ง/ลบ env (แสดงเฉพาะชื่อ) |
| `secrets` | ดู secret ที่อ่านได้และที่ map ไว้ (ไม่แสดงค่า) |
| `secrets list` / `secrets add <1-5> [--from-stdin\|--from-file F]` / `secrets map <ENV_NAME> <1-5>` | จัดการ slot secret ของกลุ่ม `<prefix>-app-secret-1..5` สำหรับ API key ของตัวเอง |
| `logs [service\|job] [--severity ERROR] [--limit 100] [--since 2h] [--follow]` | อ่าน log |
| `status` | URL, revision, image, ชื่อ env, ผล job ครั้งล่าสุด |
| `open` | เปิดเว็บ |
| `rollback [--to REVISION]` | ย้าย traffic ไป revision ก่อนหน้าที่ **พร้อมใช้งาน** (หลังจากนั้น traffic ถูกตรึงไว้ที่ revision นั้น; `deploy` จะย้ายกลับไปล่าสุด) |

flags ทั่วไป: `--dry-run`, `--yes`, `--env-file`, `--app-env`, `--secrets-map`, `--stack`, `--allow-min-instances`, `--allow-plain NAME`, `--lang en|th`

ข้อความที่แสดงจะใช้คำสั่งตามที่คุณเรียก (เช่น `./project-kit/kit.sh deploy`)

### ภาษาของข้อความจาก kit.sh

`kit.sh` และ `from-portal-json.sh` แสดงข้อความได้ 2 ภาษา (อังกฤษ/ไทย) เลือกตามลำดับนี้:
1. flag `--lang en` หรือ `--lang th`
2. ตัวแปร `KIT_LANG=en` หรือ `KIT_LANG=th`
3. ถ้า `LC_ALL` / `LC_MESSAGES` / `LANG` ขึ้นต้นด้วย `th` ใช้ภาษาไทย
4. นอกนั้นใช้ **ภาษาอังกฤษ** (ค่าเริ่มต้น)

ตัวอย่าง: `./project-kit/kit.sh --lang th doctor` หรือ `export KIT_LANG=th`
คำที่ต้องพิมพ์เพื่อยืนยันเหมือนกันทั้งสองภาษา: ตอบ `y` หรือ `yes` สำหรับคำถาม [y/N] และพิมพ์คำว่า `replace` (ภาษาอังกฤษ) สำหรับ `deploy --replace-env`
ส่วนคำสั่ง gcloud/docker ที่แสดงตอน `--dry-run` เหมือนกันทุกภาษา

## Windows

- **ใช้ WSL (แนะนำ) หรือ Git Bash** ใน WSL (Ubuntu) ติดตั้ง gcloud และ Docker Desktop แบบเปิด WSL integration และเก็บโปรเจกต์ไว้ใน home ของ Linux (เช่น `~/myproject`) ไม่ใช่ใต้ `/mnt/c` Git Bash ใช้ได้เหมือนกัน แต่ WSL มีเรื่องน่าปวดหัวน้อยกว่า PowerShell และ `cmd` รัน `kit.sh` ไม่ได้
- **ต้องมี python3** เฉพาะสำหรับ `from-portal-json.sh` บน Windows คำสั่ง `python3` อาจเป็นทางลัด Microsoft Store ที่ไม่ทำอะไร สคริปต์จะตรวจเจอและบอกให้ติดตั้ง Python จาก https://www.python.org/downloads/ (ติ๊ก "Add python.exe to PATH") หรือปิด App execution aliases
- **"permission denied"**: zip อาจทำให้สิทธิ์ execute หายตอนแตกไฟล์ (เช่น Finder บน macOS หรือโปรแกรมแตกไฟล์บางตัวบน Windows) ให้รัน `chmod +x project-kit/*.sh` หรือรันผ่าน bash: `bash project-kit/kit.sh doctor`
- **ขึ้นบรรทัดใหม่ (line endings)**: `kit.sh` ต้องเป็นแบบ LF ถ้า Git หรือ editor แปลงเป็น CRLF การรัน `./project-kit/kit.sh` จะเจอ `env: bash\r: No such file or directory` หรือ `bad interpreter: /usr/bin/env bash^M` (ถ้ารันแบบ `bash project-kit/kit.sh` อาจเจอ `set: pipefail: invalid option name` หรือ kit.sh หยุดพร้อมข้อความ "Windows line endings") วิธีแก้: `dos2unix project-kit/*.sh` หรือ `sed -i 's/\r$//' project-kit/*.sh` (บน macOS: `sed -i '' 's/\r$//' project-kit/*.sh`) และตรวจว่า `.gitattributes` มี `*.sh text eol=lf` kit มีไฟล์ `.gitattributes` (`*.sh text eol=lf`) กัน Git แปลงให้ ให้เก็บไว้ใน `project-kit/` (หรือคัดลอกบรรทัดนั้นไปไว้ใน `.gitattributes` ของ repo) และใน Git for Windows ให้รัน `git config core.autocrlf input` ก่อน clone หรือ add kit
- **Git Bash แปลง path** (เคล็ดลับที่ยังไม่ได้ยืนยัน): Git Bash อาจแก้อาร์กิวเมนต์ที่ขึ้นต้นด้วย `/` (เปลี่ยน `/cloudsql/...` เป็น path แบบ Windows) kit.sh ไม่ต้องใช้อาร์กิวเมนต์แบบนั้น แต่ถ้าคำสั่ง gcloud ของคุณเองพังเพราะเรื่องนี้ ให้ใส่ `MSYS_NO_PATHCONV=1` นำหน้า เช่น `MSYS_NO_PATHCONV=1 gcloud ...`

## FAQ

**เปลี่ยน env ของแอปอย่างไร**
- ค่าที่ไม่ลับ (เช่น `LOG_LEVEL`, `TZ`) แก้ไฟล์ `app.env` (คัดลอกจาก `app.env.example`) แล้ว `./project-kit/kit.sh deploy`
- หรือแก้เร็วๆ: `./project-kit/kit.sh env set LOG_LEVEL=debug` (ใส่ `--job` ถ้าให้ migrate job ใช้ด้วย) / `./project-kit/kit.sh env unset LOG_LEVEL`
- การ deploy ปกติใช้โหมด **เพิ่ม/อัปเดตเฉพาะตัวที่ระบุ** — env ตัวอื่น (รวมถึง `DATABASE_URL` ที่ portal ตั้งให้) จะไม่หาย
- `deploy --replace-env` จะ **แทนที่ทั้งหมด** และต้องพิมพ์ยืนยันเอง ใช้เมื่อรู้ว่ากำลังทำอะไรเท่านั้น
- ตั้ง `PORT` ใน `app.env` ไม่ได้ (Cloud Run กำหนดเอง) — ตั้งใน `resources.env`
- ค่าที่อยู่ในเครื่องหมายคำพูด: ใช้ single quote (`'...'`) หรือ double quote ได้ แต่ backslash escape เช่น `\"` ภายในค่า **ไม่รองรับ** ค่าจะถูกอ่านถึงเครื่องหมายคำพูดตัวถัดไป
- การอ่านไฟล์ผ่อนปรน: BOM, ขึ้นบรรทัดแบบ Windows, ช่องว่างท้ายบรรทัด และ `# comment` ท้ายค่า (เว้นวรรค + `#`) จะถูกข้าม ถ้าบรรทัดผิดจะบอกชื่อไฟล์กับเลขบรรทัดเท่านั้น (ไม่พิมพ์ข้อความของบรรทัดนั้น)
- **ค่า env ถูกปิดบังในทุกอย่างที่ kit.sh พิมพ์**: คำสั่งใน `--dry-run` และตอนรันจริงจะแสดง `--update-env-vars '^@^LOG_LEVEL=***'` ไม่แสดงค่า
- **kit.sh ปฏิเสธชื่อและค่าที่ดูเหมือนความลับ** ใน `app.env` และ `env set` กติกาที่แน่นอน:
  - **ชื่อ**: แยกชื่อด้วย `_` แล้วตรวจทีละคำ (ไม่ใช้การหาสตริงย่อย จึงผ่านได้: `AUTHOR_NAME`, `PASSPORT_STRATEGY`, `MONKEY_MODE`, `NEXTAUTH_URL`, `AUTH_TRUST_HOST`) ชื่อจะถูกปฏิเสธถ้ามีคำเต็มเหล่านี้: `SECRET`, `PASSWORD`, `PASSWD`, `PWD`, `PASS`, `CREDENTIAL`, `CREDENTIALS`, `SIGNATURE`, `DSN`; `TOKEN` (ยกเว้นคำถัดไปเป็น `EXPIRE...`, `TTL`, `MINUTES`, `SECONDS`, `HOURS`, `DAYS`, `ROUNDS`, `TYPE`, `URL`, `HOST`, `NAME` จึงผ่าน `ACCESS_TOKEN_EXPIRE_MINUTES`); `PRIVATE_KEY`; `DATABASE_URL`; `CONNECTION_STRING`; `KEY` เมื่อเป็นคำสุดท้ายหรืออยู่ใน `API_KEY`, `SECRET_KEY`, `ACCESS_KEY`, `AUTH_KEY` (`STRIPE_KEY`, `OPENAI_API_KEY` ถูกปฏิเสธ แต่ `PUBLIC_KEY_URL` ผ่าน); และ `AUTH` คำเดียว ชื่อที่ลงท้ายด้วย `_URL`, `_HOST`, `_PORT`, `_ROUNDS`, `_MINUTES`, `_SECONDS`, `_TTL`, `_NAME`, `_ID`, `_ENABLED`, `_MODE`, `_LABEL`, `_DIR` หรือ `_PATH` จะข้ามเฉพาะกฎ `KEY` / `AUTH` (`GOOGLE_CLIENT_ID`, `KEYCLOAK_URL` ผ่าน ส่วน `GOOGLE_CLIENT_SECRET` ถูกปฏิเสธ)
  - **ค่า**: ปฏิเสธเฉพาะสัญญาณที่ชัดเจน: ค่าที่ขึ้นต้นด้วย `sk-`, `sk_live_`, `sk_test_`, `AIza`, `ghp_` / `gho_` / `ghu_` / `ghs_` / `ghr_`, `github_pat_`, `xox?-` หรือ `AKIA` / `ASIA` ตามด้วยตัวอักษรหรือเลข 16 ตัว; ค่าที่มี `-----BEGIN` หรือ JWT (`eyJ...` `.` `eyJ...` `.`); หรือสตริงสุ่มเอนโทรปีสูง คือยาว 32 ตัวขึ้นไปจาก `A-Za-z0-9+/=_-` ที่มีทั้งตัวเลขและตัวอักษร และเป็นตัวพิมพ์เล็กใหญ่ปนกันหรือยาว 40 ตัวขึ้นไป **ไม่นับ** เป็นสตริงสุ่ม: path (ขึ้นต้นด้วย `/` หรือเป็นท่อนตัวพิมพ์เล็กคั่นด้วย `/`), URL, slug ที่เป็นคำตัวพิมพ์เล็กตั้งแต่ 3 คำขึ้นไปต่อกันด้วย `-` หรือ `_` (เช่น `cpe-se-course-2026-team-abc-uploads-bucket`) และ git SHA แบบ hex 40 ตัว ค่าทั่วไปอย่าง `/var/lib/myapp/uploads/public/images` หรือ `REGION_LABEL=ASIA-SE` ผ่านได้
  - ข้อความ error บอกเฉพาะชื่อตัวแปร (ไม่แสดงค่า) และแนะนำให้ใช้ `secrets add` กับ `secrets map`
  - **เตือนผิดใช่ไหม ให้อนุญาตเอง**: ใช้ flag `--allow-plain NAME` (ใส่ซ้ำได้หลายชื่อ เช่น `./project-kit/kit.sh --allow-plain MY_TOKEN_LABEL env set MY_TOKEN_LABEL=abc`) หรือใส่บรรทัด `ALLOW_PLAIN=NAME1,NAME2` ใน `app.env` หรือ `resources.env` ทั้งสองแบบจะข้ามการตรวจชื่อและค่าเฉพาะชื่อที่ระบุ แต่ค่ายังถูกปิดบังในทุกอย่างที่ kit.sh พิมพ์ อย่าใช้กับความลับจริง
- **หลัง `rollback` traffic จะถูกตรึงไว้ที่ revision เดียว** `env set` / `env unset` จะสร้าง revision ใหม่ที่ได้ traffic 0% และ kit.sh จะแสดงคำเตือน ให้รัน `./project-kit/kit.sh deploy` (ย้าย traffic ไป revision ล่าสุด) หรือ `gcloud run services update-traffic <service> --to-latest --project <project> --region <region>`

**ใช้รหัสผ่าน / API key อย่างไร** — ห้ามใส่ใน env, `app.env`, โค้ด หรือ git ให้ใช้ secret slot ของกลุ่ม:
portal สร้าง slot ว่างให้กลุ่มไว้ 5 ช่อง ชื่อ `<prefix>-app-secret-1` ถึง `-5` คุณมีสิทธิ์ "เพิ่ม version" และ "อ่าน" เฉพาะ 5 ช่องนี้ (สร้าง secret ใหม่เอง, ปิด/ลบ version, หรือแตะ secret อื่นไม่ได้)
1. `./project-kit/kit.sh secrets list` — ดูสถานะของแต่ละ slot สถานะมาจากการลองเข้าถึง (`gcloud secrets versions access latest` เพราะสมาชิกไม่มีสิทธิ์ list version) ผลลัพธ์ของการลองถูกทิ้งทันที จึงไม่แสดงค่าเด็ดขาด `มีค่าแล้ว` = ลองเข้าถึงสำเร็จ, `พร้อมใช้/ว่าง` = slot มีอยู่แต่ยังไม่มี version (ใช้ `secrets add` กับ slot ว่างได้), `ไม่มีสิทธิ์ หรือยังไม่ได้สร้างให้กลุ่มคุณ` = ถูกปฏิเสธสิทธิ์ ให้ถาม TA, `version ล่าสุดถูกปิด/ทำลายแล้ว (DISABLED/DESTROYED)` = TA ปิดหรือทำลาย version ล่าสุด ให้รัน `secrets add N` เพื่อเพิ่มค่าใหม่ (version ใหม่จะกลายเป็นตัวล่าสุด), `ข้อผิดพลาดที่ไม่รู้จัก` = แสดงบรรทัดแรกของ error
2. `./project-kit/kit.sh secrets add 1` — พิมพ์ค่าแบบซ่อน (ไม่แสดงบนจอ ไม่ลง history ไม่เขียนลงไฟล์) หรือส่งทาง pipe: `printf '%s' "$VALUE" | ./project-kit/kit.sh secrets add 1 --from-stdin` หรือ `--from-file ไฟล์` (kit.sh ไม่รับค่าเป็นอาร์กิวเมนต์เด็ดขาด) ทั้ง `--from-stdin` และ `--from-file` จะ **ตัดขึ้นบรรทัดใหม่ท้ายค่าและ carriage return ท้ายค่า 1 ตัวออก** (ค่าที่เซฟจากโปรแกรมแก้ไข `echo` หรือ Notepad ของ Windows (CRLF) จึงไม่มีตัวอักษรล่องหนติดท้าย) ช่องว่างหน้า/หลังค่ายังคงอยู่
3. `./project-kit/kit.sh secrets map MY_API_KEY 1` — เพิ่มบรรทัด `MY_API_KEY=grp01-app-secret-1:latest` ใน `secrets.map`
4. `./project-kit/kit.sh deploy` — แอปอ่านได้ทาง `process.env.MY_API_KEY` / `os.environ["MY_API_KEY"]`

ข้อควรรู้
- **ค่าที่ใส่แล้ว นักศึกษาอ่านกลับจากเว็บ/Cloud Console ไม่ได้** (portal ไม่แสดงค่า secret) จดค่าจริงไว้ที่แหล่งของคุณเองเสมอ (เช่น หน้า API key ของผู้ให้บริการ)
- **เปลี่ยนค่า (rotate) = add version ใหม่** (`./project-kit/kit.sh secrets add N` อีกครั้ง) version เก่าไม่ถูกลบ แอปที่ใช้ `:latest` จะได้ค่าใหม่เมื่อ deploy/สร้าง revision ใหม่
- **อย่าส่งค่าความลับในแชตกลุ่มหรือแชต AI**
- ถ้า `secrets list` ขึ้นว่า `ไม่มีสิทธิ์ หรือยังไม่ได้สร้างให้กลุ่มคุณ` แปลว่า slot ของกลุ่มยังไม่ถูกสร้าง (หรือไม่ใช่ของกลุ่มคุณ) ให้ถาม TA ส่วน slot ว่าง (`พร้อมใช้/ว่าง`) เป็นเรื่องปกติ รัน `secrets add` ได้เลย

`./project-kit/kit.sh secrets` (ไม่มีคำสั่งย่อย) ดู secret ที่ map ไว้และอ่านได้ (ไม่แสดงค่า) kit.sh จะปฏิเสธ env ที่ชื่อมี `KEY`, `PASSWORD`, `SECRET`, `TOKEN` ฯลฯ และค่าที่ดูเหมือนความลับ (ดูด้านบน)

ถ้า `secrets.map` มีบรรทัดผิด error จะแสดงเฉพาะเลขบรรทัดกับชื่อ ENV ไม่แสดงค่า

**รัน migration อย่างไร** — ตั้งใน `resources.env` เช่น
`MIGRATE_COMMAND=npx prisma migrate deploy` / `alembic upgrade head` / `python manage.py migrate` / `/app/server migrate`
คำสั่งนี้รัน **ใน image ของคุณ** โดยมี env/secret/Cloud SQL เดียวกับ service ถ้าคำสั่งไม่มีไวยากรณ์ shell (ไม่มีเครื่องหมายคำพูด, `$`, `;`, `&`, `|`, `<`, `>`, `()`, `{}`, `*`, `?`, `~`, `#`, `!`, backslash และไม่ขึ้นต้นด้วย `VAR=ค่า`) จะถูกเรียกตรงๆ (exec-style ใช้ได้แม้ image ไม่มี shell) ไม่เช่นนั้นจะรันผ่าน `sh -c` ซึ่ง image ต้องมี shell
รันเดี่ยวๆ: `./project-kit/kit.sh migrate`  — ไม่ต้อง migrate (เช่น เว็บ static) ก็เว้นว่างไว้ แล้ว `deploy` จะข้ามให้
(Spring/Flyway ที่ migrate ตอนสตาร์ตแอปอยู่แล้วก็เว้นว่างได้)

**ดู log อย่างไร** — `./project-kit/kit.sh logs` (service), `./project-kit/kit.sh logs job` (migration), `--severity ERROR`, `--since 30m`, `--follow` (ติดตามสด หยุดเองใน 15 นาที ถ้า gcloud ผิดพลาดจะพิมพ์ error และหยุดเมื่อพลาด 3 ครั้งติดกัน) `--severity` รับ DEFAULT, DEBUG, INFO, NOTICE, WARNING, ERROR, CRITICAL, ALERT หรือ EMERGENCY

**แอปเชื่อมฐานข้อมูลอย่างไร** — service/job ถูกผูกกับ Cloud SQL และมี secret `DATABASE_URL` แนบไว้แล้ว (ผ่านซ็อกเก็ต `/cloudsql/...` ไม่ใช่ TCP) ให้แอปอ่าน `DATABASE_URL`
รูปแบบ URL ที่ portal เตรียมเป็นแบบ `postgresql://user:***@localhost/db?host=/cloudsql/...&schema=public&connection_limit=3` (สไตล์ Prisma) — ไลบรารีบางตัว (เช่น SQLAlchemy/psycopg2, JDBC, Go pq) อ่านพารามิเตอร์ `schema`/`connection_limit` ไม่ได้ ให้ตัดพารามิเตอร์พวกนั้นทิ้งในโค้ด หรือขอ TA ทำ secret อีกรูปแบบ

**ต่อฐานข้อมูลจากเครื่องตัวเอง (Cloud SQL Auth Proxy)**
```sh
gcloud auth application-default login
# ดาวน์โหลด cloud-sql-proxy: https://cloud.google.com/sql/docs/postgres/sql-proxy
cloud-sql-proxy cpe-se-course-2026:asia-southeast1:grp01-pg --port 5433
psql "host=127.0.0.1 port=5433 user=grp01 dbname=grp01"
```
สิทธิ์ของคุณคือ Cloud SQL Client (เชื่อมต่อได้) แต่ **อ่านรหัสผ่านฐานข้อมูลเองไม่ได้** (secret `database-url`/`database-password` ใช้ได้เฉพาะตัวแอป) ถ้าอยากต่อจากเครื่อง ให้ถาม TA เรื่องวิธีรับรหัสผ่านอย่างปลอดภัย หรือรันงานฐานข้อมูลผ่าน migrate job แทน
ชื่อ user/database ปกติคือ prefix ของกลุ่ม (ตรวจในแท็บ Team resources)

**ย้อนกลับเมื่อ deploy พัง** — `./project-kit/kit.sh rollback` (ย้าย traffic ไป revision ก่อนหน้าที่พร้อมใช้งาน revision ที่ล้มเหลวจะถูกข้าม) หมายเหตุ: **ไม่ย้อน migration/ข้อมูลในฐานข้อมูล** หลัง rollback traffic จะถูก **ตรึง** ไว้ที่ revision นั้น revision ใหม่ (รวมถึงที่เกิดจาก `env set` / `env unset`) จะได้ 0% จนกว่าจะรัน `./project-kit/kit.sh deploy` ซึ่งจะย้าย traffic กลับไป revision ล่าสุด

**ไม่ใช้ Docker บนเครื่องได้ไหม** — kit นี้ build ด้วย Docker ในเครื่อง ถ้าติดตั้งไม่ได้ให้ถาม TA (สิทธิ์ของคุณไม่รวม Cloud Build)

**เปลี่ยนขนาด/พอร์ต** — `CPU`, `MEMORY`, `MAX_INSTANCES`, `PORT` ใน `resources.env` เครดิตใช้ร่วมกันประมาณ 38 กลุ่ม kit.sh จึงกำหนดเพดาน: `CPU` ไม่เกิน 2, `MEMORY` ไม่เกิน 2Gi, `MAX_INSTANCES` 1-3 และ `MIN_INSTANCES` ต้องเป็น 0 ถ้าต้องการให้มี instance รันค้าง (`MIN_INSTANCES` มากกว่า 0) ต้องได้รับอนุญาตจาก TA แล้วเพิ่ม flag `--allow-min-instances` (เช่น `./project-kit/kit.sh --allow-min-instances deploy`) และ kit.sh จะถามยืนยัน

### สิ่งที่ทำ "ไม่ได้" และต้องถามใคร

| ต้องการ | ทำเองได้ไหม | ถามใคร |
|---|---|---|
| สร้าง/แก้/ลบ secret ใหม่ | ไม่ได้ (อ่านได้อย่างเดียว) | TA / portal |
| ตั้งค่า/สร้าง/ขยาย Cloud SQL (เพิ่มเครื่อง, instance ที่ 2, เปลี่ยน tier) | ไม่ได้ | TA |
| แก้ IAM, สร้าง service account, สร้าง service/โปรเจกต์ใหม่ | ไม่ได้ | TA |
| ดู/แตะ resource ของกลุ่มอื่น | ไม่ได้ (และ kit.sh จะปฏิเสธ) | — |
| ลืมรหัสผ่านแอป/ต้องการรหัสผ่านฐานข้อมูล | อ่าน `admin-password`/`demo-password` ได้ผ่าน `gcloud secrets versions access` (ระวังอย่าแปะผลลัพธ์ที่ไหน) | TA |
| เชื่อม GitHub / ใช้ GitHub Actions | ไม่บังคับ | TA เปิด WIF ให้ (ดู `templates/deploy.github-actions.example.yml`) |
| โดเมนของตัวเอง, ขยายโควตา/เครดิต | ไม่ได้ | TA |

ถ้าติดปัญหา: รัน `./project-kit/kit.sh doctor` แล้วส่งผลลัพธ์ให้ TA (**ห้ามแนบรหัสผ่านหรือค่าใน secret**)

## แก้ปัญหาเบื้องต้น (Troubleshooting)

| อาการ | สาเหตุและวิธีแก้ |
|---|---|
| `doctor` บอกว่ายังไม่ได้ล็อกอิน gcloud | รัน `gcloud auth login` และเลือก Gmail ที่ลงทะเบียนไว้ใน portal (ตรวจด้วย `gcloud auth list`) |
| `doctor` ไม่ผ่านหรือเจอ resource ไม่ตรงกลุ่ม | ตรวจ `PREFIX`, `PROJECT_ID`, `REGION` ใน `resources.env` ให้ตรงกับแท็บ Team resources; ตรวจว่าใช้ gcloud project ถูก (kit.sh ส่ง `--project` ให้เองทุกคำสั่ง) ถ้ายังไม่หาย ให้ถาม TA |
| `permission denied` / `PERMISSION_DENIED` ตอนใช้คำสั่งแบบ list (เช่น `gcloud run services list`) | สิทธิ์ของนักศึกษาจำกัดเฉพาะ resource ของกลุ่ม คำสั่ง list ทั้งโปรเจกต์ใช้ไม่ได้เป็นปกติ ให้ใช้ `./project-kit/kit.sh status` / `./project-kit/kit.sh doctor` ที่เรียกเฉพาะชื่อ resource ของกลุ่มแทน |
| Mac Apple Silicon (M1/M2/M3): image รันบน Cloud Run ไม่ได้ / ขึ้น platform ผิด | kit.sh build ด้วย `--platform linux/amd64` ให้แล้ว อย่า build ด้วย `docker build` ธรรมดา และต้องมี Docker Desktop ที่เปิดอยู่พร้อม `docker buildx` (build ครั้งแรกอาจช้าเพราะต้องจำลอง amd64) |
| `secrets add` ขึ้นว่าไม่มี terminal | การพิมพ์ค่าแบบซ่อนต้องรันใน terminal จริง ถ้ารันผ่านสคริปต์/IDE ที่ไม่มี terminal ให้ใช้ `--from-stdin` (pipe) หรือ `--from-file ไฟล์` แทน |
| ขึ้นข้อความภาษาที่ไม่ต้องการ | ใส่ `--lang en` หรือ `--lang th` หรือตั้ง `KIT_LANG` |

## คำเตือนสำคัญ

- **ห้ามใส่ความลับใน env / app.env / โค้ด / git / แชต AI** (รหัสผ่าน, token, API key, DATABASE_URL จริง) — ใช้ `secrets.map` เท่านั้น
  ไฟล์ `resources.env`, `app.env`, `secrets.map` ไม่ควร push ขึ้น git สาธารณะ (มีใน `.dockerignore` ตัวอย่างแล้ว)
- **ฐานข้อมูล: 1 instance ต่อกลุ่มเท่านั้น** ห้ามขอ/สร้างเพิ่ม ใช้หลาย database/schema ใน instance เดิมถ้าจำเป็น (ถามกรณี TA)
- **เครดิตเป็นของส่วนกลาง ใช้ร่วมกันทั้งวิชา** — service ถูกตั้งค่าเริ่มต้นเป็น `min-instances 0`, `max-instances 1` (ไม่มีคนใช้ = ไม่คิดเงิน)
  อย่าตั้ง min-instances > 0 (kit.sh ปฏิเสธถ้าไม่ใส่ `--allow-min-instances`) / CPU/memory สูง (kit.sh จำกัดที่ 2 CPU และ 2Gi) / ยิง load test โดยไม่ขออนุญาต Cloud SQL คิดเงินตลอดเวลาแม้ไม่มีคนใช้
- **ห้ามลบ resource** (service, job, instance, repo, secret) แม้จะรู้สึกว่าไม่ใช้ — สร้างใหม่ไม่ได้ด้วยตัวเอง ต้องรอ TA
- image ที่ push ขึ้นไปสะสมจะกินพื้นที่/เงินเล็กน้อย อย่า build ถี่โดยไม่จำเป็น
- service เป็น **public** ใครก็เข้า URL ได้ อย่าเปิดเผยข้อมูลส่วนตัวใน endpoint โดยไม่มีระบบ login
- kit.sh จะ **ปฏิเสธทุกคำสั่ง** ที่ชื่อ resource ไม่ขึ้นต้นด้วย `PREFIX` ของกลุ่ม และไม่แสดงค่าใน secret

## โครงสร้างไฟล์

```
project-kit/
  README.md                 คู่มือภาษาอังกฤษ (English)
  README.th.md              คู่มือภาษาไทย (ไฟล์นี้)
  kit.sh                    คำสั่งหลัก
  from-portal-json.sh       แปลง <prefix>-resources.json (หรือ lab5-<prefix>-handoff.json) จาก portal -> resources.env
  resources.env             (มีเฉพาะใน zip จาก portal) ข้อมูลทรัพยากรของกลุ่ม กรอกให้แล้ว
  resources.example.env     ตัวอย่างของ resources.env (ใช้เมื่อต้องสร้างเอง)
  app.env.example           env ธรรมดา (คัดลอกเป็น app.env)
  secrets.map.example       map ENV -> secret ที่มีอยู่ (คัดลอกเป็น secrets.map)
  templates/                Dockerfile ตัวอย่าง (node/python/go/java/static), .dockerignore, GitHub Actions (ไม่บังคับ)
  .gitattributes            ให้ไฟล์ *.sh ใช้ขึ้นบรรทัดแบบ LF (สำหรับ Windows)
```

zip จาก portal มีเฉพาะไฟล์ข้างต้น (กับ `resources.env` ที่กรอกให้แล้ว) ชุดทดสอบออฟไลน์อยู่ใน repo ของวิชาและ **ไม่ได้อยู่ใน zip**

ไฟล์ config (`resources.env`, `app.env`, `secrets.map`) ถูกหาที่โฟลเดอร์ปัจจุบันก่อน แล้วค่อยหาในโฟลเดอร์ของ kit (หรือชี้เองด้วย `--env-file`, `--app-env`, `--secrets-map`; path ที่ระบุแต่ไม่มีไฟล์จะเป็น error)
