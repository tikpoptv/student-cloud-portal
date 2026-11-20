import test from 'node:test';
import assert from 'node:assert/strict';
import {pushAdvice,detectEnvironment,urlBase64ToUint8Array} from '../src/push.js';

const base={supported:true,ios:false,standalone:false,permission:'default',serverEnabled:true};

test('advice: iPhone Safari tab must install to the Home Screen first, whatever else is true',()=>{
 assert.equal(pushAdvice({...base,ios:true,standalone:false,supported:false}),'install');
 assert.equal(pushAdvice({...base,ios:true,standalone:false,permission:'denied'}),'install');
 assert.equal(pushAdvice({...base,ios:true,standalone:true}),'off');
});

test('advice covers unsupported, unavailable, blocked and ready',()=>{
 assert.equal(pushAdvice({...base,supported:false}),'unsupported');
 assert.equal(pushAdvice({...base,serverEnabled:false}),'unavailable');
 assert.equal(pushAdvice({...base,permission:'denied'}),'blocked');
 assert.equal(pushAdvice(base),'off');
 assert.equal(pushAdvice({...base,serverEnabled:undefined}),'off');
});

test('environment detection for iPhone, iPad desktop mode, Android and an installed app',()=>{
 const iphone=detectEnvironment({navigator:{userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)',standalone:false},matchMedia:()=>({matches:false})});
 assert.deepEqual([iphone.ios,iphone.standalone,iphone.supported],[true,false,false]);
 const ipad=detectEnvironment({navigator:{userAgent:'Mozilla/5.0 (Macintosh)',platform:'MacIntel',maxTouchPoints:5}});
 assert.equal(ipad.ios,true);
 const mac=detectEnvironment({navigator:{userAgent:'Mozilla/5.0 (Macintosh)',platform:'MacIntel',maxTouchPoints:0}});
 assert.equal(mac.ios,false);
 const installed=detectEnvironment({navigator:{userAgent:'iPhone',standalone:true,serviceWorker:{}},PushManager:function(){},Notification:{permission:'granted'},matchMedia:()=>({matches:true})});
 assert.deepEqual([installed.ios,installed.standalone,installed.supported,installed.permission],[true,true,true,'granted']);
 const android=detectEnvironment({navigator:{userAgent:'Android Chrome',serviceWorker:{}},PushManager:function(){},Notification:{permission:'default'},matchMedia:()=>({matches:false})});
 assert.deepEqual([android.ios,android.supported],[false,true]);
});

test('VAPID public key decodes to a 65-byte uncompressed P-256 point',()=>{
 const raw=Buffer.alloc(65,7);raw[0]=4;
 const url=raw.toString('base64').replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
 const bytes=urlBase64ToUint8Array(url);
 assert.equal(bytes.length,65);assert.equal(bytes[0],4);assert.equal(bytes[64],7);
});
