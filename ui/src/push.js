import {t} from './i18n.js';

// What the person must do next to get notifications. Pure so it can be tested without a browser.
//   unsupported -> this browser cannot receive Web Push
//   install     -> iPhone/iPad Safari tab: Apple only allows push for an app added to the Home Screen
//   blocked     -> notifications were denied in the browser settings
//   off         -> can be enabled now (server has keys, permission not denied)
//   unavailable -> the server has no push keys yet
export function pushAdvice({supported,ios,standalone,permission,serverEnabled}){
  if(ios&&!standalone)return 'install';
  if(!supported)return 'unsupported';
  if(serverEnabled===false)return 'unavailable';
  if(permission==='denied')return 'blocked';
  return 'off';
}

export function detectEnvironment(win=globalThis){
  const nav=win.navigator||{};
  const ua=nav.userAgent||'';
  const ios=/iPhone|iPad|iPod/i.test(ua)||(nav.platform==='MacIntel'&&nav.maxTouchPoints>1);
  const standalone=Boolean(nav.standalone)||Boolean(win.matchMedia&&win.matchMedia('(display-mode: standalone)').matches);
  const supported=Boolean(nav.serviceWorker&&win.PushManager&&win.Notification);
  return {ios,standalone,supported,permission:win.Notification?win.Notification.permission:'default'};
}

export function urlBase64ToUint8Array(value){
  const padded=(value+'='.repeat((4-value.length%4)%4)).replace(/-/g,'+').replace(/_/g,'/');
  const raw=atob(padded);
  return Uint8Array.from(raw,c=>c.charCodeAt(0));
}

export async function currentSubscription(){
  if(!('serviceWorker' in navigator))return null;
  const reg=await navigator.serviceWorker.getRegistration('/');
  return reg?reg.pushManager.getSubscription():null;
}

export async function enablePush(api){
  const cfg=await api('/api/push/config');
  if(!cfg.enabled)throw new Error(t('ยังไม่ได้เปิดใช้การแจ้งเตือนบนเซิร์ฟเวอร์'));
  const reg=await navigator.serviceWorker.register('/sw.js',{scope:'/'});
  await navigator.serviceWorker.ready;
  // Must run from a click: iOS only shows the permission prompt for a user gesture.
  const permission=await Notification.requestPermission();
  if(permission!=='granted')throw new Error(t('ไม่ได้รับอนุญาตให้แจ้งเตือน กรุณาเปิดในการตั้งค่าของเบราว์เซอร์'));
  const subscription=(await reg.pushManager.getSubscription())||await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:urlBase64ToUint8Array(cfg.public_key)});
  await api('/api/push/subscribe',{subscription:subscription.toJSON()});
  return true;
}

export async function disablePush(api){
  const subscription=await currentSubscription();
  if(!subscription)return;
  try{await api('/api/push/unsubscribe',{endpoint:subscription.endpoint});}finally{await subscription.unsubscribe();}
}

// Signing out on a shared computer must not leave this device receiving the previous person's notifications.
export function cleanupBeforeLogout(event,api){
  if(!('serviceWorker' in navigator))return;
  const form=event.currentTarget;
  event.preventDefault();
  const done=()=>form.submit();
  Promise.race([disablePush(api),new Promise(resolve=>setTimeout(resolve,2000))]).catch(()=>{}).then(done);
}
