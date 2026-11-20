import React,{useEffect,useMemo,useState} from 'react';
import {Badge,Button,Empty,Input,Typography} from 'antd';
import {ArrowLeftOutlined,SearchOutlined,TeamOutlined} from '@ant-design/icons';
import Chat from './Chat.jsx';
import {buildInboxRows,timeAgo} from './inbox-utils.js';
import {t} from './i18n.js';
const {Text}=Typography;

export function useIsMobile(){
  const query='(max-width: 767px)';
  const [mobile,setMobile]=useState(()=>typeof window!=='undefined'&&Boolean(window.matchMedia)&&window.matchMedia(query).matches);
  useEffect(()=>{
    if(!window.matchMedia)return;
    const media=window.matchMedia(query);
    const update=()=>setMobile(media.matches);
    update();media.addEventListener('change',update);
    return()=>media.removeEventListener('change',update);
  },[]);
  return mobile;
}

const ago=seconds=>{
  const r=timeAgo(Math.floor(Date.now()/1000),seconds);
  return r.n===undefined?t(r.key):`${r.n} ${t(r.key)}`;
};

function Row({row,active,onOpen}){
  const unread=row.unread>0;
  const preview=row.hasThread?`${row.last_role==='ta'?t('คุณ')+': ':''}${row.last_body}`:t('ยังไม่เคยคุย กดเพื่อเริ่มข้อความ');
  return <button type="button" onClick={()=>onOpen(row.id)} aria-current={active?'true':undefined}
    style={{display:'flex',width:'100%',gap:12,alignItems:'center',textAlign:'left',padding:'12px 14px',border:0,borderBottom:'1px solid #eef1f5',cursor:'pointer',minHeight:64,
      background:active?'#e8f0fb':unread?'#f4f8ff':'#fff'}}>
    <span aria-hidden style={{width:10,height:10,borderRadius:'50%',flex:'none',background:unread?'#2455a4':'transparent'}}/>
    <span style={{flex:1,minWidth:0}}>
      <span style={{display:'flex',justifyContent:'space-between',gap:8}}>
        <span style={{fontWeight:unread?700:500,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap',color:'#243247'}}>{row.name}</span>
        {row.hasThread&&<span style={{fontSize:12,color:unread?'#2455a4':'#8a94a3',flex:'none'}}>{ago(row.last_at)}</span>}
      </span>
      <span style={{display:'block',fontSize:13,color:unread?'#243247':'#6c7788',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap',fontWeight:unread?600:400}}>{preview}</span>
    </span>
    {unread&&<Badge count={row.unread} color="#2455a4"/>}
  </button>;
}

// Inbox of team conversations. Desktop: list and conversation side by side. Phone: one at a time, with a back button.
export default function Inbox({api,teams,threads,onRead,onOpenTeam,isMobile}){
  const [selected,setSelected]=useState(null),[query,setQuery]=useState('');
  const rows=useMemo(()=>buildInboxRows(teams,threads,query),[teams,threads,query]);
  const team=(teams||[]).find(x=>x.id===selected);
  const list=<div style={{border:'1px solid #e5e9f0',borderRadius:12,background:'#fff',overflow:'hidden'}}>
    <div style={{padding:10,borderBottom:'1px solid #eef1f5'}}><Input allowClear size="large" prefix={<SearchOutlined/>} placeholder={t('ค้นหากลุ่ม เพื่อเริ่มข้อความใหม่')} value={query} onChange={e=>setQuery(e.target.value)} aria-label={t('ค้นหากลุ่ม')}/></div>
    <div style={{maxHeight:isMobile?'calc(100dvh - 300px)':620,overflowY:'auto'}}>
      {rows.length===0?<Empty style={{padding:32}} image={Empty.PRESENTED_IMAGE_SIMPLE} description={query?t('ไม่พบกลุ่มที่ค้นหา'):t('ยังไม่มีข้อความจากนักศึกษา ค้นหากลุ่มเพื่อเริ่มคุยได้')}/>
        :rows.map(row=><Row key={row.id} row={row} active={row.id===selected} onOpen={setSelected}/>)}
    </div>
  </div>;
  const conversation=team?<div style={{border:'1px solid #e5e9f0',borderRadius:12,background:'#fff',padding:isMobile?12:16}}>
    <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:12}}>
      {isMobile&&<Button type="text" size="large" icon={<ArrowLeftOutlined/>} onClick={()=>setSelected(null)} aria-label={t('กลับไปรายการข้อความ')}/>}
      <div style={{flex:1,minWidth:0}}><div style={{fontWeight:700,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{team.name}</div><Text type="secondary" style={{fontSize:12}}>{team.email}</Text></div>
      <Button icon={<TeamOutlined/>} onClick={()=>onOpenTeam(team.id)}>{isMobile?null:t('ข้อมูลกลุ่ม')}</Button>
    </div>
    <Chat api={api} mode="ta" teamId={team.id} active showPush={false} onRead={onRead} threadMaxHeight={isMobile?'calc(100dvh - 330px)':'calc(100vh - 460px)'}/>
  </div>:<div style={{border:'1px dashed #cfd6e0',borderRadius:12,background:'#fff',padding:40}}><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('เลือกกลุ่มทางซ้ายเพื่ออ่านและตอบข้อความ')}/></div>;
  if(isMobile)return selected&&team?conversation:list;
  return <div style={{display:'grid',gridTemplateColumns:'minmax(280px,360px) minmax(0,1fr)',gap:16,alignItems:'start'}}>{list}{conversation}</div>;
}
