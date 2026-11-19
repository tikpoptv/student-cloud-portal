import messages from '../../locales/en.json' with { type: 'json' };
// Decides what a non-prepared repo review offers next. Pure so it can be tested without rendering.
// cta: 'kit' (resources ready), 'status' (activation exists but is queued/running/failed: the overview tab shows its progress,
// there is no Activate button there), 'resources' (no activation yet: the overview tab has the Activate resources only button).
export function reviewGuidance(review,activation,preview){
  if(!review||review.status==='prepared')return null;
  // A preview-mode activation seen by the live portal is shown as the activation form again, so it counts as "none".
  const exists=Boolean(activation)&&!(preview===false&&activation.mode==='preview');
  const cta=exists?(activation.status==='ready'?'kit':'status'):'resources';
  return {cta,tab:cta==='kit'?'final':'overview',showActivateHint:cta==='resources',sha:String(review.source_sha||'').slice(0,7)};
}
// Backend warnings can be raw exception text (e.g. 'substring not found'). Show only known messages; map anything else to one clear sentence.
export const GENERIC_WARNING='deploy/deploy.sh ไม่ตรงโครงสร้าง Starter Kit';
export const THAI_WARNING_PREFIXES=['ยังไม่พบไฟล์ตามโครงสร้าง Starter Kit:','Deployment workflow ต่างจาก Starter Kit:','release.sh ต่างจาก Starter Kit:'];
// The server sends warnings already translated to English, so also accept the English value of each prefix (read from the catalogue).
export const KNOWN_WARNING_PREFIXES=[...THAI_WARNING_PREFIXES,...THAI_WARNING_PREFIXES.map(p=>messages[p]).filter(Boolean)];
export function warningText(warning,t,isKnown){
  const w=String(warning??'');
  return t(isKnown(w)||KNOWN_WARNING_PREFIXES.some(p=>w.startsWith(p))?w:GENERIC_WARNING);
}
