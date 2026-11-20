import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {nodes} from './i18n-sources.mjs';
import {t,teamName,isKnownMessage,setLanguage,initialLanguage} from '../src/i18n.js';

test('English covers both screens without changing commands or identifiers',()=>{
 setLanguage('en');
 for(const file of ['ui/src/main.jsx','ui/src/RepoReview.jsx','ui/src/GroupResources.jsx','ui/src/resource-context.js','ui/src/PortalHeader.jsx','ui/src/ErrorPage.jsx','ui/src/AdminDashboard.jsx','ui/src/TeamMembers.jsx','ui/src/ResourceActivation.jsx','ui/src/ActivationProgress.jsx','ui/src/FinalProjectKit.jsx','ui/src/DownloadButton.jsx','ui/src/download.js','ui/src/Chat.jsx','ui/src/push.js','ui/src/Inbox.jsx','ui/src/inbox-utils.js']){
  for(const node of nodes(fs.readFileSync(new URL('../../'+file,import.meta.url),'utf8'))){
   if(['Language / ภาษา','ไทย'].includes(node.value))continue; // Language names stay native.
   assert.doesNotMatch(t(node.value),/[ก-๙]/,`${file}: ${node.value}`);
  }
 }
 for(const value of ['gcloud run services list','demo437','ci-docker.yml','projects/123/locations/global'])assert.equal(t(value),value);
 assert.equal(t('ออกจากระบบ'),'Sign out');
 setLanguage('th');assert.equal(t('Sign out'),'ออกจากระบบ');
});

test('explicit URL language overrides saved language',()=>{
 globalThis.location={search:'?lang=en'};
 globalThis.localStorage={getItem:()=> 'th'};
 globalThis.document={documentElement:{lang:'th'}};
 assert.equal(initialLanguage(),'en');
 location.search='';assert.equal(initialLanguage(),'th');
});

test('team names are never mangled by the substring fallback',()=>{
 const names=['Time Savers','กลุ่ม 7 เชื่อมใจ','Teams United','ชื่อเวลาอ่าน','Name','เวลา'];
 for(const lang of ['th','en']){
  setLanguage(lang);
  for(const n of names)assert.equal(teamName(n),n,lang+': '+n);
 }
 setLanguage('en');assert.equal(teamName('KitLoop · กลุ่มทดลอง'),'KitLoop · Demo team');
 setLanguage('th');assert.equal(teamName('KitLoop · กลุ่มทดลอง'),'KitLoop · กลุ่มทดลอง');
});
test('short keys translate only as whole strings, never inside other text',()=>{
 setLanguage('en');
 assert.equal(t('เวลา'),'Time');assert.equal(t('ชื่อ'),'Name');
 for(const text of ['เวลาออมทรัพย์','ชื่อเล่น 7','กลุ่ม 7 เชื่อมใจ'])assert.equal(t(text),text);
 setLanguage('th');
 assert.equal(t('Time'),'เวลา');
 for(const text of ['Time Savers','Name tag','teams 7'])assert.equal(t(text),text);
 // long keys still work inside dynamic messages
 setLanguage('en');
 assert.match(t('ยังไม่พบไฟล์ตามโครงสร้าง Starter Kit: Dockerfile'),/^Missing files from the Starter Kit structure: Dockerfile$/);
 setLanguage('th');
});
test('isKnownMessage recognises Thai keys and English values only',()=>{
 assert.ok(isKnownMessage('ออกจากระบบ'));assert.ok(isKnownMessage('Sign out'));
 assert.ok(!isKnownMessage('substring not found'));assert.ok(!isKnownMessage(undefined));
});
