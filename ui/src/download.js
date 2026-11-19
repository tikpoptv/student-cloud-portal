// Download via fetch + blob so an error response (401/404/503 JSON) is shown to the student instead of being saved as a file.
export function filenameFromDisposition(header,fallback){
 if(typeof header!=='string')return fallback;
 const star=/filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(header);
 if(star){try{return decodeURIComponent(star[1].trim());}catch{}}
 const plain=/filename\s*=\s*"?([^";]+)"?/.exec(header);
 return plain&&plain[1].trim()?plain[1].trim():fallback;
}
export class DownloadError extends Error{constructor(message,status){super(message);this.name='DownloadError';this.status=status;}}
// Returns {blob,filename}. Throws DownloadError (status 401 means the session ended).
export async function fetchDownload(url,{fetchImpl=globalThis.fetch,fallbackName='download',language='th',messages={},isKnown=()=>false}={}){
 let res;
 try{res=await fetchImpl(url,{headers:{'Accept-Language':language},credentials:'same-origin'});}
 catch{throw new DownloadError(messages.network||'เชื่อมต่อระบบไม่สำเร็จ กรุณาลองใหม่',0);}
 if(!res.ok){
  let text='';
  if(res.status!==401){try{const body=await res.json();text=body?.error_source||body?.error||'';}catch{}}
  const byStatus={401:messages.unauthorized,404:messages.notFound,503:messages.unavailable}[res.status];
  // Framework error pages (e.g. werkzeug 'The requested URL was not found') are English-only: use the translated status text unless the body is a message we know.
  const useBody=text&&(res.status!==404||isKnown(text));
  throw new DownloadError((useBody?text:'')||byStatus||messages.failed||'ดาวน์โหลดไม่สำเร็จ กรุณาลองใหม่',res.status);
 }
 const blob=await res.blob();
 return {blob,filename:filenameFromDisposition(res.headers.get('Content-Disposition'),fallbackName)};
}
export function saveBlob(blob,filename){
 const url=URL.createObjectURL(blob),a=document.createElement('a');
 a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();
 // Safari/iOS and in-app browsers (LINE/Facebook) can start the save late, so keep the URL alive for a minute.
 setTimeout(()=>URL.revokeObjectURL(url),60000);
}
