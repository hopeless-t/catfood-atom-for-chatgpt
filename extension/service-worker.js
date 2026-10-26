const LOCAL = "http://127.0.0.1:8766";
const active = new Map();
function category(type) {
  if (["main_frame","sub_frame"].includes(type)) return "document";
  if (["script","stylesheet","image","font","media"].includes(type)) return "asset";
  if (["xmlhttprequest","websocket"].includes(type)) return "api";
  return "other";
}
async function emit(event) {
  try { await fetch(LOCAL+"/event", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(event),cache:"no-store"}); } catch(_) {}
}
chrome.webRequest.onBeforeRequest.addListener(d=>{
  if (!d.url.startsWith("https://chatgpt.com/")) return;
  const c=category(d.type); active.set(d.requestId,{t:performance.now(),c,method:d.method,type:d.type,tab:d.tabId,ttfb:null});
  emit({ts:Date.now(),kind:"net",stage:"start",category:c,method:d.method,resource_type:d.type,tab_id:d.tabId});
},{urls:["https://chatgpt.com/*"]});
chrome.webRequest.onHeadersReceived.addListener(d=>{
  const s=active.get(d.requestId); if(!s) return; s.ttfb=Math.max(0,performance.now()-s.t);
  emit({ts:Date.now(),kind:"net",stage:"headers",category:s.c,ttfb_ms:s.ttfb,status:d.statusCode||0,method:s.method,resource_type:s.type,tab_id:s.tab});
},{urls:["https://chatgpt.com/*"]});
function finish(d,failed=false){
  const s=active.get(d.requestId); active.delete(d.requestId); const c=s?.c||category(d.type);
  emit({ts:Date.now(),kind:"net",stage:failed?"error":"end",category:c,duration_ms:s?Math.max(0,performance.now()-s.t):0,
    ttfb_ms:s?.ttfb??0,status:failed?0:(d.statusCode||0),method:s?.method||d.method||"",resource_type:s?.type||d.type||"",tab_id:s?.tab??d.tabId});
}
chrome.webRequest.onCompleted.addListener(d=>finish(d,false),{urls:["https://chatgpt.com/*"]});
chrome.webRequest.onErrorOccurred.addListener(d=>finish(d,true),{urls:["https://chatgpt.com/*"]});
chrome.runtime.onMessage.addListener((m,sender)=>{if(m?.source==="catfood-atom"&&m.event)emit({...m.event,tab_id:sender.tab?.id??-1});});
