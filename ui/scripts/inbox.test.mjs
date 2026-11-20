import test from 'node:test';
import assert from 'node:assert/strict';
import {buildInboxRows,timeAgo} from '../src/inbox-utils.js';

const teams=[{id:'a',name:'Alpha',email:'a@gmail.com',prefix:'sa1'},{id:'b',name:'Bravo',email:'b@gmail.com',prefix:'sb2'},{id:'c',name:'Charlie',email:'c@gmail.com',prefix:'sc3'},{id:'d',name:'Delta',email:'d@gmail.com',prefix:'sd4'}];
const threads=[
 {team_id:'a',last_at:100,last_role:'ta',last_body:'answer',unread:0},
 {team_id:'b',last_at:50,last_role:'student',last_body:'old question',unread:2},
 {team_id:'c',last_at:300,last_role:'student',last_body:'new question',unread:1},
 {team_id:'ghost',last_at:999,last_role:'student',last_body:'team was deleted',unread:5},
];

test('unread conversations come first (newest first), then read ones newest first; unknown teams are dropped',()=>{
 assert.deepEqual(buildInboxRows(teams,threads).map(r=>r.id),['c','b','a']);
});

test('a team that never talked is not listed without a search, and rows carry the preview',()=>{
 const rows=buildInboxRows(teams,threads);
 assert.equal(rows.some(r=>r.id==='d'),false);
 assert.deepEqual([rows[0].unread,rows[0].last_body,rows[2].last_role],[1,'new question','ta']);
});

test('search finds any team by name, email or prefix; teams without a conversation come last',()=>{
 assert.deepEqual(buildInboxRows(teams,threads,'  ').map(r=>r.id),['c','b','a']);
 assert.deepEqual(buildInboxRows(teams,threads,'a').map(r=>r.id),['c','b','a','d']);
 assert.deepEqual(buildInboxRows(teams,threads,'SD4').map(r=>r.id),['d']);
 assert.deepEqual(buildInboxRows(teams,threads,'b@gmail').map(r=>r.id),['b']);
 assert.deepEqual(buildInboxRows(teams,threads,'nothing like this'),[]);
 const d=buildInboxRows(teams,threads,'delta')[0];
 assert.deepEqual([d.hasThread,d.unread,d.last_body],[false,0,'']);
});

test('ties are stable by name and missing inputs are tolerated',()=>{
 const two=[{id:'x',name:'Zed',email:'',prefix:''},{id:'y',name:'Amy',email:'',prefix:''}];
 assert.deepEqual(buildInboxRows(two,[],'').map(r=>r.id),[]);
 assert.deepEqual(buildInboxRows(two,[],'e').map(r=>r.id),['x']);
 assert.deepEqual(buildInboxRows(two,[],'m').map(r=>r.id),['y']);
 assert.deepEqual(buildInboxRows(two,[],'').length,0);
 assert.deepEqual(buildInboxRows(undefined,undefined),[]);
 const tie=[{team_id:'y',last_at:5,unread:0},{team_id:'x',last_at:5,unread:0}];
 assert.deepEqual(buildInboxRows(two,tie).map(r=>r.name),['Amy','Zed']);
});

test('timeAgo buckets',()=>{
 assert.deepEqual(timeAgo(1000,1000),{key:'เมื่อสักครู่'});
 assert.deepEqual(timeAgo(1000,990),{key:'เมื่อสักครู่'});
 assert.deepEqual(timeAgo(1000,1000+30),{key:'เมื่อสักครู่'});  // clock skew never goes negative
 assert.deepEqual(timeAgo(1000,1000-120),{n:2,key:'นาทีที่แล้ว'});
 assert.deepEqual(timeAgo(10000,10000-7300),{n:2,key:'ชั่วโมงที่แล้ว'});
 assert.deepEqual(timeAgo(1000000,1000000-3*86400),{n:3,key:'วันที่แล้ว'});
});
