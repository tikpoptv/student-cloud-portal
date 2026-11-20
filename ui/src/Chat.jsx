import React,{useCallback,useEffect,useRef,useState} from 'react';
import {Alert,Button,Empty,Input,Space,Typography} from 'antd';
import {BellOutlined,SendOutlined} from '@ant-design/icons';
import {t} from './i18n.js';
import {pushAdvice,detectEnvironment,currentSubscription,enablePush,disablePush} from './push.js';
const {Text,Paragraph}=Typography;
const POLL_MS=10000;
const stamp=seconds=>new Date(seconds*1000).toLocaleString(document.documentElement.lang==='en'?'en-GB':'th-TH',{dateStyle:'short',timeStyle:'short'});

// Notifications are optional; the chat works without them.
export function PushPanel({api}){
  const [env]=useState(()=>detectEnvironment());
  const [serverEnabled,setServerEnabled]=useState(null),[subscribed,setSubscribed]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  useEffect(()=>{
    let alive=true;
    (async()=>{
      try{const cfg=await api('/api/push/config');if(alive)setServerEnabled(Boolean(cfg.enabled));}catch{}
      try{const sub=await currentSubscription();if(alive)setSubscribed(Boolean(sub)&&env.permission==='granted');}catch{}
    })();
    return()=>{alive=false;};
  },[api,env.permission]);
  const advice=pushAdvice({...env,serverEnabled:serverEnabled===null?undefined:serverEnabled});
  async function toggle(){
    setBusy(true);setError('');
    try{if(subscribed){await disablePush(api);setSubscribed(false);}else{await enablePush(api);setSubscribed(true);}}
    catch(e){setError(e.message);}
    finally{setBusy(false);}
  }
  if(advice==='unavailable')return null;
  if(advice==='install')return <Alert type="info" showIcon className="!mb-4" title={t('รับแจ้งเตือนบน iPhone')} description={<div><Paragraph className="!mb-1">{t('เปิดเว็บนี้ใน Safari กดปุ่มแชร์ แล้วเลือก "เพิ่มไปยังหน้าจอโฮม" จากนั้นเปิดจากไอคอนบนหน้าจอโฮมและกดเปิดการแจ้งเตือนที่หน้านี้')}</Paragraph><Text type="secondary">{t('ต้องใช้ iOS 16.4 ขึ้นไป')}</Text></div>}/>;
  if(advice==='unsupported')return <Alert type="info" showIcon className="!mb-4" title={t('เบราว์เซอร์นี้ยังไม่รองรับการแจ้งเตือน')}/>;
  if(advice==='blocked')return <Alert type="warning" showIcon className="!mb-4" title={t('การแจ้งเตือนถูกปิดอยู่ในการตั้งค่าของเบราว์เซอร์')}/>;
  return <div className="mb-4 flex flex-wrap items-center gap-3"><Button icon={<BellOutlined/>} loading={busy} onClick={toggle} type={subscribed?'default':'primary'}>{subscribed?t('ปิดการแจ้งเตือนบนอุปกรณ์นี้'):t('เปิดการแจ้งเตือนบนอุปกรณ์นี้')}</Button><Text type="secondary">{t('แจ้งเตือนจะไม่แสดงเนื้อหาข้อความ')}</Text>{error&&<Text type="danger">{error}</Text>}</div>;
}

// mode 'student': thread of the signed-in team. mode 'ta': thread of `teamId`.
export default function Chat({api,mode,teamId,active=true,onRead,showPush=mode!=='ta',threadMaxHeight=420}){
  const base=mode==='ta'?`/api/admin/chat/${encodeURIComponent(teamId)}`:'/api/chat';
  const [messages,setMessages]=useState([]),[loaded,setLoaded]=useState(false),[text,setText]=useState(''),[sending,setSending]=useState(false),[error,setError]=useState('');
  const lastId=useRef(0),bottom=useRef(null),composing=useRef(false);
  const mine=role=>mode==='ta'?role==='ta':role==='student';
  const merge=useCallback(incoming=>{
    if(!incoming.length)return false;
    setMessages(old=>{const seen=new Set(old.map(m=>m.id));return [...old,...incoming.filter(m=>!seen.has(m.id))];});
    lastId.current=Math.max(lastId.current,...incoming.map(m=>m.id));
    return true;
  },[]);
  const load=useCallback(async()=>{
    try{const data=await api(`${base}?after=${lastId.current}`);merge(data.messages);setError('');if(onRead)onRead();}
    catch(e){if(e.name!=='AuthRedirect')setError(e.message);}
    finally{setLoaded(true);}
  },[api,base,merge,onRead]);
  useEffect(()=>{setMessages([]);lastId.current=0;setLoaded(false);},[base]);
  useEffect(()=>{
    if(!active)return;
    load();
    const timer=setInterval(()=>{if(!document.hidden)load();},POLL_MS);
    const onVisible=()=>{if(!document.hidden)load();};
    document.addEventListener('visibilitychange',onVisible);
    return()=>{clearInterval(timer);document.removeEventListener('visibilitychange',onVisible);};
  },[active,load]);
  useEffect(()=>{bottom.current?.scrollIntoView?.({block:'end'});},[messages.length]);
  async function send(){
    const body=text.trim();
    if(!body||sending)return;
    setSending(true);setError('');
    try{const data=await api(base,{body});merge([data.message]);setText('');if(onRead)onRead();}
    catch(e){setError(e.message);}
    finally{setSending(false);}
  }
  return <div>
    {showPush&&<PushPanel api={api}/>}
    <div className="chat-thread" role="log" aria-live="polite" style={{maxHeight:threadMaxHeight,minHeight:200,overflowY:'auto',padding:'4px 2px'}}>
      {loaded&&messages.length===0&&<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={mode==='ta'?t('ยังไม่มีข้อความจากกลุ่มนี้'):t('ยังไม่มีข้อความ ถามอะไร TA ได้เลย')}/>}
      {messages.map(m=><div key={m.id} style={{display:'flex',justifyContent:mine(m.role)?'flex-end':'flex-start',margin:'6px 0'}}>
        <div style={{maxWidth:'80%',background:mine(m.role)?'#2455a4':'#eef2f7',color:mine(m.role)?'#fff':'#243247',borderRadius:12,padding:'8px 12px'}}>
          <div style={{fontSize:12,opacity:.75,marginBottom:2}}>{m.role==='ta'?t('TA'):m.sender} · {stamp(m.created_at)}</div>
          <div style={{whiteSpace:'pre-wrap',wordBreak:'break-word'}}>{m.body}</div>
        </div>
      </div>)}
      <div ref={bottom}/>
    </div>
    {error&&<Alert type="error" showIcon className="!my-3" title={error}/>}
    <Space.Compact className="!mt-3 !flex">
      <Input.TextArea aria-label={t('พิมพ์ข้อความ')} value={text} maxLength={1000} autoSize={{minRows:1,maxRows:5}} placeholder={t('พิมพ์ข้อความ (Enter เพื่อส่ง, Shift+Enter ขึ้นบรรทัดใหม่)')}
        onChange={e=>setText(e.target.value)} onCompositionStart={()=>{composing.current=true;}} onCompositionEnd={()=>{composing.current=false;}}
        onPressEnter={e=>{if(!e.shiftKey&&!composing.current&&!e.nativeEvent?.isComposing){e.preventDefault();send();}}}/>
      <Button type="primary" icon={<SendOutlined/>} loading={sending} disabled={!text.trim()} onClick={send}>{t('ส่ง')}</Button>
    </Space.Compact>
    {mode!=='ta'&&<Paragraph type="secondary" className="!mt-3 !mb-0">{t('TA เห็นทุกข้อความในห้องนี้ ห้ามส่งรหัสผ่านหรือค่า secret')}</Paragraph>}
  </div>;
}
