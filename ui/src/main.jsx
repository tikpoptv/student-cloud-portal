import React, {useState,useEffect,useCallback,useRef} from 'react';
import {createRoot} from 'react-dom/client';
import {ConfigProvider,App as AntApp,Button,Card,Alert,Tag,Typography,Form,Input,Steps,Progress,Descriptions,Table,Tabs,Space,Spin,Result,Divider,Tooltip,Badge} from 'antd';
import {CloudOutlined,GoogleOutlined,GithubOutlined,ArrowRightOutlined,LogoutOutlined,CheckCircleOutlined,DatabaseOutlined,AppstoreOutlined,SafetyCertificateOutlined,DownloadOutlined,ReloadOutlined,ExportOutlined,FileTextOutlined,ExperimentOutlined,TeamOutlined,DeploymentUnitOutlined,InfoCircleOutlined,GlobalOutlined,RocketOutlined,MessageOutlined} from '@ant-design/icons';
import thTH from 'antd/locale/th_TH';
import enUS from 'antd/locale/en_US';
import {t,teamName,initialLanguage,setLanguage,getLanguage} from './i18n.js';
import './style.css';
import RepoReview from './RepoReview.jsx';
import GroupResources from './GroupResources.jsx';
import FinalProjectKit from './FinalProjectKit.jsx';
import PortalHeader from './PortalHeader.jsx';
import ErrorPage from './ErrorPage.jsx';
import AdminDashboard from './AdminDashboard.jsx';
import ResourceActivation from './ResourceActivation.jsx';
import ActivationProgress from './ActivationProgress.jsx';
import Chat from './Chat.jsx';
import {cleanupBeforeLogout} from './push.js';
import {activationStatus,estimateServerNow} from './activation-status.js';
import {createRequestGate,pollInterval} from './activation-poll.js';
const {Title,Text,Paragraph}=Typography;
const boot=JSON.parse(document.getElementById('root').dataset.bootstrap);
async function api(path,data,signal){
  const res=await fetch(path,data===undefined?{signal,headers:{'Accept-Language':getLanguage()}}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':boot.csrf,'Accept-Language':getLanguage()},body:JSON.stringify(data)});
  // 401 means the session ended: go to the login page and always throw, so callers never read fields of an undefined result.
  if(res.status===401){location.assign('/');throw Object.assign(new Error(t("เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่")),{name:'AuthRedirect',status:401});}
  let body;try{body=await res.json();}catch(e){if(e?.name==='AbortError')throw e;throw new Error(t("เชื่อมต่อระบบไม่สำเร็จ กรุณาลองใหม่"));}
  if(!res.ok)throw new Error(body.error_source||body.error||t("ดำเนินการไม่สำเร็จ"));return body;
}
function PostForm({action,children,onSubmit}){return <form method="post" action={action} onSubmit={onSubmit}><input type="hidden" name="csrf" value={boot.csrf}/>{children}</form>;}
function Portal({language,onLanguage}){
  const [data,setData]=useState(null),[fetchFailed,setFetchFailed]=useState(false),[actionError,setActionError]=useState(''),[busy,setBusy]=useState(false),[tab,setTab]=useState('overview'),[receivedAt,setReceivedAt]=useState(Date.now());
  const [unread,setUnread]=useState(0);
  const clearUnread=useCallback(()=>setUnread(0),[]);
  useEffect(()=>{
    if(!boot.team||tab==='chat')return;
    let alive=true;
    const poll=async()=>{if(document.hidden)return;try{const d=await api('/api/chat/unread');if(alive)setUnread(d.unread||0);}catch{}};
    poll();const timer=setInterval(poll,30000);
    return()=>{alive=false;clearInterval(timer);};
  },[tab]);
  const [form]=Form.useForm();const {message}=AntApp.useApp();
  const gate=useRef(null);if(!gate.current)gate.current=createRequestGate();
  // fetchFailed is only about reading /api/status; actionError is only about a user action (activate/reset).
  const refresh=useCallback(async(force=false)=>{
    const req=gate.current.begin(force===true);if(!req)return; // a request is still in flight: skip this tick
    try{const d=await api('/api/status',undefined,req.signal);if(!gate.current.isCurrent(req.id))return;if(d){setData(d);setReceivedAt(Date.now());}setFetchFailed(false);}
    catch(e){if(e?.name==='AbortError'||e?.name==='AuthRedirect'||!gate.current.isCurrent(req.id))return;setFetchFailed(true);}
    finally{gate.current.finish(req.id);}
  },[language]);
  const interval=pollInterval(data?.activation);
  useEffect(()=>{if(!boot.team)return;refresh(true);},[refresh]);
  useEffect(()=>{if(!boot.team)return;
    const timer=setInterval(()=>{if(!document.hidden)refresh();},interval);
    const visible=()=>{if(!document.hidden)refresh(true);};document.addEventListener('visibilitychange',visible);
    return()=>{clearInterval(timer);document.removeEventListener('visibilitychange',visible);};},[refresh,interval]);
  useEffect(()=>()=>gate.current.abort(),[]);
  async function activate(values){setBusy(true);setActionError('');try{await api('/api/activate',values);await refresh(true);message.success(t(boot.preview?"เริ่มเตรียมแผนทดลองแล้ว":"ส่งคำขอเตรียมทรัพยากรแล้ว"));}catch(e){setActionError(e.message);}finally{setBusy(false);}}
  async function reset(){setBusy(true);setActionError('');try{await api('/api/preview/reset',{});setTab('repo');form.resetFields();await refresh(true);}catch(e){setActionError(e.message);}finally{setBusy(false);}}
  const a=data?.activation,ready=a?.status==='ready',preview=a?a.mode==='preview':boot.preview;
  const judged=a?activationStatus(a,data?.progress,estimateServerNow(data?.server_time,receivedAt,Date.now()),!fetchFailed):null;
  const uncertain=Boolean(judged?.stale);
  const status=uncertain?t("ยังยืนยันความคืบหน้าล่าสุดไม่ได้"):a?.status==='failed'?t("เตรียมทรัพยากรไม่สำเร็จ"):ready?t(preview?"แผนทดลองพร้อมแล้ว":"ทรัพยากรพร้อมสำหรับ deploy"):a?t("กำลังดำเนินการ"):t("ยังไม่เริ่ม");
  const repoReview=<RepoReview api={api} activation={a} team={boot.team} language={language} preview={boot.preview} variables={a?.outputs?.github_variables} onActivate={async values=>{await api('/api/activate',values);await refresh(true);setTab('overview');}} onStatus={()=>setTab('overview')} onGoTab={setTab}/>;
  const overview=<div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_300px]"><div className="space-y-5"><Card className="team-card" title={<Space><TeamOutlined/><span>{t("ข้อมูลกลุ่ม")}</span></Space>} extra={<Tag icon={<CheckCircleOutlined/>} color="blue">{boot.preview?t("บัญชีทดลอง"):t("ยืนยันบัญชีแล้ว")}</Tag>}><div className="mb-6"><Title level={4} className="!mb-1">{teamName(boot.team?.name)}</Title><Text type="secondary">{boot.team?.email}</Text></div><Descriptions size="small" column={{xs:1,sm:2,lg:2}} items={[{key:'p',label:'Project ID',children:<Text code>cpe-se-course-2026</Text>},{key:'prefix',label:t("Prefix ของกลุ่ม"),children:<Tag color="geekblue">{boot.team?.prefix}</Tag>},{key:'r',label:'Region',children:'asia-southeast1'},{key:'repo',label:'Repository',children:a?<Text className="break-all">{a.repo}</Text>:t("ยังไม่ระบุ")}]}/></Card>
  <Card title={a?t("สถานะการเตรียมระบบ"):t("เริ่มเตรียมพื้นที่ของกลุ่ม")} extra={a?<Tag color={a?.status==='failed'?'error':uncertain?'warning':ready?'success':'processing'}>{status}</Tag>:<Tag>{t("หนึ่งชุดต่อกลุ่ม")}</Tag>}>
  {(!a||(!boot.preview&&a.mode==='preview'))?<ResourceActivation busy={busy} onActivate={activate} onReview={()=>setTab('repo')}/>:<><ActivationProgress activation={a} progress={data?.progress} serverTime={data?.server_time} receivedAt={receivedAt} connected={!fetchFailed} steps={boot.steps} language={language} preview={preview} onRefresh={()=>refresh(true)} onRetryLink={()=>activate({repo:a.repo})} busy={busy}/>{(judged?.canRetry||(!boot.preview&&a.mode==='preview'))&&<Button className="!mt-4" type="primary" loading={busy} onClick={()=>activate(a.repo?{repo:a.repo}:{resources_only:true})}>{t("Activate / ส่งงานเดิมเข้าคิวอีกครั้ง")}</Button>}{ready&&<Alert className="!mt-5" type="success" showIcon title={t("ทำ Final Project? ไปที่แท็บ Final Project Kit")} action={<Button size="small" type="primary" icon={<RocketOutlined/>} onClick={()=>setTab('final')}>{t("เปิด Final Project Kit")}</Button>}/>}{ready&&<div className="mt-5 border-t border-slate-100 pt-5"><Button type="primary" icon={<ArrowRightOutlined/>} onClick={()=>setTab(a.repo?'repo':'resources')}>{t(a.repo?"เปิดคู่มือและทำต่อตามขั้นตอน":"ดูทรัพยากรและข้อมูลสำหรับ deploy")}</Button>{boot.preview&&<Button className="!ml-2" type="text" icon={<ReloadOutlined/>} loading={busy} onClick={reset}>{t("เริ่มทดลองใหม่")}</Button>}</div>}</>}
  </Card></div><aside className="space-y-5"><Card title={t("ก่อนเริ่ม Activate")} size="small"><div className="space-y-4 py-2">{[t("ใช้ Gmail ที่ TA อนุมัติสำหรับกลุ่ม"),t("ทรัพยากรแยกตาม prefix ของกลุ่ม"),t("กลุ่มต้อง build และ deploy แอปเอง")].map(t=><div key={t} className="flex items-start gap-3"><CheckCircleOutlined className="mt-1 text-blue-600"/><Text>{t}</Text></div>)}</div><Divider className="!my-4"/><Button type="link" className="!px-0" href="https://console.cloud.google.com/?project=cpe-se-course-2026" target="_blank" rel="noopener" icon={<ExportOutlined/>}>Google Cloud Console</Button></Card>{a?.repo&&<Card size="small" className="guide-card"><Text className="eyebrow">STUDENT GUIDE</Text><Title level={5} className="!mt-3">{t("คุณยังได้ deploy แอปเอง")}</Title><Paragraph type="secondary">{t("ระบบช่วยเตรียม infrastructure และสิทธิ์ให้ จากนั้นกลุ่มทำ build image, migration และ deploy ต่อเอง")}</Paragraph><Tag color="blue">Episode 5.3 / 6.4</Tag><div className="mt-4"><Button type="link" className="!px-0" onClick={()=>setTab("repo")} icon={<FileTextOutlined/>}>{t("ตรวจไฟล์และขั้นตอนถัดไป")}</Button></div></Card>}<div className="px-2 text-sm leading-7 text-slate-500"><InfoCircleOutlined className="mr-2"/>{t("หากพบปัญหา ส่ง Gmail และภาพหน้าจอให้ทีม TA ของรายวิชา")}</div></aside></div>;
  return <div className="min-h-screen bg-slate-50"><PortalHeader language={language} onLanguage={onLanguage}>{boot.team&&<PostForm action="/logout" onSubmit={e=>cleanupBeforeLogout(e,api)}><Button htmlType="submit" type="text" icon={<LogoutOutlined/>}>{t("ออกจากระบบ")}</Button></PostForm>}</PortalHeader>
  {boot.preview&&<div className="preview-strip"><ExperimentOutlined/><span><b>{t("โหมดทดลอง")}</b><span className="mx-2">·</span>{t("การเปิดทรัพยากรของกลุ่มยังเป็นการจำลอง")}</span></div>}
  {!boot.team?<main className="landing-shell"><div className="grid items-center gap-10 lg:grid-cols-[1.15fr_1fr]"><section><Tag color="blue" bordered={false}>CPE334 · LAB 5 & LAB 6</Tag><h1 className="landing-title">{t("พื้นที่ Google Cloud")}<br/>{t("สำหรับโปรเจกต์ของกลุ่ม")}</h1><p className="max-w-lg text-base leading-8 text-slate-500">{t("ยืนยันบัญชีที่ลงทะเบียนกับรายวิชา เพื่อเตรียมทรัพยากรและรับค่าตั้งต้นสำหรับ deploy แอปของกลุ่ม")}</p><div className="mt-9 grid max-w-lg grid-cols-3 gap-3">{[[<AppstoreOutlined/>,'Cloud Run',t("แอปของกลุ่ม")],[<DatabaseOutlined/>,'Cloud SQL',t("ฐานข้อมูล")],[<GithubOutlined/>,'GitHub Actions',t("เชื่อมต่อ CI/CD")]].map(([icon,title,desc])=><div className="feature-tile" key={title}>{icon}<strong>{title}</strong><span>{desc}</span></div>)}</div><div className="mt-8 flex items-start gap-3 text-sm leading-7 text-slate-500"><SafetyCertificateOutlined className="mt-1 text-blue-600"/><span>{t("ใช้ Gmail ของกลุ่มที่แจ้งไว้ในแบบฟอร์ม")}<br/>{t("ระบบเลือกกลุ่มและกำหนด prefix ให้โดยอัตโนมัติ")}</span></div></section><Card className="login-panel"><div className="mb-5 flex items-center justify-between"><span className="login-symbol"><TeamOutlined/></span><Tag>{t("สำหรับนักศึกษา")}</Tag></div><Title level={3}>{t("เข้าสู่พื้นที่ของกลุ่ม")}</Title><Paragraph type="secondary">{t("ใช้ Gmail ที่ลงชื่อแจ้งปัญหา Google Cloud")}<br/>{t("เพื่อยืนยันสิทธิ์เข้าใช้งาน")}</Paragraph><div className="mt-7"><Button size="large" block icon={<GoogleOutlined/>} href={boot.oauth_ready?'/auth/google':undefined} disabled={!boot.oauth_ready}>{t("เข้าสู่ระบบด้วย Google")}</Button>{(!boot.oauth_ready)&&<p className="mt-3 text-center text-xs text-slate-400">{t("กำลังเตรียมการเข้าสู่ระบบด้วย Google")}</p>}</div>{boot.demo_login&&<><Divider plain>{t("ทดลองระบบก่อนเปิดใช้งานจริง")}</Divider><PostForm action="/preview/login"><Button type="primary" size="large" block htmlType="submit" icon={<ArrowRightOutlined/>}>{t("เข้าสู่กลุ่มทดลอง")}</Button></PostForm></>}<div className="mt-6 border-t border-slate-100 pt-5 text-center text-xs text-slate-500"><SafetyCertificateOutlined className="mr-2"/>{t("ข้อมูลของกลุ่มจะแสดงให้เฉพาะบัญชีที่ได้รับสิทธิ์")}</div></Card></div><div className="mt-14 border-t border-slate-200 pt-8"><Steps items={[{title:t("ยืนยันบัญชี"),description:t("เข้าสู่ระบบด้วย Gmail ของกลุ่ม")},{title:t("เตรียมพื้นที่"),description:t("กด Activate ทรัพยากรอย่างเดียว หรือระบุ repo ก็ได้ (repo เป็นทางเลือก)")},{title:t("ดำเนินการต่อ"),description:t("นำค่าตั้งต้นไป deploy ตามไกด์")}]} current={-1}/></div></main>:<main className="dashboard-shell"><div className="mb-6 flex flex-wrap items-center justify-between gap-4"><div><div className="eyebrow mb-2">STUDENT WORKSPACE</div><Title level={2} className="!mb-2">{t("พื้นที่ทำงานของกลุ่ม")}</Title><Text type="secondary">{t("จัดเตรียมทรัพยากรและข้อมูลสำหรับ Lab 5 และ Lab 6")}</Text></div><Tag color={a?.status==='failed'?'error':uncertain?'warning':ready?'success':a?'processing':'default'}>{status}</Tag></div>{actionError&&<Alert type="error" showIcon closable onClose={()=>setActionError('')} className="!mb-5" title={t(actionError)}/>}{fetchFailed&&data&&<Alert type="warning" showIcon className="!mb-5" title={t("เชื่อมต่อระบบไม่สำเร็จ กรุณาลองใหม่")}/>}{!data?(fetchFailed?<Result status="warning" title={t("เชื่อมต่อระบบไม่สำเร็จ กรุณาลองใหม่")} subTitle={t("โหลดข้อมูลกลุ่มไม่สำเร็จ ยังไม่ทราบสถานะการเตรียมทรัพยากร")} extra={<Button type="primary" icon={<ReloadOutlined/>} onClick={()=>refresh(true)}>{t("ลองใหม่")}</Button>}/>:<div className="p-16 text-center"><Spin description={t("กำลังโหลดข้อมูลกลุ่ม")}/></div>):<Tabs activeKey={tab} onChange={setTab} items={[{key:'overview',label:<Space><AppstoreOutlined/>{t("เปิดทรัพยากรและดูสถานะ")}</Space>,children:overview},{key:'resources',label:<Space><DatabaseOutlined/>{t('ทรัพยากรของกลุ่ม')}</Space>,children:<GroupResources team={boot.team} activation={a} onOpenOverview={()=>setTab('overview')} onOpenKit={()=>setTab('final')}/>},{key:'final',label:<Space><RocketOutlined/>{t('Final Project Kit')}</Space>,children:<FinalProjectKit team={boot.team} activation={a} onOpenOverview={()=>setTab('overview')}/>},{key:'repo',label:<Space><GithubOutlined/>{t("Lab 5 · ตรวจ repo และดู diff")}</Space>,children:repoReview},{key:'chat',label:<Space><MessageOutlined/>{t("คุยกับ TA")}<Badge count={unread} size="small"/></Space>,children:<Card title={t("ข้อความถึง TA")}><Chat api={api} mode="student" active={tab==='chat'} onRead={clearUnread}/></Card>}]}/>}</main>}
  <footer className="portal-footer"><span>CPE334 · Department of Computer Engineering</span><span>Student Cloud Portal · 2026</span></footer></div>;
}
function LocalizedRoot(){
 const [language,updateLanguage]=useState(initialLanguage);
 setLanguage(language);
 useEffect(()=>{
   document.documentElement.lang=language;
   try{localStorage.setItem('student-cloud-language',language);}catch{}
   document.cookie=`portal_lang=${language}; Path=/; Max-Age=31536000; SameSite=Lax${location.protocol==='https:'?'; Secure':''}`;
 },[language]);
 function changeLanguage(next){
   const url=new URL(location.href);
   if(url.searchParams.has('lang')){url.searchParams.set('lang',next);history.replaceState(null,'',url);}
   setLanguage(next);updateLanguage(next);
 }
 return <ConfigProvider locale={language==='en'?enUS:thTH} theme={{token:{colorPrimary:'#2455a4',colorInfo:'#2455a4',borderRadius:8,colorBgLayout:'#f5f7fa',colorText:'#243247',colorTextSecondary:'#6c7788',fontFamily:'system-ui, -apple-system, Thonburi, sans-serif',fontSize:14},components:{Card:{headerFontSize:15},Button:{controlHeight:36},Tabs:{horizontalItemGutter:28}}}}><AntApp>{boot.error?<ErrorPage error={boot.error} language={language} onLanguage={changeLanguage} oauthReady={boot.oauth_ready}/>:boot.admin_email?<AdminDashboard api={api} boot={boot} language={language} onLanguage={changeLanguage}/>:<Portal language={language} onLanguage={changeLanguage}/>}</AntApp></ConfigProvider>;
}
createRoot(document.getElementById('root')).render(<LocalizedRoot/>);
