import React,{useState} from 'react';
import {Alert,Button,Card,Collapse,Space,Steps,Tag,Typography} from 'antd';
import {CopyOutlined,CheckOutlined} from '@ant-design/icons';
import DownloadButton from './DownloadButton.jsx';
import {t} from './i18n.js';
import {kitCommands} from './kit-commands.js';
const {Title,Text,Paragraph}=Typography;
async function copyText(text){
 try{if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(text);return true;}}catch{}
 try{const a=document.createElement('textarea');a.value=text;a.style.position='fixed';a.style.opacity='0';document.body.appendChild(a);a.select();const ok=document.execCommand('copy');a.remove();return ok;}catch{return false;}
}
function CommandBlock({text}){
 const [state,setState]=useState('');
 async function copy(){const ok=await copyText(text);setState(ok?'done':'failed');setTimeout(()=>setState(''),2500);}
 return <div className="kit-command"><pre>{text}</pre><Button size="small" icon={state==='done'?<CheckOutlined/>:<CopyOutlined/>} onClick={copy}>{t('คัดลอก')}</Button><div role="status" aria-live="polite" className="kit-copy-status">{state==='done'?t('คัดลอกแล้ว'):state==='failed'?t('คัดลอกไม่สำเร็จ ลองเลือกข้อความแล้วกด Ctrl+C'):''}</div></div>;
}
function Step({title,children,cmd}){
 return <div className="space-y-2"><Text strong>{title}</Text><div className="text-slate-600">{children}</div>{cmd&&<CommandBlock text={cmd}/>}</div>;
}
export default function FinalProjectKit({team,activation,onOpenOverview}){
 const prefix=activation?.outputs?.prefix||team?.prefix,c=kitCommands(prefix);
 // A plan exists as soon as an activation row exists; in live mode outputs stays {} until every stage is done.
 const hasPlan=Boolean(activation),ready=activation?.status==='ready'&&hasPlan;
 const banner=ready
  ?<Alert type="success" showIcon title={t('ทรัพยากรของกลุ่มพร้อมแล้ว ใช้ Project Kit ได้เลย')}/>
  :<Alert type={hasPlan?'warning':'info'} showIcon title={hasPlan?t('ทรัพยากรของกลุ่มยังไม่พร้อม รอให้เตรียมระบบเสร็จก่อนจึงจะ deploy ได้'):t('กลุ่มยังไม่มีแผนทรัพยากร ต้องเปิดทรัพยากรก่อนใช้ Project Kit')} action={<Button size="small" type="primary" onClick={onOpenOverview}>{t('ไปเปิดทรัพยากรก่อน')}</Button>}/>;
 const items=[
  {title:t('แตกไฟล์และตรวจความพร้อม'),content:<Step title={t('แตก zip แล้วย้ายโฟลเดอร์ project-kit เข้าไปในโฟลเดอร์โปรเจกต์ของคุณ')}><Paragraph className="!mb-1" type="secondary">{t('Windows: ใช้ WSL หรือ Git Bash เพราะ kit.sh เป็น bash')}</Paragraph><CommandBlock text={c.unzip}/><Paragraph className="!mt-2 !mb-2">{t('เปิด terminal ที่โฟลเดอร์โปรเจกต์ (โฟลเดอร์ที่มีโค้ดและ Dockerfile ของคุณ ไม่ใช่ข้างใน project-kit) แล้วรันคำสั่งทุกข้อจากตรงนั้น จากนั้นให้ doctor ตรวจเครื่องและสิทธิ์')}</Paragraph><CommandBlock text={c.doctor}/><Paragraph className="!mt-2 !mb-1">{t('ถ้าบรรทัดไหนไม่ผ่าน doctor จะบอกวิธีแก้ใต้บรรทัดนั้น')}</Paragraph><Paragraph className="!mb-1" type="secondary">{t('ไฟล์ project-kit/resources.env ใน zip เติมค่าของกลุ่มให้แล้ว kit.sh หาเจอเอง ไม่ต้องคัดลอกหรือแก้ (ถ้าวาง resources.env ไว้ในโฟลเดอร์โปรเจกต์ จะใช้ไฟล์นั้นก่อน)')}</Paragraph><Paragraph className="!mb-1" type="secondary">{t('ถ้าขึ้น permission denied ให้รัน:')}</Paragraph><CommandBlock text={c.chmod}/></Step>},
  {title:t('เลือก stack และตั้งค่าแอป'),content:<Step title={t('สร้าง Dockerfile จาก templates/ (ข้ามได้ถ้ามีแล้ว) แล้วแก้ app.env')}><Text>{t('เลือกคำสั่งตาม stack ของคุณ (เลือกอันเดียว) ใส่ env ธรรมดาใน app.env เท่านั้น')}</Text>{c.stacks.map(s=><CommandBlock key={s.stack} text={s.command}/>)}<Text>{t('แล้วคัดลอกไฟล์ตัวอย่าง app.env')}</Text><CommandBlock text={c.appEnv}/><Paragraph className="!mt-2 !mb-0" type="secondary">{t('ถ้า kit.sh ปฏิเสธ env เพราะดูเหมือนความลับ แต่จริง ๆ ไม่ใช่ความลับ ใส่ --allow-plain NAME (ตอน env set) หรือ ALLOW_PLAIN=NAME ใน resources.env/app.env ได้')}</Paragraph><Alert className="!mt-2" type="error" showIcon title={t('ห้ามใส่รหัสผ่าน token หรือ API key ใน app.env ใช้ข้อ 7 แทน')}/></Step>},
  {title:t('Build image'),content:<Step title={t('สร้าง Docker image แล้วส่งขึ้น Artifact Registry ของกลุ่ม')} cmd={c.build}><Text type="secondary">{t('รันในโฟลเดอร์โปรเจกต์ที่มี Dockerfile ของคุณ')}</Text></Step>},
  {title:t('Migrate ฐานข้อมูล'),content:<Step title={t('ถ้าแอปไม่มี migration ข้ามข้อนี้ได้เลย (deploy จะข้ามให้เอง) ถ้ามี ให้ตั้ง MIGRATE_COMMAND ใน resources.env ก่อนรัน')} cmd={c.migrate}><Text type="secondary">{t('ตัวอย่างบรรทัดใน project-kit/resources.env:')}</Text><CommandBlock text={c.migrateExample}/></Step>},
  {title:t('Deploy และเปิดดูแอป'),content:<Step title={t('deploy ขึ้น Cloud Run ของกลุ่ม ดูสถานะ แล้วเปิดแอปในเบราว์เซอร์')} cmd={c.deploy}><Text type="secondary">{t('อยากลองก่อนโดยไม่เปลี่ยนอะไรจริง ใส่ --dry-run ไว้หน้าคำสั่ง')}</Text></Step>},
  {title:t('ตั้ง env ของแอป'),content:<Step title={t('เพิ่มหรือแก้ env ธรรมดาบน service โดยไม่ต้อง build ใหม่')} cmd={c.env}/>},
  {title:t('Secret ของกลุ่ม (API key ฯลฯ)'),content:<Step title={t('กลุ่มมี 5 ช่อง secret ใส่ค่าได้เฉพาะช่องเหล่านี้')} cmd={c.secretAdd}><div className="mb-2">{c.secretSlots.map(s=><Tag key={s}>{s}</Tag>)}</div><Paragraph className="!mb-2">{t('คำสั่ง add จะถามค่าแบบซ่อนตัวอักษร ค่าที่ใส่แล้วอ่านกลับจากเว็บไม่ได้ จะเปลี่ยนค่าให้ add อีกครั้งเพื่อสร้าง version ใหม่')}</Paragraph><Text>{t('จากนั้นผูกช่องกับชื่อตัวแปรของแอป แล้ว deploy ใหม่')}</Text><CommandBlock text={c.secretMap}/></Step>},
  {title:t('ดู log และย้อนกลับ'),content:<Step title={t('ดู log ของแอป และย้อนกลับไป revision ก่อนหน้าเมื่อ deploy พัง')}><Text type="secondary">{t('ดู log ของแอป')}</Text><CommandBlock text={c.logs}/><Text type="secondary">{t('ย้อนกลับไป revision ก่อนหน้า (รันเมื่อ deploy พังเท่านั้น คำสั่งนี้เปลี่ยนแอปที่รันอยู่จริง)')}</Text><CommandBlock text={c.rollback}/></Step>},
 ];
 return <div className="space-y-5">
  {banner}
  <Card><Space align="start" wrap className="w-full justify-between"><div><Title level={4} className="!mb-1">{t('Final Project Kit')}</Title><Paragraph type="secondary" className="!mb-0">{t('ในไฟล์ zip: kit.sh, README.md, templates/ (Dockerfile ตัวอย่าง), app.env.example และ resources.env ที่เติมค่าของกลุ่มแล้ว')}</Paragraph></div><DownloadButton type="primary" size="large" href="/api/kit/download" fallbackName={'cpe334-project-kit-'+c.prefix+'.zip'} disabled={!hasPlan} disabledReason={t('ต้องเปิดทรัพยากรของกลุ่มก่อนจึงจะดาวน์โหลดได้ ไปที่แท็บ เปิดทรัพยากรและดูสถานะ')}>{t('ดาวน์โหลด Project Kit (.zip)')}</DownloadButton></Space></Card>
  {!c.valid&&<Alert type="info" showIcon title={t('ยังไม่ทราบ prefix ของกลุ่ม คำสั่งด้านล่างใช้ PREFIX แทนชื่อจริง')}/>}
  <Card title={t('ก่อนเริ่ม')}><Paragraph className="!mb-2">{t('ติดตั้ง gcloud และ docker แล้วล็อกอินด้วย Gmail ที่ลงทะเบียนไว้')}</Paragraph><CommandBlock text={c.prereq}/></Card>
  <Card title={t('ทำตามทีละขั้น')}><Steps orientation="vertical" current={-1} items={items.map(i=>({title:i.title,content:i.content,status:'process'}))}/></Card>
  <Collapse items={[{key:'limits',label:t('ทำไม่ได้ / ต้องขอใคร'),children:<ul className="list-disc space-y-2 pl-5">
   <li>{t('สร้าง Cloud SQL เพิ่มเองไม่ได้ ใช้ instance ของกลุ่มที่เตรียมไว้')}</li>
   <li>{t('แตะทรัพยากรของกลุ่มอื่นไม่ได้ kit จะปฏิเสธชื่อที่ไม่ขึ้นต้นด้วย prefix ของกลุ่ม')}</li>
   <li>{t('ต่อฐานข้อมูลจากเครื่องตัวเองต้องขอรหัสผ่านจาก TA แล้วใช้ Cloud SQL Auth Proxy')}</li>
   <li>{t('เครดิตใช้ร่วมกันทั้งรายวิชา ตั้ง max instances ให้ต่ำ')}</li>
   <li>{t('ห้ามลบทรัพยากรที่ระบบเตรียมให้')}</li></ul>}]}/>
 </div>;
}
