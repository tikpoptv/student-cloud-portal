// Pure helpers for the TA inbox (kept out of the component so they can be unit tested).

export function timeAgo(now,then){
  const s=Math.max(0,now-then);
  if(s<60)return {key:'เมื่อสักครู่'};
  if(s<3600)return {n:Math.floor(s/60),key:'นาทีที่แล้ว'};
  if(s<86400)return {n:Math.floor(s/3600),key:'ชั่วโมงที่แล้ว'};
  return {n:Math.floor(s/86400),key:'วันที่แล้ว'};
}

const byName=(a,b)=>String(a.name).localeCompare(String(b.name),'th');

// Rows of the inbox, in the order they are shown:
//   people who wrote and are still unread -> newest first
//   then everyone else with a conversation -> newest first
//   with a search query: teams without any conversation come last, so a TA can start one.
export function buildInboxRows(teams,threads,query=''){
  const byTeam=new Map((threads||[]).map(thread=>[thread.team_id,thread]));
  const q=String(query||'').trim().toLowerCase();
  const source=q?(teams||[]).filter(team=>`${team.name} ${team.email} ${team.prefix}`.toLowerCase().includes(q)):(teams||[]).filter(team=>byTeam.has(team.id));
  const rows=source.map(team=>{
    const thread=byTeam.get(team.id);
    return {id:team.id,name:team.name,email:team.email,prefix:team.prefix,hasThread:Boolean(thread),unread:thread?.unread||0,last_at:thread?.last_at||0,last_role:thread?.last_role||'',last_body:thread?.last_body||''};
  });
  return rows.sort((a,b)=>(b.unread>0)-(a.unread>0)||(b.hasThread-a.hasThread)||b.last_at-a.last_at||byName(a,b));
}
