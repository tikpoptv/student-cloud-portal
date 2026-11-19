// Only public deployment references belong in the student handoff.
export const resourceDefinitions=[
 ['cloud_run_service','Cloud Run service','รันแอปของกลุ่ม'],
 ['migration_job','Migration job','รัน migration ก่อน deploy แอป'],
 ['sql_instance','Cloud SQL instance','ฐานข้อมูล PostgreSQL ของกลุ่ม'],
 ['sql_tier','SQL tier','ขนาดเครื่องฐานข้อมูลตามแผน'],
 ['database','Database','ชื่อฐานข้อมูล'],
 ['database_user','Database user','ชื่อผู้ใช้ฐานข้อมูล ไม่ใช่รหัสผ่าน'],
 ['sql_connection_name','SQL connection name','อ้างอิง Cloud SQL จาก Cloud Run'],
 ['registry','Artifact Registry repository','เก็บ Docker image ของกลุ่ม'],
 ['image_repository','Image repository URI','ปลายทาง push image ต้องเติม tag หรือ digest'],
 ['runtime_service_account','Runtime service account','ตัวตนที่แอปและ migration ใช้ทำงาน'],
 ['deployer_service_account','Deployer service account','ตัวตนสำหรับ GitHub Actions deploy'],
 ['database_secret','DATABASE_URL secret','ชื่อ secret สำหรับเชื่อมต่อฐานข้อมูล'],
 ['admin_password_secret','ADMIN_PASSWORD secret','ชื่อ secret รหัสผู้ดูแลของแอป'],
 ['demo_password_secret','DEMO_USER_PASSWORD secret','ชื่อ secret สำหรับ seed ข้อมูล demo เมื่อใช้ --demo'],
 ['wif_pool','Workload Identity pool','ใช้ยืนยันตัวตน GitHub Actions โดยไม่สร้าง key file'],
 ['logs_view','Logs view','อ่าน log เฉพาะทรัพยากรของกลุ่ม'],
 ['wif_provider','Workload Identity provider','ผู้ให้บริการตัวตน GitHub ใน pool ของกลุ่ม'],
];
// Resource-only groups have no Workload Identity, so the deployer is not described as a GitHub Actions identity.
export function resourceDefinitionsFor(githubConnected){
 return githubConnected===true?resourceDefinitions:resourceDefinitions.map(row=>row[0]==='deployer_service_account'?[row[0],row[1],'ตัวตนสำหรับ deploy แอปของกลุ่ม ยังไม่ผูกกับ GitHub Actions']:row);
}
export const variableNames=['GCP_PROJECT_ID','GCP_REGION','WIF_PROVIDER','WIF_SERVICE_ACCOUNT'];
export function resourceContext(team,activation){
 const o=activation?.outputs;
 // In live mode outputs is {} until all six stages finish: without prefix and resources there is nothing real to show.
 if(!o||typeof o.prefix!=='string'||!o.prefix||!o.resources||typeof o.resources!=='object')return null;
 return {
  team:team.name,mode:o.mode,activation_status:activation.status,
  created_in_google_cloud:o.created_in_google_cloud===true,
  github_connected:o.github_connected===true,service_url:o.service_url,application_deployed_by_portal:o.application_deployed_by_portal===true,
  project_id:o.project_id,region:o.region,prefix:o.prefix,github_repository:o.github_repository,
  resources:Object.fromEntries(resourceDefinitions.filter(([key])=>o.resources?.[key]!==undefined).map(([key])=>[key,o.resources[key]])),
  github_variables:Object.fromEntries(variableNames.filter(key=>o.github_variables?.[key]!==undefined).map(key=>[key,o.github_variables[key]])),
 };
}
// What the Team resources tab should show: 'none' (no activation), 'preparing', 'failed' or 'ready' (context available).
export function resourceState(team,activation){
 if(!activation)return {state:'none',prefix:team?.prefix||''};
 if(resourceContext(team||{},activation))return {state:'ready',prefix:activation.outputs.prefix};
 return {state:activation.status==='failed'?'failed':'preparing',prefix:team?.prefix||''};
}
export function contextJSON(context,t){
 if(!context)return '';
 return JSON.stringify({...context,
  usage_notes:[
   t('สิทธิ์จำกัดเฉพาะ resource ของกลุ่ม คำสั่ง list ทั้งโปรเจกต์อาจใช้ไม่ได้ ให้ใช้ชื่อจากแท็บทรัพยากรของกลุ่มกับคำสั่ง describe แทน'),
   t('ทรัพยากรพร้อมไม่เท่ากับแอป deploy แล้ว กลุ่มต้อง build, migration, deploy และเก็บหลักฐานเอง'),
   context.created_in_google_cloud?t('เป็นผลที่ระบบบันทึกไว้ ไม่ได้ตรวจสถานะสดจาก Google Cloud'):t('ยังไม่มีการสร้างทรัพยากรจริง ห้ามใช้ข้อมูลชุดนี้เป็นหลักฐานว่า deploy ได้แล้ว'),
   t('ใช้เฉพาะทรัพยากรที่ระบุของกลุ่มนี้ ห้ามแก้หรือลบของกลุ่มอื่น'),
   context.github_connected===false?t('GitHub และ Lab 5 เป็นทางเลือก ใช้ทรัพยากรนี้ทำโปรเจกต์ของกลุ่มได้ โดย build และ deploy แอปเอง'):t('Portal/TA เตรียม infrastructure และ IAM กลุ่มยังต้อง build → migration → deploy เองตาม diff ที่ผ่าน review และไกด์ Lab 5'),
   ...(context.github_connected===false?[]:[t('PROJECT_NUMBER เป็น placeholder ต้องรอค่าจริงจาก TA ห้ามเดาตัวเลข และห้ามสร้าง service account key file')]),
   t('ชื่อ secret เป็นเพียงชื่ออ้างอิง อย่าใส่ค่ารหัสผ่าน token หรือ DATABASE_URL จริงลงในแชต AI'),
  ],
  agent_guidance:{
   purpose:t('หากคุณเป็น agent โปรดช่วยให้นักศึกษาได้เรียนรู้และลงมือทำด้วยตนเอง ไม่ทำงานทั้งหมดแทนเขา'),
   approach:[
    t('ถามก่อนว่านักศึกษาเข้าใจอะไรแล้ว ลองทำอะไรมา และติดที่ขั้นตอนไหน'),
    t('อธิบายเหตุผลของแต่ละขั้น ให้คำใบ้หรือตัวอย่างเล็กๆ แล้วให้นักศึกษาลองทำเอง'),
    t('ก่อนเสนอคำสั่งหรือแก้ไฟล์ อธิบายผลที่จะเกิดขึ้น และให้นักศึกษาตรวจสอบค่าของกลุ่ม'),
    t('หลังแต่ละขั้น ให้นักศึกษาอธิบายสิ่งที่ทำและผลที่ได้ แล้วช่วยตรวจความเข้าใจ'),
    context.github_connected===false?t('ให้ผู้เรียนตรวจการเปลี่ยนแปลงและทดสอบแอปด้วยตนเอง อย่าอ้างว่าทำขั้นตอนที่ยังไม่ได้ทำ'):t('อย่าข้าม review, tests หรือหลักฐานที่ Lab กำหนด และอย่าอ้างว่าทำขั้นตอนที่ยังไม่ได้ทำ'),
   ],
  },
 },null,2)+'\n';
}
