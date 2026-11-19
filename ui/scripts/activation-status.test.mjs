import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';
import {activationStatus,duration,estimateServerNow} from '../src/activation-status.js';
const job={status:'running',step:1,created_at:100,updated_at:700};
test('database wait counts completed stages without estimating an ETA',()=>{
 const m=activationStatus(job,{worker_last_seen_at:700,step_started_at:130},710);
 assert.equal(m.done,1);assert.equal(m.stale,false);assert.equal(m.elapsed,610);assert.equal(m.stageElapsed,580);assert.equal(m.age,10);
 assert.equal(duration(m.elapsed,'en'),'10:10');
});
test('a fresh page does not replace a missing or stale worker heartbeat',()=>{
 assert.equal(activationStatus(job,{worker_last_seen_at:300},710).stale,true);
 assert.equal(activationStatus(job,{worker_last_seen_at:700},710,false).stale,true);
 const queued=activationStatus({...job,status:'queued'},{worker_last_seen_at:null},710);
 assert.equal(queued.waitingQueue,true);assert.equal(queued.heartbeat,null);assert.equal(queued.stale,false);
});
test('completed and failed jobs stop their timers and do not show a busy worker',()=>{
 for(const status of ['ready','failed']){
  const m=activationStatus({...job,status,step:status==='ready'?6:1},{step_started_at:130},10000,false);
  assert.equal(m.elapsed,600);assert.equal(m.stale,false);assert.equal(m.ready,status==='ready');assert.equal(m.failed,status==='failed');
 }
});

// ---- one shared judgement for badge and progress screen ----
const base={created_at:100,updated_at:100};
test('queued: waiting for a worker is not stale until the queue has been stuck for 10 minutes',()=>{
 const q={...base,status:'queued',step:0};
 let m=activationStatus(q,{worker_last_seen_at:null},400);
 assert.equal(m.waitingQueue,true);assert.equal(m.stale,false);assert.equal(m.canRetry,false);
 m=activationStatus(q,{worker_last_seen_at:null},100+601);
 assert.equal(m.stale,true);assert.equal(m.queueStuck,true);assert.equal(m.canRetry,true);
 assert.equal(activationStatus(q,{worker_last_seen_at:null},100+600).stale,false);
});
test('running with a fresh heartbeat is healthy and cannot be re-sent',()=>{
 const m=activationStatus({...base,status:'running',step:1},{worker_last_seen_at:1000},1100);
 assert.equal(m.stale,false);assert.equal(m.canRetry,false);assert.equal(m.age,100);
});
test('running with a heartbeat older than 180s is stale',()=>{
 const m=activationStatus({...base,status:'running',step:1},{worker_last_seen_at:1000},1181);
 assert.equal(m.stale,true);assert.equal(m.canRetry,false);
 assert.equal(activationStatus({...base,status:'running',step:1},{worker_last_seen_at:1000},1180).stale,false);
});
test('running with a null heartbeat judges by last update instead of trusting the page',()=>{
 const job={created_at:100,updated_at:1000,status:'running',step:1};
 assert.equal(activationStatus(job,{worker_last_seen_at:null},1100).stale,false);
 assert.equal(activationStatus(job,{worker_last_seen_at:null},1181).stale,true);
 assert.equal(activationStatus(job,null,1181).stale,true);
});
test('failed offers retry and never looks stale; ready is terminal',()=>{
 const f=activationStatus({...base,status:'failed',step:2,updated_at:200},{},9999,false);
 assert.equal(f.failed,true);assert.equal(f.stale,false);assert.equal(f.canRetry,true);assert.equal(f.terminal,true);
 const r=activationStatus({...base,status:'ready',step:6,updated_at:200},{},9999,false);
 assert.equal(r.ready,true);assert.equal(r.stale,false);assert.equal(r.canRetry,false);assert.equal(r.elapsed,100);
});
test('disconnected page marks unfinished work as unconfirmed but not finished work',()=>{
 assert.equal(activationStatus({...base,status:'running',step:1},{worker_last_seen_at:1000},1010,false).stale,true);
 assert.equal(activationStatus({...base,status:'queued',step:0},{},110,false).stale,true);
 assert.equal(activationStatus({...base,status:'queued',step:0},{},110,false).canRetry,false);
});
test('a GitHub link keeps the resources ready and is judged separately',()=>{
 const ready={...base,status:'ready',step:6,updated_at:500,github_link_status:'queued',github_link_at:1000};
 let m=activationStatus(ready,{worker_last_seen_at:null},1100);
 assert.equal(m.ready,true);assert.equal(m.stale,false);assert.equal(m.link.active,true);assert.equal(m.link.waitingQueue,true);assert.equal(m.link.canRetry,false);
 assert.equal(activationStatus(ready,{worker_last_seen_at:null},1601).link.canRetry,true);
 m=activationStatus({...ready,github_link_status:'running'},{worker_last_seen_at:1000},1200);
 assert.equal(m.link.stale,true);assert.equal(m.stale,false);
 m=activationStatus({...ready,github_link_status:'failed'},{},1100);
 assert.equal(m.ready,true);assert.equal(m.failed,false);assert.equal(m.link.failed,true);assert.equal(m.link.canRetry,true);
});
test('the home badge and the progress screen import the one shared function',()=>{
 const main=fs.readFileSync(new URL('../src/main.jsx',import.meta.url),'utf8');
 const progress=fs.readFileSync(new URL('../src/ActivationProgress.jsx',import.meta.url),'utf8');
 for(const src of [main,progress])assert.match(src,/activationStatus\(/);
 assert.doesNotMatch(main,/worker_last_seen_at/);
 assert.match(main,/import \{activationStatus[^}]*\} from '\.\/activation-status\.js'/);
});
test('progress is a step indicator without percentage semantics and its clock stops when finished',()=>{
 const progress=fs.readFileSync(new URL('../src/ActivationProgress.jsx',import.meta.url),'utf8');
 assert.doesNotMatch(progress,/<Progress[\s>]|aria-valuenow|percent=/);
 assert.match(progress,/activation-stepbar[^>]*aria-hidden/);
 assert.match(progress,/if\(!running\)return;/);
});
test('connection loss and action errors are separate states',()=>{
 const main=fs.readFileSync(new URL('../src/main.jsx',import.meta.url),'utf8');
 assert.doesNotMatch(main,/connected=\{!error\}|\bsetError\(/);
 assert.match(main,/connected=\{!fetchFailed\}/);assert.match(main,/setActionError\(e\.message\)/);
});
test('estimated server time follows the fetch time and never goes backwards',()=>{
 assert.equal(estimateServerNow(1000,5000,9500),1004);assert.equal(estimateServerNow(1000,5000,4000),1000);assert.equal(estimateServerNow(null,0,0),0);
});
