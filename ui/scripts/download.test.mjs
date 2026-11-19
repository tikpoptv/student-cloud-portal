import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {filenameFromDisposition,fetchDownload,DownloadError} from '../src/download.js';
const msgs={network:'N',failed:'F',unauthorized:'U',notFound:'NF',unavailable:'SU'};
const resp=(status,{body,json,headers={}}={})=>({ok:status>=200&&status<300,status,headers:{get:k=>headers[k]??null},blob:async()=>new Blob([body??'x']),json:async()=>{if(json===undefined)throw new Error('not json');return json;}});
test('filename comes from Content-Disposition, fallback otherwise',()=>{
 assert.equal(filenameFromDisposition('attachment; filename=cpe334-project-kit-grp01.zip','x'),'cpe334-project-kit-grp01.zip');
 assert.equal(filenameFromDisposition('attachment; filename="a b.zip"','x'),'a b.zip');
 assert.equal(filenameFromDisposition("attachment; filename*=UTF-8''%E0%B8%81.zip",'x'),'ก.zip');
 assert.equal(filenameFromDisposition(null,'fallback.zip'),'fallback.zip');
});
test('success returns blob and server filename',async()=>{
 const r=await fetchDownload('/api/kit/download',{fetchImpl:async()=>resp(200,{headers:{'Content-Disposition':'attachment; filename=k.zip'}}),fallbackName:'f.zip',messages:msgs});
 assert.equal(r.filename,'k.zip');assert.ok(r.blob instanceof Blob);
});
test('errors never become files: 401, 404, 503 JSON, non-JSON and network failure',async()=>{
 const run=fetchImpl=>fetchDownload('/x',{fetchImpl,messages:msgs}).then(()=>assert.fail('should throw'),e=>e);
 let e=await run(async()=>resp(401));assert.ok(e instanceof DownloadError);assert.equal(e.status,401);assert.equal(e.message,'U');
 e=await run(async()=>resp(404));assert.equal(e.status,404);assert.equal(e.message,'NF');
 e=await run(async()=>resp(503,{json:{error:'Project Kit ยังไม่พร้อมบนเซิร์ฟเวอร์ กรุณาแจ้ง TA'}}));assert.equal(e.status,503);assert.match(e.message,/Project Kit/);
 e=await run(async()=>resp(503));assert.equal(e.message,'SU');
 e=await run(async()=>resp(500));assert.equal(e.message,'F');
 e=await run(async()=>{throw new TypeError('offline');});assert.equal(e.status,0);assert.equal(e.message,'N');
});
test('404 shows the translated text, not the framework English body, unless the body is a known message',async()=>{
 const run=(fetchImpl,isKnown)=>fetchDownload('/x',{fetchImpl,messages:msgs,isKnown}).then(()=>assert.fail('should throw'),e=>e);
 const werk='The requested URL was not found on the server. If you entered the URL manually please check your spelling and try again.';
 let e=await run(async()=>resp(404,{json:{error:werk}}),()=>false);assert.equal(e.message,'NF');
 e=await run(async()=>resp(404,{json:{error:'Known message'}}),v=>v==='Known message');assert.equal(e.message,'Known message');
 e=await run(async()=>resp(503,{json:{error:'anything'}}),()=>false);assert.equal(e.message,'anything');
});
test('blob URL stays alive for 60 s',()=>{
 const d=fs.readFileSync(new URL('../src/download.js',import.meta.url),'utf8');
 assert.match(d,/revokeObjectURL\(url\),60000/);
});
test('download links use DownloadButton (fetch+blob), not plain <a download>',()=>{
 const read=f=>fs.readFileSync(new URL('../src/'+f,import.meta.url),'utf8');
 const kit=read('FinalProjectKit.jsx'),rr=read('RepoReview.jsx'),btn=read('DownloadButton.jsx');
 assert.match(kit,/<DownloadButton[^>]*href="\/api\/kit\/download"[^>]*disabled=\{!hasPlan\}/);
 assert.match(rr,/href="\/api\/repo-patch"/);assert.match(rr,/href="\/api\/repo-patch\?format=zip"/);
 for(const src of [kit,rr])assert.doesNotMatch(src,/\bdownload>|<a [^>]*download/);
 assert.match(btn,/location\.assign\('\/'\)/);assert.match(btn,/role="alert"/);assert.match(btn,/loading=\{busy\}/);
});
test('api() redirects on 401 before parsing the body and always throws',()=>{
 const m=fs.readFileSync(new URL('../src/main.jsx',import.meta.url),'utf8');
 assert.ok(m.indexOf('res.status===401')<m.indexOf('body=await res.json()'));
 assert.match(m,/location\.assign\('\/'\);throw/);
 assert.doesNotMatch(m,/location\.assign\('\/'\);return;/);
 assert.match(m,/<Result status="warning"/);
});
