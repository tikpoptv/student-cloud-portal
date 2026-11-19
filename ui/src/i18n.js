import messages from '../../locales/en.json' with { type: 'json' };
const reverse=Object.fromEntries(Object.entries(messages).map(([th,en])=>[en,th]));
let language='th';
export function setLanguage(value){language=value==='en'?'en':'th';}
export function getLanguage(){return language;}
export function initialLanguage(){
  const requested=new URLSearchParams(location.search).get('lang');
  if(requested==='en'||requested==='th')return requested;
  try {const saved=localStorage.getItem('student-cloud-language');if(saved==='en'||saved==='th')return saved;}catch{}
  return document.documentElement.lang==='en'?'en':'th';
}
function escape(value){return value.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');}
// Substring fallback is only for dynamic messages that embed a long known sentence. Short keys ('ชื่อ','เวลา','Time', ...) would
// match in the middle of words or user data (team names), so they are exact-match only.
export const MIN_FALLBACK_LENGTH=12;
const longKeys=map=>Object.keys(map).filter(k=>k.length>=MIN_FALLBACK_LENGTH).sort((a,b)=>b.length-a.length).map(escape);
const patterns={en:new RegExp(longKeys(messages).join('|'),'g'),th:new RegExp(longKeys(reverse).join('|'),'g')};
// Team names are user data: never translated, except the built-in demo team whose name is looked up by exact match.
const DEMO_TEAM_NAMES=['KitLoop · กลุ่มทดลอง'];
export function teamName(value){
 if(language==='en'&&DEMO_TEAM_NAMES.includes(value)&&messages[value]!==undefined)return messages[value];
 return value;
}
// True when the whole string is a known message (Thai key or English value). Used to hide raw backend text from students.
export function isKnownMessage(value){return typeof value==='string'&&(messages[value]!==undefined||reverse[value]!==undefined);}
export function t(value){
 if(typeof value!=='string')return value;
 if(language==='th'&&/[ก-๙]/.test(value))return value;
 const map=language==='en'?messages:reverse;
 if(map[value]!==undefined)return map[value];
 return value.replace(patterns[language],match=>map[match]);
}
