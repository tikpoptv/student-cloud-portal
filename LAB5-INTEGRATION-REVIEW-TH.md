> **HISTORICAL source audit (19 November 2026)** written before live activation was built; where it says the provisioner or live activation is missing, see LIVE-ACTIVATION.md for the current state.

> Current release: real activation is enabled through a private provisioner and persistent PostgreSQL. See [LIVE-ACTIVATION.md](LIVE-ACTIVATION.md) for current state and evidence; preview-only notes below describe earlier milestones.

# ผลตรวจขอบเขต Student Cloud Portal เทียบ Lab 5

ตรวจวันที่ 19 พฤศจิกายน 2569 จากต้นฉบับใน Downloads:

- 01_SE_Lab_5_updated.pdf: ข้อ 4 Required Work, ข้อ 5 Recommended Practices, rubric 30/20/35/15
- 03_Student-Guide-GCP-Deployment-and+CI+CD-V1_1.pdf: Episode 5.0–5.8, 6.1–6.7, 7–10
- 02_lab5-starter-kit.zip: README, deploy/deploy.sh, deploy/release.sh, workflows/deploy.yml และ ci-docker.yml (อ่านจาก zip โดยตรง ไม่ใช้ repo นักศึกษามาแทนต้นฉบับ)
- ประกาศโปรเจกต์กลาง cpe-se-course-2026 ที่ผู้ใช้ให้มา: ใช้เป็นการปรับวิธีเข้าถึง GCP แทนการสมัคร trial รายกลุ่ม ส่วนวันส่งใน PDF เก่าไม่ใช้แทนประกาศใหม่

## ข้อสรุป

แนวทาง portal เหมาะกับการจัด infrastructure ของโปรเจกต์กลาง แต่เป็นการปรับจากคู่มือ ต้องมีคู่มือเสริมสำหรับ shared project และบันทึกส่วนที่ระบบทำให้ใน deployment.md พร้อมยืนยันกับผู้สอน ไม่มีข้อกำหนดบังคับให้นักศึกษาทุกกลุ่มมี Owner ของโปรเจกต์กลาง

ข้อกำหนดที่ยังต้องทำครบ: Docker จาก clean clone, configuration ผ่าน environment, ไม่เปิดเผย secrets, แอป GCP URL ใช้งาน UI/API/DB ได้, persistence หลัง restart/redeploy, CI ทุก PR และ required check, reviewed staging→main release, pipeline ระบุ commit ที่รันได้ และสมาชิกทั้งสองมีส่วนร่วม Portal ทำสิ่งเหล่านี้แทนทั้งหมดไม่ได้

ตอนนี้ระบบยังเป็น preview: ไม่ได้เปิด API สร้าง SQL หรือผูก IAM/WIF ใดจริง จึงยังรับรองว่า “เปิดทรัพยากรถูกต้องแล้ว” ไม่ได้

## เราเข้าไปแทรกตรงไหน

| จุดในคู่มือ | ผู้รับผิดชอบในแบบ portal | สิ่งที่ต้องคงไว้/ปรับ |
|---|---|---|
| Episode 1 | รายวิชาดูแล project/billing กลาง | นักศึกษาใช้ Gmail ที่ลงทะเบียน ไม่สร้าง project ใหม่ในขั้นตอนนี้ |
| Episode 2–4 | นักศึกษา | ปรับแอป, Docker, tests, CI, PR/review ตามเดิม |
| 5.0–5.2 | นักศึกษา + portal แสดงแผน | นักศึกษายังปรับ stack และอ่าน dry-run แต่ต้องอ่าน shared-project deployment plan ไม่ใช่รัน privileged deploy.sh |
| 5.3: deploy.sh ขั้น 1–8 | Portal/TA | เปิด API, Registry, SQL instance, database, runtime SA, DB user, DB URL secret, admin/demo secrets ตามที่แอปต้องการ, secret IAM |
| 5.4 | Portal/TA | ปิด SQL storage auto-increase ตั้งแต่สร้าง; ให้นักศึกษาตรวจค่าที่ระบบเตรียม |
| 5.3: deploy.sh ขั้น 9–11 | นักศึกษาใช้สคริปต์สำหรับ shared project | build/push image → ตั้ง migration job ตาม stack และ execute → update service; IAM/public access ครั้งแรกและ resource skeleton ทำโดย portal |
| 5.5–5.8 | นักศึกษา | health/readiness, smoke, ลองใช้แอป, รับ app-admin password เฉพาะกลุ่มอย่างเป็นส่วนตัว, ตรวจ resource และเก็บหลักฐาน |
| 6.1 | นักศึกษาแจ้ง repo; ระบบตรวจ GitHub IDs | ขอ owner/repo ที่ถูกต้องและตรวจ immutable IDs ฝั่ง server; public repo ตาม Lab |
| 6.2–6.3 | Portal/TA | deployer + WIF เฉพาะ repo/main/workflow/environment ของทีม |
| 6.4–6.7 | นักศึกษา | GitHub environment/variables, required check, passing/failing PR และ review ตามเดิม |
| Episode 7–8 | นักศึกษา | auto deploy, smoke, SHA/digest, persistence, rollback ตามข้อกำหนดและข้อแนะนำ |
| Episode 9–10 | Portal/TA สำหรับ pause/cleanup | ยังต้องมีวิธี pause/resume และขอ cleanup หลังตรวจงาน อย่ารัน teardown.sh เดิมในโปรเจกต์กลาง |

หมายเลขขั้น 1–11 ข้างบนคือ comment ใน deploy.sh; ในคู่มือ 5.2 ย่อเป็น 8 รายการซึ่งไม่ใช่เลขเดียวกัน

## ทรัพยากรที่ต้องเตรียมจริง

1. API ที่ script ใช้: run.googleapis.com, sqladmin.googleapis.com, artifactregistry.googleapis.com, secretmanager.googleapis.com, iam.googleapis.com; WIF ต้อง iamcredentials.googleapis.com และ sts.googleapis.com ด้วย เปิดเป็นงานส่วนกลางครั้งเดียว หากยังใช้ Cloud Build ในเส้นทางที่เลือกจึงเปิด cloudbuild.googleapis.com และจัด build identity แยก ไม่ให้ broad shared builder
2. Registry ของกลุ่ม, SQL PostgreSQL 16 Enterprise db-f1-micro ตาม reference เมื่อ quota/region รองรับ, disk 10GB และ auto-increase off, database และ DB user ของกลุ่ม ข้อจำกัด resource/credit ต้องตรวจจริงก่อนเปิด 36 ทีม
3. Runtime SA แยกกลุ่ม; database connection string ต้องตรง driver ไม่ใช่ใช้ Prisma URL กับทุก stack. ไม่เก็บ URL ที่มี password ใน handoff
4. Secret DATABASE_URL และ bootstrap admin/demo secrets ตามความต้องการของแต่ละแอป ตัว reference มี admin-password และ demo-password แบบ optional --demo; แอปอื่นอาจต้องชื่อต่างกัน ไม่ควรเปิดจำนวน secret ตายตัวให้ทุก stack
5. Cloud Run service และ migration job ที่มีอยู่แล้วเพื่อให้สิทธิ์ระดับ resource. ระยะแรกใช้ placeholder ที่ปลอดภัยและไม่สามารถรันโค้ดนักศึกษาด้วยสิทธิ์ provisioner; placeholder ไม่เท่ากับ deploy สำเร็จ
6. Service configuration สำหรับแอปจริงต้องได้ port, env, secret mappings, health endpoint, CPU/memory/scaling และ SQL connection จากนักศึกษาหรือการตั้งค่าที่ตรวจแล้ว นักศึกษาตั้ง command/args ของ migration/seed ด้วย identity จำกัดของทีมก่อน release ครั้งแรก
7. TA ตั้ง public invoker ของแอปเมื่อเหมาะสม (ไม่เปิด migration job ให้ allUsers), runtime/deployer binding และ WIF ให้สำเร็จก่อน handoff พร้อมทดสอบ cross-team denials

SQL Client ต้อง conditional เฉพาะ instance ของทีม; runtime Secret Accessor เฉพาะ secret ตัวเอง; deployer Cloud Run Developer เฉพาะ service/job ตัวเอง, Artifact Registry Writer เฉพาะ repo ตัวเอง, SA User เฉพาะ runtime ตัวเอง และ job execution permission ที่จำเป็น ให้สิทธิ์ read logs ผ่าน view ที่จำกัดทีมตามการออกแบบจริง ไม่ใช้ Logs Viewer ทั้งโปรเจกต์โดยไม่ตรวจ

การอ่าน initial admin password ใน 5.6: ให้ผู้ติดต่อสิทธิ์เฉพาะ admin/demo secret ที่กลุ่มต้องรับ หรือมีช่องส่งต่อส่วนตัวที่ตรวจเจ้าของแล้ว ห้ามให้ Project Secret Accessor เพื่อแก้ปัญหานี้

## CI ต้องเปลี่ยนไหม

**CI ที่ build/test บน PR ไม่ต้องเปลี่ยนเพราะใช้โปรเจกต์กลาง**:

- คง .github/workflows/ci-docker.yml, job/check test-and-docker, pull_request targets, tests, Docker build และ temporary failing PR
- ไม่เพิ่ม cloud credentials หรือขั้น provision ใน PR CI
- คง main ruleset, teammate review และ staging→main release history

**CD ต้องเปลี่ยนค่าปลายทางและชื่อ resource**:

| ไฟล์/ตำแหน่ง | สิ่งที่นักศึกษาต้องแก้ |
|---|---|
| GitHub Environment demo | GCP_PROJECT_ID=cpe-se-course-2026; GCP_REGION=asia-southeast1; WIF_PROVIDER และ WIF_SERVICE_ACCOUNT ที่ระบบจริงส่งให้ |
| .github/workflows/deploy.yml | SERVICE_NAME, MIGRATE_JOB_NAME, image path `<region>-docker.pkg.dev/<project>/<team-registry>/<team-image>:<sha>` |
| deploy/release.sh | default service/job names, image path และ digest-prefix validation ต้องตรง workflow; ตัว reference ตรวจ prefix ของ digest ด้วย ไม่ใช่แก้เฉพาะ IMAGE บรรทัดเดียว |
| ขั้น first deployment | ใช้สคริปต์ shared-project ที่ไม่มี API enable/IAM/SQL create/secret create หรือ public IAM update แล้ว build/push และ configure/update service/job ของตัวเอง |
| Migration job | command/args, env, SQL connection และ secrets ต้องตรง stack และ seed รันซ้ำได้ release.sh เดิมเปลี่ยนแค่ image ไม่ได้แก้ migration command ให้ |
| deploy/smoke_test.py | URL/path/expected response ตรงแอปจริง; SMOKE_EMAIL และ SMOKE_PASSWORD ตั้งคู่กันเฉพาะเมื่อใช้ login smoke |
| deploy/tests/ | เปลี่ยน expected names ให้ตรง script แล้วรันเทส offline ต้องยังจับ migration fail ก่อน service update ได้ |
| docs/labs/lab-05/deployment.md | ระบุว่ารายวิชา provision infrastructure ให้, names/config/env, ขั้น manual first deploy, pipeline/release procedure และหลักฐานแต่ละกลุ่ม |

ชื่อ environment demo ต้องตรง GitHub, deploy.yml และ WIF subject condition. deployment workflow ยังใช้ main และ id-token: write เฉพาะ deploy job; ไม่สร้าง JSON key. คง CI gate, SHA image tag, immutable digest, migration-before-service, concurrency cancel-in-progress:false และ smoke test

**จุดที่แก้ใน portal แล้ว:** handoff เดิมให้ GitHub variables PROJECT_ID/REGION ซึ่งผิดจาก Starter Kit. แก้เป็น GCP_PROJECT_ID/GCP_REGION; PROJECT_ID/REGION เป็นชื่อ env ภายใน shell/job ที่ workflow map จาก vars.* ไม่ใช่ชื่อ GitHub variables. ข้อมูล preview ที่มีอยู่เดิมจะถูกแสดง/ดาวน์โหลดตาม schema ที่แก้แล้วด้วย

## เส้นทาง build ครั้งแรกต้องประกาศให้ตรง

deploy.sh เดิมใช้ gcloud builds submit แต่ deploy.yml ใช้ docker build/push บน GitHub runner. เพื่อไม่ให้ทุกกลุ่มมีสิทธิ์ใช้งาน builder กลาง เลือกให้ manual first deploy ใช้ Docker ในเครื่อง/Cloud Shell แล้ว push เข้า team registry และ CD ใช้ GitHub runner ตามเดิม การเปลี่ยนนี้ต้องเขียนคู่มือเสริมและทดสอบด้วย restricted student identity จริง อย่าบอกว่า “ขั้น 9 ใช้คำสั่งเดิมได้ทันที”

หลัง initial config สำเร็จ release.sh ออกแบบมา update pre-provisioned resources อยู่แล้ว จึง reuse ได้โดยปรับ names/image validation ให้ตรง ไม่ควรย้ายการ deploy release ทุกครั้งมาให้ portal ทำแทนนักศึกษา

## ยังไม่ครบก่อนปล่อยใช้งานจริง

- OAuth จริง, durable production hosting/queue และ live provisioner
- shared-project first-deploy script และคำสั่ง configure job/service ที่ทดสอบกับบัญชีนักศึกษาจริง
- ใส่แอปตัวอย่างครบวงจรอย่างน้อยสองกลุ่ม: Docker build→push→migration→service→smoke→pipeline→persistence และ cross-team IAM denial
- แก้ broad IAM เดิมอย่างมีแผน: scoped grants เพิ่มใหม่ไม่ลบ project-level permissions ที่มีอยู่แล้ว
- ตรวจ SQL/WIF/service-account quotas และ billing รวมของรายวิชา; เว็บไม่ได้เพิ่ม quota หรือ hard-cap เงินรายกลุ่ม
- ตกลงกับอาจารย์เรื่องคู่มือเสริม/การแสดงหลักฐานขั้นที่รายวิชาทำแทน คง rubric เดิม ไม่อ้างว่าปรับเกณฑ์ให้เอง

## เอกสาร Google ที่ตรวจประกอบ

- https://docs.cloud.google.com/run/docs/deploying — deploy to an existing service / resource-scoped permissions
- https://docs.cloud.google.com/run/docs/execute/jobs — job execution permissions
- https://docs.cloud.google.com/sql/docs/postgres/iam-conditions — instance-specific conditional Cloud SQL access

## ปรับล่าสุด: ใช้ไฟล์เดิม ไม่เพิ่ม config ใหม่

ข้อเสนอเดิมเรื่อง course-app.json และ course-deploy.py ถูกยกเลิกแล้ว เว็บรุ่นปัจจุบันอ่าน repo ที่ commit main ชัดเจนและแสดง diff บน deploy/deploy.sh, release.sh, deploy.yml และ deployment-script tests เดิม โดยคง CI/app tests, port, migration, seed และ env ของกลุ่ม เมื่อรูปแบบไม่ชัดจะหยุดให้ TA ตรวจ ไม่มีการ execute repo หรือเขียน GitHub จากเว็บ

Patch ปรับ deploy.sh ให้ใช้ infrastructure ที่เตรียมแล้ว, build/push ด้วย Docker, migration ก่อน update service และ digest/SHA ส่วน pipeline เดิมยังผ่าน CI และ main/environment/WIF ตามไกด์ Preview patch มีตัวบล็อก deploy/CD จริงและไม่มีการยืนยันว่า infrastructure พร้อม การรับ patch เป็นขั้นเตรียม PR ไม่ใช่การตรวจรับ Lab หรือการ merge อัตโนมัติ
