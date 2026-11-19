import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {kitCommands,isValidPrefix} from '../src/kit-commands.js';
test('prefix validation',()=>{
 for(const ok of ['abc','grp01','a123456789'])assert.ok(isValidPrefix(ok),ok);
 for(const bad of ['','ab','1abc','Abc','a-b','abcdefghijk','a b','x;rm -rf /','$(id)','a`b`c',null,undefined,5])assert.ok(!isValidPrefix(bad),String(bad));
});
test('commands for sample prefix',()=>{
 const c=kitCommands('grp01');
 assert.equal(c.valid,true);
 assert.equal(c.unzip,'unzip cpe334-project-kit-grp01.zip');assert.equal(c.doctor,'./project-kit/kit.sh doctor');assert.equal(c.chmod,'chmod +x project-kit/*.sh');
 assert.deepEqual(c.secretSlots,[1,2,3,4,5].map(n=>'grp01-app-secret-'+n));
 assert.equal(c.build,'./project-kit/kit.sh build');assert.equal(c.migrate,'./project-kit/kit.sh migrate');assert.match(c.migrateExample,/^MIGRATE_COMMAND=\S/);
 assert.match(c.deploy,/kit\.sh deploy\n\.\/project-kit\/kit\.sh status\n\.\/project-kit\/kit\.sh open/);
 assert.match(c.env,/kit\.sh env set \w+=/);
 assert.match(c.secretAdd,/secrets add 1/);assert.match(c.secretMap,/secrets map API_KEY 1/);
 assert.match(c.logs,/logs/);assert.match(c.rollback,/rollback/);
});
test('every command runs from the project folder through ./project-kit/ (kit.sh builds the Dockerfile in the current folder)',()=>{
 const c=kitCommands('grp01');
 const all=[c.doctor,...c.stacks.map(s=>s.command),c.appEnv,c.build,c.migrate,c.deploy,c.env,c.secretAdd,c.secretMap,c.logs,c.rollback,c.dryRun].join('\n');
 for(const line of all.split('\n').filter(l=>/kit\.sh/.test(l)))assert.match(line,/^\.\/project-kit\/kit\.sh /,line);
 assert.doesNotMatch(all+c.unzip,/cd project-kit|(^|\n)\.\/kit\.sh/);
 assert.deepEqual(c.stacks.map(s=>s.command),['node','python','java','go','static'].map(s=>'./project-kit/kit.sh --stack '+s+' init'));
 assert.equal(c.appEnv,'cp project-kit/app.env.example app.env');
 // No copyable command may contain a placeholder that a shell would interpret.
 for(const cmd of [...c.stacks.map(s=>s.command),c.appEnv,c.doctor,c.build,c.migrate,c.deploy,c.env,c.secretAdd,c.secretMap,c.logs,c.rollback,c.dryRun])assert.doesNotMatch(cmd,/[<>|]/,cmd);
 // logs and rollback are separate blocks so pasting logs never runs rollback.
 const f=fs.readFileSync(new URL('../src/FinalProjectKit.jsx',import.meta.url),'utf8');
 assert.doesNotMatch(f,/c\.logs\+/);assert.match(f,/<CommandBlock text=\{c\.logs\}\/>/);assert.match(f,/<CommandBlock text=\{c\.rollback\}\/>/);
 assert.match(f,/--allow-plain NAME/);assert.match(f,/ALLOW_PLAIN=NAME/);
});
test('Final Project Kit text matches how kit.sh finds files and how migrate behaves',()=>{
 const f=fs.readFileSync(new URL('../src/FinalProjectKit.jsx',import.meta.url),'utf8');
 const kit=fs.readFileSync(new URL('../../project-kit/kit.sh',import.meta.url),'utf8');
 // resources.env is found next to kit.sh when not in the project folder, so the filled one in the zip needs no copying.
 assert.match(kit,/\[ -f "\$KIT_DIR\/\$2" \]/);
 assert.match(f,/ไฟล์ project-kit\/resources\.env ใน zip เติมค่าของกลุ่มให้แล้ว/);
 assert.match(f,/ย้ายโฟลเดอร์ project-kit เข้าไปในโฟลเดอร์โปรเจกต์/);
 assert.match(f,/permission denied/);assert.match(f,/WSL หรือ Git Bash/);
 assert.match(f,/ถ้าแอปไม่มี migration ข้ามข้อนี้ได้เลย \(deploy จะข้ามให้เอง\)/);
 assert.doesNotMatch(f,/ขั้นนี้จะถูกข้าม/);
 // `migrate` errors without MIGRATE_COMMAND; only `deploy` skips.
 assert.match(kit,/M_MIG_NO_CMD/);
});
test('invalid prefix falls back to placeholder and never injects',()=>{
 for(const bad of ['x;rm -rf /','$(id)','',undefined]){
  const c=kitCommands(bad),all=JSON.stringify(c);
  assert.equal(c.valid,false);assert.equal(c.prefix,'PREFIX');
  assert.doesNotMatch(all,/rm -rf|\$\(|;/);
 }
});
test('commands contain no secret values',()=>{
 const all=JSON.stringify(kitCommands('grp01'));
 assert.doesNotMatch(all,/password|token|DATABASE_URL|=\S*sk-|--from-stdin|--from-file/i);
});
test('main.jsx wires the final tab',()=>{
 const m=fs.readFileSync(new URL('../src/main.jsx',import.meta.url),'utf8');
 assert.match(m,/import FinalProjectKit from '\.\/FinalProjectKit\.jsx'/);
 assert.match(m,/key:'final'/);
 assert.match(m,/onOpenKit=\{\(\)=>setTab\('final'\)\}/);
 const g=fs.readFileSync(new URL('../src/GroupResources.jsx',import.meta.url),'utf8');
 assert.match(g,/onOpenKit/);
});
