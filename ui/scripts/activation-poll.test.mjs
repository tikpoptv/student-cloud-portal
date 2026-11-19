import test from 'node:test';import assert from 'node:assert/strict';
import {createRequestGate,pollInterval,FAST_POLL_MS,SLOW_POLL_MS} from '../src/activation-poll.js';
test('a tick is skipped while a request is in flight and resumes after it finishes',()=>{
 const g=createRequestGate();const a=g.begin();
 assert.equal(g.begin(),null);assert.equal(g.inFlight,true);
 g.finish(a.id);assert.equal(g.inFlight,false);assert.ok(g.begin());
});
test('a forced request aborts the old one and a stale response is ignored',()=>{
 const g=createRequestGate();const old=g.begin(),fresh=g.begin(true);
 assert.equal(old.signal.aborted,true);assert.equal(fresh.signal.aborted,false);
 assert.equal(g.isCurrent(old.id),false);assert.equal(g.isCurrent(fresh.id),true);
 g.finish(old.id);assert.equal(g.inFlight,true); // the old request finishing must not release the new one
 g.finish(fresh.id);assert.equal(g.inFlight,false);
 assert.ok(fresh.id>old.id);
});
test('abort on unmount invalidates the pending request',()=>{
 const g=createRequestGate();const r=g.begin();g.abort();
 assert.equal(r.signal.aborted,true);assert.equal(g.isCurrent(r.id),false);assert.equal(g.inFlight,false);
});
test('polling slows once work is finished and speeds up while a GitHub link is running',()=>{
 assert.equal(pollInterval(null),FAST_POLL_MS);
 assert.equal(pollInterval({status:'queued'}),FAST_POLL_MS);
 assert.equal(pollInterval({status:'running'}),FAST_POLL_MS);
 assert.equal(pollInterval({status:'ready'}),SLOW_POLL_MS);
 assert.equal(pollInterval({status:'ready',github_link_status:'running'}),FAST_POLL_MS);
 assert.equal(pollInterval({status:'ready',github_link_status:'failed'}),SLOW_POLL_MS);
 assert.equal(pollInterval({status:'failed'}),SLOW_POLL_MS);
});
