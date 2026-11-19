import React,{useId,useState} from 'react';
import {Alert,Button} from 'antd';
import {DownloadOutlined} from '@ant-design/icons';
import {t,getLanguage,isKnownMessage} from './i18n.js';
import {fetchDownload,saveBlob} from './download.js';
// Accessible download button: loading state, error Alert (role=alert), redirect to login on 401.
export default function DownloadButton({href,fallbackName,type,size,disabled,disabledReason,children,onDone}){
 const reasonId=useId(),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function run(){
  if(busy||disabled)return;
  setBusy(true);setError('');
  try{
   const {blob,filename}=await fetchDownload(href,{fallbackName,language:getLanguage(),isKnown:isKnownMessage,messages:{
    network:'เชื่อมต่อระบบไม่สำเร็จ กรุณาลองใหม่',failed:'ดาวน์โหลดไม่สำเร็จ กรุณาลองใหม่',
    unauthorized:'เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่',notFound:'ยังไม่พบไฟล์นี้ ตรวจสอบว่ากลุ่มมีแผนทรัพยากรแล้ว',unavailable:'ไฟล์ยังไม่พร้อมบนเซิร์ฟเวอร์ กรุณาแจ้ง TA'}});
   saveBlob(blob,filename);if(onDone)onDone();
  }catch(e){
   if(e?.status===401){location.assign('/');return;}
   setError(e?.message||'ดาวน์โหลดไม่สำเร็จ กรุณาลองใหม่');
  }finally{setBusy(false);}
 }
 return <span className="download-button"><Button type={type} size={size} icon={<DownloadOutlined/>} loading={busy} disabled={disabled} onClick={run} aria-describedby={disabled&&disabledReason?reasonId:undefined}>{children}</Button>
  {disabled&&disabledReason&&<span id={reasonId} className="block mt-2 text-xs text-slate-500">{disabledReason}</span>}
  <span role="alert" aria-live="assertive">{error&&<Alert className="!mt-2" type="error" showIcon title={t(error)}/>}</span></span>;
}
