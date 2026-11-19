import React,{useEffect,useState} from 'react';
import {Alert,Button,Descriptions,Space,Spin,Steps,Tag,Typography} from 'antd';
import {CheckCircleOutlined,ClockCircleOutlined,ReloadOutlined} from '@ant-design/icons';
import {t} from './i18n.js';
import {activationStatus,duration,estimateServerNow} from './activation-status.js';
const {Text,Paragraph}=Typography;
const explanations=[
 'กำลังเตรียมที่เก็บ Docker image สำหรับกลุ่ม',
 'Cloud SQL อาจใช้เวลาหลายนาที บางครั้งเกิน 10 นาที ขั้นตอนอาจยังไม่เปลี่ยนระหว่างที่ Google เตรียมฐานข้อมูล ระบบจะตรวจงานเป็นระยะ',
 'กำลังเตรียมบัญชีและสิทธิ์ที่ใช้เฉพาะทรัพยากรของกลุ่ม',
 'กำลังเตรียมการเชื่อมต่อฐานข้อมูลและ secrets โดยไม่แสดงรหัสผ่านบนหน้าเว็บ',
 'กำลังเตรียม Cloud Run และงาน migration สำหรับแอปของกลุ่ม',
 'กำลังเตรียม logs ของกลุ่ม และเชื่อม GitHub หากกลุ่มเลือกใช้',
];
export default function ActivationProgress({activation,progress,serverTime,receivedAt,connected,steps,language,preview,onRefresh,onRetryLink,busy}){
 const [tick,setTick]=useState(Date.now()),[checking,setChecking]=useState(false);
 // The 1s clock only runs while something can still change; finished or failed jobs never re-render on a timer.
 const linkBusy=activation.status==='ready'&&['queued','running'].includes(activation.github_link_status);
 const running=!['ready','failed'].includes(activation.status)||linkBusy;
 useEffect(()=>{if(!running)return;setTick(Date.now());const timer=setInterval(()=>setTick(Date.now()),1000);return()=>clearInterval(timer);},[running]);
 const now=estimateServerNow(serverTime,receivedAt,running?tick:receivedAt);
 const m=activationStatus(activation,progress,now,connected);
 const clock=value=>value?new Date(value*1000).toLocaleTimeString(language==='en'?'en-GB':'th-TH',{hour:'2-digit',minute:'2-digit',second:'2-digit',timeZone:'Asia/Bangkok'}):t('ยังไม่เริ่มตรวจ');
 const title=m.failed?'เตรียมทรัพยากรไม่สำเร็จ':m.ready?(preview?'แผนทดลองพร้อมแล้ว':'ทรัพยากรพร้อมแล้ว'):m.stale?'ยังยืนยันความคืบหน้าล่าสุดไม่ได้':m.waitingQueue?'รับคำขอแล้ว กำลังรอคิว':preview?'กำลังจำลองการเตรียมทรัพยากร':'ระบบกำลังดำเนินการ';
 async function refresh(){setChecking(true);try{await onRefresh();}finally{setChecking(false);}}
 return <div className="activation-progress"><div className="activation-progress-heading" role="status" aria-live="polite"><Space align="start">{m.ready?<CheckCircleOutlined className="activation-ready-icon"/>:m.failed||m.stale?<ClockCircleOutlined/>:<Spin size="small"/>}<div><Text strong>{t(title)}</Text>{!m.ready&&!m.failed&&<div className="mt-1"><Text type="secondary">{t(m.waitingQueue?'งานถูกบันทึกแล้ว ระบบจะเริ่มเมื่อถึงคิว':`ขั้นตอนปัจจุบัน`)}{!m.waitingQueue&&': '+t(steps[m.done]?.[1]||'')}</Text></div>}</div></Space><Tag color={m.ready?'success':m.failed?'error':m.stale?'warning':'blue'}>{m.done}/6 {t('ขั้นตอนเสร็จแล้ว')}</Tag></div>
 <div className={'activation-stepbar'+(m.failed?' is-failed':m.ready?' is-ready':'')} aria-hidden="true">{steps.map(([key],i)=><span key={key} className={i<m.done?'is-done':i===m.done&&!m.ready?'is-current':''}/>)}</div><Paragraph type="secondary" className="activation-phase-note">{t('แถบนี้นับขั้นตอนที่เสร็จ ไม่ใช่เวลาที่เหลือ แต่ละขั้นใช้เวลาไม่เท่ากัน')}</Paragraph>
 <Descriptions className="activation-timing" size="small" column={{xs:1,sm:2}} items={[{key:'total',label:t('เวลารวม (นาที:วินาที)'),children:<span className="activation-timer" aria-live="off">{duration(m.elapsed,language)}</span>},{key:'stage',label:t(m.ready?'เสร็จเมื่อ (เวลาไทย)':'อยู่ในขั้นตอนนี้มา (นาที:วินาที)'),children:m.ready?clock(activation.updated_at):<span className="activation-timer" aria-live="off">{duration(m.stageElapsed,language)}</span>},{key:'worker',label:t('ระบบตรวจงานล่าสุด (เวลาไทย)'),children:clock(m.heartbeat)},{key:'page',label:t('หน้าเว็บรับข้อมูลล่าสุด (เวลาไทย)'),children:clock(serverTime)}]}/>
 {!m.ready&&!m.failed&&<Alert className="!mt-4" type={m.stale?'warning':'info'} showIcon title={t(m.stale?'กำลังตรวจสอบการเชื่อมต่อกับระบบ':m.done===1?'กำลังรอ Google Cloud เตรียมฐานข้อมูล':'งานยังอยู่ระหว่างดำเนินการ')} description={<><Paragraph className="!mb-2">{t(m.queueStuck?'งานรออยู่ในคิวนานผิดปกติ อาจส่งเข้าคิวไม่สำเร็จ กดปุ่มส่งงานเข้าคิวอีกครั้ง หรือติดต่อ TA พร้อม prefix ของกลุ่ม':m.stale?'ยังไม่ได้รับข้อมูลการทำงานล่าสุด งานอาจยังทำอยู่ กดตรวจสถานะอีกครั้ง หากยังไม่อัปเดตให้ติดต่อ TA พร้อม prefix ของกลุ่ม':m.waitingQueue?'รอระบบเริ่มงาน ไม่ต้องส่งคำขอซ้ำ':preview?'เป็นการจำลอง ไม่มีการสร้างทรัพยากรจริง':explanations[m.done])}</Paragraph>{!m.canRetry&&<Text>{t('ปิดหน้านี้แล้วกลับมาดูต่อได้ งานถูกบันทึกไว้ ไม่ต้องกด Activate ซ้ำ')}</Text>}{activation.error&&<details className="activation-wait-detail"><summary>{t('รายละเอียดการรอล่าสุด')}</summary><Text type="secondary">{t(activation.error)}</Text></details>}</>}/>}
 {m.failed&&<Alert className="!mt-4" type="error" showIcon title={t('กรุณาลองใหม่หรือติดต่อ TA')} description={t(activation.error||'เตรียมทรัพยากรไม่สำเร็จ')}/>}
 {m.ready&&m.link.state&&<Alert className="!mt-4" showIcon type={m.link.failed?'warning':'info'} title={t(m.link.failed?'เชื่อม GitHub ไม่สำเร็จ ทรัพยากรของกลุ่มยังพร้อมใช้งาน':m.link.stale?'ยังยืนยันความคืบหน้าการเชื่อม GitHub ไม่ได้':'กำลังเชื่อม GitHub กับทรัพยากรที่พร้อมแล้ว')} description={<><Paragraph className="!mb-2">{m.link.failed?t(activation.github_link_error||'เชื่อม GitHub ไม่สำเร็จ'):t(m.link.waitingQueue?'รอระบบเริ่มเชื่อม GitHub ไม่ต้องส่งคำขอซ้ำ':'ทรัพยากรและไฟล์ handoff ยังใช้ได้ระหว่างเชื่อม GitHub')}</Paragraph>{m.link.canRetry&&<Button size="small" loading={busy} onClick={onRetryLink}>{t('ลองเชื่อม GitHub อีกครั้ง')}</Button>}</>}/>}
 {m.ready&&<Alert className="!mt-4" showIcon type="success" title={t(preview?'จำลองขั้นตอนครบแล้ว':'เตรียมทรัพยากรครบแล้ว')} description={t(preview?'ยังไม่มีทรัพยากรจริงใน Google Cloud':'กลุ่มยังต้อง build, migration และ deploy แอปของตัวเอง')}/>}
 <div className="mt-4"><Button icon={<ReloadOutlined/>} loading={checking} onClick={refresh}>{t('ตรวจสถานะอีกครั้ง')}</Button>{!m.ready&&!m.failed&&<Text type="secondary" className="!ml-3 text-xs">{t('หน้านี้ตรวจสถานะอัตโนมัติเมื่อเปิดค้างไว้')}</Text>}</div>
 <Steps className="!mt-6" orientation="vertical" current={m.done} status={m.failed?'error':'process'} size="small" items={steps.map(([key,title,description],i)=>({key,title:t(title),description:i<m.done?t(preview?'จำลองแล้ว':'เสร็จแล้ว'):i===m.done?t(m.failed?'ติดปัญหา':m.stale?'รอยืนยันสถานะล่าสุด':m.waitingQueue?'รอคิว':'อยู่ระหว่างดำเนินการ'):t('รอดำเนินการ')}))}/>
 </div>;
}
