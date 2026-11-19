// Pure sequencing helpers for status polling (no React, no network).
export const FAST_POLL_MS=2000,SLOW_POLL_MS=30000;
// Slow down once nothing is expected to change: finished resources with no GitHub link in flight, or a failed job.
export function pollInterval(activation){
 if(!activation)return FAST_POLL_MS;
 const linking=activation.github_link_status==='queued'||activation.github_link_status==='running';
 if(activation.status==='failed')return SLOW_POLL_MS;
 if(activation.status==='ready'&&!linking)return SLOW_POLL_MS;
 return FAST_POLL_MS;
}
// begin() returns null when a poll tick must be skipped (a request is already in flight).
// force:true (user action, tab became visible) aborts the old request; only the newest id is ever current.
export function createRequestGate(){
 let latest=0,inFlight=false,controller=null;
 return {
  begin(force=false){
   if(inFlight&&!force)return null;
   if(controller)controller.abort();
   controller=new AbortController();inFlight=true;latest+=1;
   return {id:latest,signal:controller.signal};
  },
  isCurrent(id){return id===latest;},
  finish(id){if(id===latest){inFlight=false;controller=null;}},
  get inFlight(){return inFlight;},
  abort(){if(controller)controller.abort();inFlight=false;latest+=1;controller=null;},
 };
}
