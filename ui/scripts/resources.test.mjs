import test from 'node:test';
import assert from 'node:assert/strict';
import {resourceContext,contextJSON} from '../src/resource-context.js';
import {t,setLanguage} from '../src/i18n.js';
import fs from 'node:fs';
import {resourceState} from '../src/resource-context.js';
test('resource handoff exports only public assigned references and marks preview',()=>{
 const ctx=resourceContext({name:'Team A',email:'private@example.test'},{status:'ready',outputs:{mode:'preview',created_in_google_cloud:false,project_id:'course',prefix:'team123',resources:{cloud_run_service:'team123',database_secret:'team123-database-url',password:'do-not-export'},github_variables:{WIF_PROVIDER:'projects/PROJECT_NUMBER/x',TOKEN:'do-not-export'},credentials:{private_key:'do-not-export'}}});
 assert.equal(ctx.resources.cloud_run_service,'team123');
 assert.equal(resourceContext({},null),null);
 for(const lang of ['th','en']){
  setLanguage(lang);const text=contextJSON(ctx,t);
  assert.doesNotMatch(text,/do-not-export|private@example/);
  assert.match(text,/"created_in_google_cloud": false/);
  assert.match(text,/PROJECT_NUMBER/);
 }
 setLanguage('en');const exported=JSON.parse(contextJSON(ctx,t));
 assert.match(exported.usage_notes[2],/No real resources/);
 assert.equal(Object.keys(exported).at(-1),'agent_guidance');
 assert.match(exported.agent_guidance.purpose,/learn/);
 assert.equal(exported.agent_guidance.approach.length,5);
});

test('resources-only handoff contains no WIF placeholders or required Lab 5 workflow',()=>{
 setLanguage('en');
 const ctx=resourceContext({name:'Final team'},{status:'ready',outputs:{prefix:'final123',mode:'live',created_in_google_cloud:true,github_connected:false,github_repository:null,resources:{cloud_run_service:'final123'},github_variables:{}}});
 const exported=JSON.parse(contextJSON(ctx,t));
 assert.equal(exported.github_connected,false);assert.deepEqual(exported.github_variables,{});
 assert.doesNotMatch(JSON.stringify(exported),/PROJECT_NUMBER|WIF_PROVIDER|according to.*Lab 5/);
 assert.match(exported.usage_notes[4],/optional/);
});

test('github_connected requires an explicit true and resource-only wording avoids GitHub Actions',async()=>{
 const {resourceDefinitionsFor}=await import('../src/resource-context.js');
 const base={prefix:'abc123',resources:{}};
 for(const outputs of [{},{github_connected:'yes'},{github_connected:null}])assert.equal(resourceContext({name:'x'},{status:'ready',outputs:{...base,...outputs}}).github_connected,false);
 assert.equal(resourceContext({name:'x'},{status:'ready',outputs:{...base,github_connected:true}}).github_connected,true);
 const text=defs=>defs.find(r=>r[0]==='deployer_service_account')[2];
 assert.doesNotMatch(text(resourceDefinitionsFor(false)),/GitHub Actions deploy/);assert.match(text(resourceDefinitionsFor(true)),/GitHub Actions deploy/);
 setLanguage('en');assert.doesNotMatch(t(text(resourceDefinitionsFor(false))),/[ก-๙]/);
});

test('live activation without outputs yet gives no context (no blank prefix, no undefined-resources.json)',()=>{
 const team={name:'Time Savers',prefix:'tsv01'};
 for(const outputs of [undefined,null,{},{prefix:'tsv01'},{resources:{}},{prefix:'',resources:{}}])
  assert.equal(resourceContext(team,{status:'running',outputs}),null,JSON.stringify(outputs));
 assert.ok(resourceContext(team,{status:'ready',outputs:{prefix:'tsv01',resources:{}}}));
});
test('resourceState: none, preparing, failed, ready',()=>{
 const team={name:'x',prefix:'tsv01'};
 assert.deepEqual(resourceState(team,null),{state:'none',prefix:'tsv01'});
 assert.deepEqual(resourceState(team,{status:'queued',outputs:{}}),{state:'preparing',prefix:'tsv01'});
 assert.deepEqual(resourceState(team,{status:'running'}),{state:'preparing',prefix:'tsv01'});
 assert.deepEqual(resourceState(team,{status:'failed',outputs:{}}),{state:'failed',prefix:'tsv01'});
 assert.deepEqual(resourceState(team,{status:'ready',outputs:{prefix:'tsv01',resources:{}}}),{state:'ready',prefix:'tsv01'});
});
test('GroupResources empty states lead to the status tab and the resources tab never exports from a missing context',()=>{
 const g=fs.readFileSync(new URL('../src/GroupResources.jsx',import.meta.url),'utf8');
 assert.match(g,/resourceState\(team,activation\)/);
 assert.match(g,/onClick=\{onOpenOverview\}/);
 assert.doesNotMatch(g,/onReview/);
 assert.match(g,/ทรัพยากรกำลังถูกเตรียม ดูความคืบหน้าที่แท็บ เปิดทรัพยากรและดูสถานะ/);
 assert.match(g,/เตรียมทรัพยากรไม่สำเร็จ ดูรายละเอียดและวิธีลองใหม่ที่แท็บ/);
 const m=fs.readFileSync(new URL('../src/main.jsx',import.meta.url),'utf8');
 assert.match(m,/onOpenOverview=\{\(\)=>setTab\('overview'\)\} onOpenKit/);
});
