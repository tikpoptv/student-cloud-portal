import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import messages from '../../locales/en.json' with {type:'json'};
import {reviewGuidance,warningText,GENERIC_WARNING,KNOWN_WARNING_PREFIXES} from '../src/review-guidance.js';
import {t,setLanguage,isKnownMessage} from '../src/i18n.js';
const review={status:'needs_review',repo:'team/app',source_sha:'0123456789abcdef'};
test('needs_review without any activation offers resources-only path with the Activate hint',()=>{
 const g=reviewGuidance(review,null);assert.equal(g.cta,'resources');assert.equal(g.tab,'overview');assert.equal(g.sha,'0123456');assert.equal(g.showActivateHint,true);
});
test('activation queued/running/failed shows the status state and hides the Activate button hint',()=>{
 for(const status of ['queued','running','failed']){const g=reviewGuidance(review,{status,mode:'live'},false);assert.equal(g.cta,'status',status);assert.equal(g.tab,'overview');assert.equal(g.showActivateHint,false);}
 // a preview activation viewed by the live portal is shown as the Activate form again, so the hint still applies
 assert.equal(reviewGuidance(review,{status:'ready',mode:'preview'},false).cta,'resources');
 assert.equal(reviewGuidance(review,{status:'ready',mode:'preview'},true).cta,'kit');
});
test('needs_review with ready resources offers the Final Project Kit tab',()=>{
 const g=reviewGuidance(review,{status:'ready'});assert.equal(g.cta,'kit');assert.equal(g.tab,'final');
});
test('prepared review or no review shows no guidance',()=>{
 assert.equal(reviewGuidance({...review,status:'prepared'},null),null);
 assert.equal(reviewGuidance(null,null),null);
});
test('RepoReview renders guidance and main.jsx wires goTab',()=>{
 const r=fs.readFileSync(new URL('../src/RepoReview.jsx',import.meta.url),'utf8');
 const m=fs.readFileSync(new URL('../src/main.jsx',import.meta.url),'utf8');
 assert.match(r,/reviewGuidance\(review,activation,preview\)/);
 assert.doesNotMatch(r,/ยังไม่มีการแก้ไฟล์อัตโนมัติ/);
 assert.match(m,/onGoTab=\{setTab\}/);
});
test('needs_review guidance block offers the Lab 5 kit download, prepared flow has a secondary link',()=>{
 const r=fs.readFileSync(new URL('../src/RepoReview.jsx',import.meta.url),'utf8');
 assert.ok(reviewGuidance(review,null));
 assert.equal((r.match(/href="\/api\/lab5-kit\/download"/g)||[]).length,2);
 assert.doesNotMatch(r,/<a href="\/api|download>/);
 assert.match(r,/ดาวน์โหลดชุดไฟล์ Lab 5 ที่ปรับชื่อให้ทีมคุณแล้ว \(\.zip\)/);
 assert.match(r,/ไม่ตรงกับ diff\? ดาวน์โหลดชุดไฟล์ Lab 5/);
 assert.doesNotMatch(r,/ต้องเริ่มเตรียมพื้นที่|Activate ก่อนเพื่อดาวน์โหลด/);
});

test('server-translated English warnings keep the file list in both languages',()=>{
 const en=[['ยังไม่พบไฟล์ตามโครงสร้าง Starter Kit:','deploy/deploy.sh, deploy/release.sh'],['Deployment workflow ต่างจาก Starter Kit:','x.yml'],['release.sh ต่างจาก Starter Kit:','a b']];
 for(const lang of ['th','en']){
  setLanguage(lang);
  for(const [th,list] of en){
   const english=messages[th];assert.ok(english,th);
   assert.ok(KNOWN_WARNING_PREFIXES.includes(english));
   const out=warningText(english+' '+list,t,isKnownMessage);
   assert.ok(out.includes(list),lang+out);assert.notEqual(out,t(GENERIC_WARNING));
   assert.equal(out,lang==='en'?english+' '+list:th+' '+list);
  }
 }
 setLanguage('th');
});
test('RepoReview wires status guidance, the card-4 error next to its button, and a non-clobbering repo input',()=>{
 const r=fs.readFileSync(new URL('../src/RepoReview.jsx',import.meta.url),'utf8');
 assert.match(r,/guidance\.cta==='status'/);assert.match(r,/guidance\.showActivateHint/);
 assert.match(r,/activateError/);assert.match(r,/form\.isFieldTouched\('repo'\)/);assert.match(r,/setReview\(d\?\.review\|\|null\)/);
 assert.match(r,/tabIndex=\{0\}/);assert.doesNotMatch(r,/'Diff '\+selected\?\.path/);
 assert.match(r,/warningText\(w,t,isKnownMessage\)/);
});
test('raw backend warnings become one translated sentence; known ones stay translated',()=>{
 for(const lang of ['th','en']){
  setLanguage(lang);
  for(const raw of ['substring not found','Section boundaries not recognized','Image setting not recognized','อ่าน port ไม่ได้ ต้องให้กลุ่มตรวจตาม stack']){
   assert.equal(warningText(raw,t,isKnownMessage),t(GENERIC_WARNING),raw);
  }
  assert.equal(warningText('ตรวจจากไฟล์เท่านั้น ยังไม่ได้รันแอป เทส หรือ deploy',t,isKnownMessage),t('ตรวจจากไฟล์เท่านั้น ยังไม่ได้รันแอป เทส หรือ deploy'));
 }
 setLanguage('en');
 assert.equal(warningText('substring not found',t,isKnownMessage),'deploy/deploy.sh does not match the Starter Kit structure.');
 assert.equal(warningText('ยังไม่พบไฟล์ตามโครงสร้าง Starter Kit: Dockerfile, deploy/release.sh',t,isKnownMessage),'Missing files from the Starter Kit structure: Dockerfile, deploy/release.sh');
 setLanguage('th');
});
