import React from 'react';
import {Button,Card,Result,Space,Tag,Typography} from 'antd';
import {ArrowLeftOutlined,GoogleOutlined,LockOutlined,FileSearchOutlined,ClockCircleOutlined,InfoCircleOutlined} from '@ant-design/icons';
import PortalHeader from './PortalHeader.jsx';
import {t} from './i18n.js';
const {Text,Paragraph}=Typography;
export default function ErrorPage({error,language,onLanguage,oauthReady}){
 const account=error.kind==='account_access';
 const title=account?t('บัญชีนี้ยังไม่มีสิทธิ์เข้าใช้งาน'):error.code===404?t('ไม่พบหน้าที่คุณต้องการ'):error.code===400?t('คำขอนี้หมดอายุหรือไม่ถูกต้อง'):t('ยังดำเนินการต่อไม่ได้');
 const icon=error.code===403?<LockOutlined/>:error.code===404?<FileSearchOutlined/>:<ClockCircleOutlined/>;
 return <div className="error-shell"><PortalHeader language={language} onLanguage={onLanguage}/><main className="error-main"><Card className="error-card"><div className="error-card-meta"><Text className="eyebrow">STUDENT WORKSPACE</Text><Tag bordered={false}>{error.code}</Tag></div><Result icon={<span className="error-symbol">{icon}</span>} title={title} subTitle={t(error.message)} extra={<Space wrap size={12}>{oauthReady&&error.code!==404&&<Button type="primary" size="large" icon={<GoogleOutlined/>} href="/auth/google">{account?t('เปลี่ยนบัญชี Google'):t('เข้าสู่ระบบอีกครั้ง')}</Button>}<Button size="large" icon={<ArrowLeftOutlined/>} href="/">{t('กลับหน้าหลัก')}</Button></Space>}/>{account&&<div className="error-help"><InfoCircleOutlined/><div><Text strong>{t('ตรวจสอบ Gmail ของกลุ่ม')}</Text><Paragraph>{t('ใช้ Gmail เดียวกับที่กรอกไว้ในชีตของกลุ่ม หากใช้บัญชีถูกต้องแล้ว ให้ส่งอีเมลที่ใช้และภาพหน้านี้ให้ทีม TA ตรวจสอบ')}</Paragraph></div></div>}</Card><p className="error-footnote">{t('หากยังพบปัญหา กรุณาติดต่อทีม TA ของรายวิชา')}</p></main><footer className="portal-footer"><span>CPE334 · Department of Computer Engineering</span><span>Student Cloud Portal · 2026</span></footer></div>;
}
