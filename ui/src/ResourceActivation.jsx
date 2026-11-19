import React,{useState} from 'react';
import {Alert,Button,Card,Checkbox,Space,Tag,Typography} from 'antd';
import {CloudOutlined,DatabaseOutlined,ArrowRightOutlined} from '@ant-design/icons';
import {t} from './i18n.js';
const {Title,Paragraph,Text}=Typography;
export default function ResourceActivation({busy,onActivate,onReview}){
 const [confirmed,setConfirmed]=useState(false);
 return <><Tag color="blue">{t('สำหรับโปรเจกต์ของกลุ่ม')}</Tag><Title level={4} className="!mt-3">{t('เปิดทรัพยากรได้โดยไม่ต้องใส่ GitHub')}</Title><Paragraph type="secondary">{t('ใช้ทำ Final Project หรือแอปของกลุ่มได้ ไม่ต้องตรวจ repo และไม่จำเป็นต้องทำตามโครงสร้าง Lab 5 ระบบเตรียมพื้นที่ให้ ส่วนกลุ่ม build และ deploy แอปของตัวเอง')}</Paragraph><Space wrap className="!mb-4"><Tag icon={<CloudOutlined/>}>Cloud Run</Tag><Tag icon={<DatabaseOutlined/>}>PostgreSQL</Tag><Tag>Artifact Registry</Tag><Tag>Secrets · Logs</Tag></Space><Alert showIcon type="info" title={t('Cloud SQL คิดค่าใช้จ่ายตามเวลาเปิดใช้งาน เครดิตใช้ร่วมกันทั้งรายวิชา สร้างได้หนึ่งชุดต่อกลุ่ม')}/><div className="my-5"><Checkbox checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}>{t('เข้าใจว่าใช้เครดิตส่วนกลาง และจะใช้เฉพาะทรัพยากรของกลุ่ม')}</Checkbox></div><Space wrap><Button type="primary" size="large" icon={<ArrowRightOutlined/>} loading={busy} disabled={!confirmed} onClick={()=>onActivate({resources_only:true})}>{t('Activate ทรัพยากรอย่างเดียว')}</Button><Button type="link" onClick={onReview}>{t('หากทำ Lab 5 ให้ตรวจ repo ทางนี้')}</Button></Space><Paragraph type="secondary" className="!mt-4 !mb-0">{t('จะยังไม่เชื่อม GitHub Actions หรือสร้าง Workload Identity provider จนกว่ากลุ่มเลือกเชื่อม repo ภายหลัง')}</Paragraph></>;
}
