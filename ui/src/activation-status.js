// Single source of truth for how a job (and its optional GitHub link) is judged. Used by the home badge
// and by ActivationProgress so the two can never disagree.
export const WORKER_STALE_AFTER=180;   // seconds without a worker checkpoint
export const QUEUE_STALE_AFTER=600;    // seconds queued without any worker claim
export function estimateServerNow(serverTime,receivedAt,nowMs){
 return (serverTime||0)+Math.max(0,Math.floor((nowMs-receivedAt)/1000));
}
function judge(heartbeat,queuedAt,queued,serverTime,fallbackAt){
 const age=heartbeat?Math.max(0,serverTime-heartbeat):null;
 const queueStuck=queued&&!heartbeat&&queuedAt!=null&&serverTime-queuedAt>QUEUE_STALE_AFTER;
 const silent=age!==null?age>WORKER_STALE_AFTER:(!queued&&fallbackAt!=null&&serverTime-fallbackAt>WORKER_STALE_AFTER);
 return {age,queueStuck,silent};
}
export function activationStatus(activation,progress,serverTime,connected=true){
 const done=Math.max(0,Math.min(6,Number(activation?.step)||0));
 const heartbeat=progress?.worker_last_seen_at||null;
 const ready=activation?.status==='ready',failed=activation?.status==='failed',queued=activation?.status==='queued';
 const j=judge(heartbeat,activation?.updated_at,queued,serverTime,activation?.updated_at||activation?.created_at);
 const stale=!ready&&!failed&&(!connected||j.silent||j.queueStuck);
 // GitHub link sub-state: resources stay `ready`; this judges only the link.
 const ls=activation?.github_link_status||null;
 const linkActive=ready&&(ls==='queued'||ls==='running');
 const lj=judge(heartbeat,activation?.github_link_at,ls==='queued',serverTime,activation?.github_link_at);
 const link={state:ls,active:linkActive,failed:ready&&ls==='failed',stale:linkActive&&(!connected||lj.silent||lj.queueStuck),
  canRetry:ready&&(ls==='failed'||(linkActive&&lj.queueStuck)),waitingQueue:linkActive&&ls==='queued'&&!heartbeat};
 const end=ready||failed?activation?.updated_at:serverTime;
 return {done,ready,failed,stale,queueStuck:j.queueStuck&&!ready&&!failed,
  waitingQueue:queued&&!heartbeat,
  canRetry:failed||(queued&&j.queueStuck),
  terminal:ready||failed,link,
  elapsed:Math.max(0,end-activation.created_at),
  stageElapsed:Math.max(0,end-(progress?.step_started_at||activation.created_at)),
  heartbeat,age:j.age};
}
export function duration(seconds,language){
 const n=Math.max(0,Math.floor(seconds));
 return new Intl.NumberFormat(language==='en'?'en':'th',{minimumIntegerDigits:2,useGrouping:false}).format(Math.floor(n/60))+':'+new Intl.NumberFormat(language==='en'?'en':'th',{minimumIntegerDigits:2,useGrouping:false}).format(n%60);
}
