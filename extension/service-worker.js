const LOCAL = "http://127.0.0.1:8767";
const active = new Map();
const rendezvousPending = new Map();
const OUTBOX_KEY = "catfoodTransportOutboxV1";
const STATE_KEY = "catfoodTransportStateV1";
const PENDING_KEY = "catfoodTransportPendingV1";
const MAX_PENDING = 2048;
const BATCH_SIZE = 200;
const MAX_BATCH_BYTES = 48 * 1024;
const MAX_EVENT_BYTES = 16 * 1024;
const utf8 = new TextEncoder();
const CIRCUIT_FAILURES = 3;
const CIRCUIT_MS = 30000;
const VERSION_GUARD_KEY = "catfoodVersionReloadGuardV1";
const REINJECT_KEY = "catfoodReinjectAfterReloadV1";
const BOOTSTRAP_RELOAD_TAB_KEY = "catfoodBootstrapReloadTabV1";
const VERSION_CHECK_INTERVAL_MS = 5000;
const WORKER_EPOCH = crypto.randomUUID();
let pending = [], flushTimer = null, flushing = false, restored = false, outboxPresent = false, pendingDurable = false, pendingPersistTimer = null;
let versionCheckInFlight=false, versionReloading=false, lastVersionCheckAt=0, versionUpdatePending=false;
let transportState = {failures:0,circuit_until:0,dropped:0,last_error:null,last_ack_ts:0};

async function persistState() {
  try { await chrome.storage.session.set({[STATE_KEY]:transportState}); } catch (_) {}
}
async function persistPendingNow() {
  if (!pendingDurable) return;
  try {
    if (pending.length) await chrome.storage.session.set({[PENDING_KEY]:pending.slice(-MAX_PENDING)});
    else { await chrome.storage.session.remove(PENDING_KEY); pendingDurable=false; }
  } catch (_) {}
}
function schedulePendingPersist(delay=80) {
  if (!pendingDurable || pendingPersistTimer != null) return;
  pendingPersistTimer=setTimeout(()=>{pendingPersistTimer=null; void persistPendingNow();},delay);
}
async function restoreTransport() {
  if (restored) return;
  restored = true;
  try {
    const v = await chrome.storage.session.get([OUTBOX_KEY, STATE_KEY, PENDING_KEY]);
    if (v[STATE_KEY] && typeof v[STATE_KEY] === "object") transportState = {...transportState,...v[STATE_KEY]};
    const backlog=v[PENDING_KEY];
    if (Array.isArray(backlog) && backlog.length) { pending=backlog.slice(-MAX_PENDING); pendingDurable=true; }
    const box = v[OUTBOX_KEY];
    if (box?.batch_id && Array.isArray(box.events) && box.events.length) {
      // UNKNOWN delivery is a separate durable lane. Do not copy it into fresh
      // pending: new events must never be spliced away while an old batch retries.
      outboxPresent = true;
    }
  } catch (_) {}
}
function scheduleFlush(delay=120) {
  if (flushTimer != null) return;
  flushTimer = setTimeout(()=>{flushTimer=null; void flush();}, delay);
}
function emit(event) {
  let eventBytes=0;
  try { eventBytes=utf8.encode(JSON.stringify(event)).length; } catch (_) { transportState.dropped++; void persistState(); return; }
  if (eventBytes > MAX_EVENT_BYTES) { transportState.dropped++; void persistState(); return; }
  if (pending.length >= MAX_PENDING) { pending.shift(); transportState.dropped++; void persistState(); }
  pending.push(event);
  if (outboxPresent || transportState.failures>0 || transportState.circuit_until>Date.now() || pendingDurable) { pendingDurable=true; schedulePendingPersist(); }
  scheduleFlush(pending.length >= 64 ? 0 : 120);
}
function emitMany(events) {
  if (!Array.isArray(events) || !events.length) return;
  for (const event of events.slice(0,1000)) emit(event);
}

function sanitizedSurface(tab) {
  const base={eligible:false,host:null,path:null,title:null,tab_id:Number.isInteger(tab?.id)?tab.id:-1,window_id:Number.isInteger(tab?.windowId)?tab.windowId:-1};
  let u;
  try { u=new URL(String(tab?.url||tab?.pendingUrl||"")); } catch (_) { return base; }
  const host=String(u.hostname||"").toLowerCase();
  if (host!=="chatgpt.com" && host!=="auth.openai.com") return base;
  let path="/";
  if (host==="auth.openai.com") {
    if (u.pathname.startsWith("/advanced-account-security/secure-methods")) path="/advanced-account-security/secure-methods";
    else if (u.pathname.startsWith("/advanced-account-security")) path="/advanced-account-security";
    else path="/other";
  } else if (String(u.pathname||"").startsWith("/c/")) path="/c/:conversation";
  const title=host==="auth.openai.com"?String(tab?.title||"").slice(0,160):null;
  return {...base,eligible:true,host,path,title};
}
let surfacePushInFlight=false, surfacePushQueued=false, surfaceQueuedWindowId=null;
async function activeSurfaceTab(windowId=null) {
  if (Number.isInteger(windowId) && windowId>=0) {
    const tabs=await chrome.tabs.query({active:true,windowId});
    return tabs?.[0]||null;
  }
  if (chrome.windows?.getLastFocused) {
    try {
      const win=await chrome.windows.getLastFocused({populate:true,windowTypes:["normal"]});
      const tab=win?.tabs?.find(t=>t.active);
      if (tab) return tab;
    } catch (_) {}
  }
  const tabs=await chrome.tabs.query({active:true,lastFocusedWindow:true});
  return tabs?.[0]||null;
}
async function activeSurfaceCandidates() {
  if (!chrome.tabs?.query) return [];
  try {
    const tabs=await chrome.tabs.query({active:true});
    const out=[];
    for (const tab of (tabs||[]).slice(0,8)) {
      const s=sanitizedSurface(tab);
      if (s.eligible) out.push(s);
    }
    return out;
  } catch (_) { return []; }
}
async function pushActiveSurface(reason="event",windowId=null) {
  if (!chrome.tabs?.query) return;
  if (surfacePushInFlight) { surfacePushQueued=true; surfaceQueuedWindowId=windowId; return; }
  surfacePushInFlight=true;
  try {
    const none=chrome.windows?.WINDOW_ID_NONE;
    const tab=(Number.isInteger(windowId) && windowId===none)?null:await activeSurfaceTab(windowId);
    const surface=sanitizedSurface(tab);
    const candidates=await activeSurfaceCandidates();
    const ctrl=new AbortController(), timer=setTimeout(()=>ctrl.abort(),500);
    try {
      await fetch(LOCAL+"/surface",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({extension_id:chrome.runtime.id,extension_version:chrome.runtime.getManifest().version,worker_epoch:WORKER_EPOCH,reason,surface,candidates}),cache:"no-store",signal:ctrl.signal});
    } finally { clearTimeout(timer); }
  } catch (_) {
    // Ephemeral observation: do not create a retry lane. A later tab/window
    // event or worker start refreshes the surface.
  } finally {
    surfacePushInFlight=false;
    if (surfacePushQueued) {
      const queued=surfaceQueuedWindowId; surfacePushQueued=false; surfaceQueuedWindowId=null;
      queueMicrotask(()=>void pushActiveSurface("coalesced",queued));
    }
  }
}
if (chrome.tabs?.onActivated) chrome.tabs.onActivated.addListener(info=>{void pushActiveSurface("activated",info?.windowId);if(versionUpdatePending)setTimeout(()=>void reconcileDaemonVersion(true),100);});
if (chrome.tabs?.onUpdated) chrome.tabs.onUpdated.addListener((_id,change,tab)=>{ if(tab?.active && (change.url||change.title||change.status==="complete")) void pushActiveSurface("updated",tab?.windowId); });
if (chrome.windows?.onFocusChanged) chrome.windows.onFocusChanged.addListener(windowId=>void pushActiveSurface("window_focus",windowId));
void pushActiveSurface("worker_start");
async function localHealthy() {
  const ctrl = new AbortController(); const timer = setTimeout(()=>ctrl.abort(), 500);
  try { const r = await fetch(LOCAL+"/health", {cache:"no-store",signal:ctrl.signal}); const h=await r.json(); return r.ok && !!h?.ok && h.version===chrome.runtime.getManifest().version; }
  catch (_) { return false; } finally { clearTimeout(timer); }
}
function tabHasActiveRequest(tabId){
  for(const row of active.values()) if(row?.tab===tabId) return true;
  return false;
}
async function prepareSafeRefresh(){
  let tabs=[];
  try{tabs=await chrome.tabs.query({url:"https://chatgpt.com/*"});}catch(_){return {ok:false,reason:"tabs_query_failed",unsafe:[]};}
  if(!tabs.length)return {ok:true,scheduled:0,unsafe:[]};
  const unsafe=[],safe=[];
  for(const tab of tabs){
    if(typeof tab?.id!=="number"){unsafe.push({tab_id:null,reason:"missing_tab_id"});continue;}
    const ping=await pingContentState(tab.id);
    const busy=tabHasActiveRequest(tab.id);
    if(!ping?.ok||ping.safe_to_reload!==true||busy){
      unsafe.push({tab_id:tab.id,reason:busy?"active_api":(!ping?.ok?"content_unreachable":(ping.visible?"visible":(ping.has_draft?"draft":(ping.editable_focused?"editable_focus":"unsafe_unknown"))))});
    }else safe.push(tab.id);
  }
  if(unsafe.length)return {ok:false,scheduled:0,unsafe};
  let scheduled=0;
  for(const tabId of safe){
    try{
      await chrome.scripting.executeScript({target:{tabId},world:"MAIN",func:(delay)=>{setTimeout(()=>location.reload(),delay);},args:[350]});
      scheduled++;
    }catch(_){return {ok:false,scheduled,unsafe:[{tab_id:tabId,reason:"main_world_schedule_failed"}]};}
  }
  return {ok:true,scheduled,unsafe:[]};
}
async function reconcileDaemonVersion(force=false) {
  if (versionReloading || versionCheckInFlight) return false;
  const now=Date.now();
  if (!force && now-lastVersionCheckAt<VERSION_CHECK_INTERVAL_MS) return true;
  lastVersionCheckAt=now; versionCheckInFlight=true;
  const ctrl=new AbortController(), timer=setTimeout(()=>ctrl.abort(),500);
  try {
    const r=await fetch(LOCAL+"/health",{cache:"no-store",signal:ctrl.signal});
    const h=await r.json();
    if (!r.ok || !h?.ok || !h.version) return false;
    const localVersion=chrome.runtime.getManifest().version;
    const guardStore=chrome.storage.local||chrome.storage.session;
    if (h.version===localVersion) {
      versionUpdatePending=false;
      try { await guardStore.remove(VERSION_GUARD_KEY); } catch (_) {}
      return true;
    }
    versionUpdatePending=true;
    const stored=await chrome.storage.session.get(OUTBOX_KEY);
    if (flushing || pending.length || outboxPresent || stored[OUTBOX_KEY]?.batch_id) {
      scheduleFlush(0);
      setTimeout(()=>void reconcileDaemonVersion(true),1000);
      return false;
    }
    const refresh=await prepareSafeRefresh();
    if(!refresh.ok){
      transportState.last_error="version_reload_deferred_"+(refresh.unsafe?.[0]?.reason||refresh.reason||"unsafe_tab");
      await persistState();
      return false;
    }
    let guard={};
    try { guard=(await guardStore.get(VERSION_GUARD_KEY))[VERSION_GUARD_KEY]||{}; } catch (_) {}
    const attempts=(guard.target===h.version && now-Number(guard.last_ts||0)<60000)?Number(guard.attempts||0):0;
    if (attempts>=2) {
      transportState.last_error="version_reload_guard"; await persistState();
      return false;
    }
    try { await guardStore.set({[VERSION_GUARD_KEY]:{target:h.version,from:localVersion,attempts:attempts+1,last_ts:now}}); } catch (_) {}
    try { await chrome.storage.local.set({[REINJECT_KEY]:{target:h.version,from:localVersion,ts:now}}); } catch (_) {}
    versionReloading=true;
    chrome.runtime.reload();
    return false;
  } catch (_) { return false; }
  finally { clearTimeout(timer); versionCheckInFlight=false; }
}
function takeBatchByBudget() {
  const batch=[]; let bytes=512;
  while (pending.length && batch.length < BATCH_SIZE) {
    let eventBytes;
    try { eventBytes=utf8.encode(JSON.stringify(pending[0])).length + 1; } catch (_) { pending.shift(); transportState.dropped++; continue; }
    if (batch.length && bytes + eventBytes > MAX_BATCH_BYTES) break;
    const event=pending.shift();
    if (!batch.length && bytes + eventBytes > MAX_BATCH_BYTES) { transportState.dropped++; continue; }
    batch.push(event); bytes += eventBytes;
  }
  return batch;
}
async function flush() {
  await restoreTransport();
  if (flushing || (!pending.length && !outboxPresent)) return;
  const now = Date.now();
  if (transportState.circuit_until > now) { scheduleFlush(Math.min(5000, transportState.circuit_until-now)); return; }
  if (transportState.failures > 0 && !(await localHealthy())) {
    transportState.last_error = "health_probe_failed"; transportState.circuit_until = now + CIRCUIT_MS; await persistState(); scheduleFlush(CIRCUIT_MS); return;
  }
  flushing = true;
  let box = null;
  try {
    const stored = await chrome.storage.session.get(OUTBOX_KEY);
    if (stored[OUTBOX_KEY]?.batch_id && Array.isArray(stored[OUTBOX_KEY].events)) {
      box = {...stored[OUTBOX_KEY],extension_id:stored[OUTBOX_KEY].extension_id||chrome.runtime.id,extension_version:stored[OUTBOX_KEY].extension_version||chrome.runtime.getManifest().version,worker_epoch:stored[OUTBOX_KEY].worker_epoch||WORKER_EPOCH};
      outboxPresent = true;
      await chrome.storage.session.set({[OUTBOX_KEY]:box});
    } else if (pending.length) {
      const batch = takeBatchByBudget();
      box = {batch_id:crypto.randomUUID(),events:batch,created_at:Date.now(),extension_id:chrome.runtime.id,extension_version:chrome.runtime.getManifest().version,worker_epoch:WORKER_EPOCH};
      if (pendingDurable) await chrome.storage.session.set({[OUTBOX_KEY]:box,[PENDING_KEY]:pending.slice(-MAX_PENDING)});
      else await chrome.storage.session.set({[OUTBOX_KEY]:box});
      outboxPresent = true;
    } else {
      outboxPresent = false;
      return;
    }
    const ctrl = new AbortController(); const timer = setTimeout(()=>ctrl.abort(), 900);
    let r;
    try {
      r = await fetch(LOCAL+"/event", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(box),cache:"no-store",signal:ctrl.signal});
    } finally { clearTimeout(timer); }
    if (!r.ok) throw new Error("http_"+r.status);
    const ack = await r.json();
    if (!ack?.ok || ack.batch_id !== box.batch_id) throw new Error("invalid_ack");
    await chrome.storage.session.remove(OUTBOX_KEY);
    outboxPresent = false;
    transportState.failures=0; transportState.circuit_until=0; transportState.last_error=null; transportState.last_ack_ts=Date.now(); await persistState();
    if (pendingDurable) await persistPendingNow();
    if (!pending.length && !outboxPresent) void reconcileDaemonVersion();
  } catch (err) {
    // Durable outbox remains authoritative for UNKNOWN delivery. Fresh events stay
    // untouched in pending and will follow only after this batch is ACKed.
    outboxPresent = !!box;
    transportState.failures++;
    transportState.last_error=String(err?.name||err||"delivery_failed").slice(0,80);
    if (transportState.failures >= CIRCUIT_FAILURES) transportState.circuit_until=Date.now()+CIRCUIT_MS;
    pendingDurable=true; await persistState(); await persistPendingNow();
    scheduleFlush(transportState.circuit_until>Date.now()?CIRCUIT_MS:1500);
  } finally {
    flushing=false;
    if ((pending.length || outboxPresent) && transportState.circuit_until<=Date.now()) scheduleFlush();
  }
}
async function pingContentState(tabId) {
  let timer=null;
  try {
    const timeout=new Promise(resolve=>{timer=setTimeout(()=>resolve(null),300);});
    const reply=await Promise.race([chrome.tabs.sendMessage(tabId,{source:"catfood-worker",action:"ping"}).catch(()=>null),timeout]);
    if (!reply?.ok || reply.version!==chrome.runtime.getManifest().version) return null;
    return reply;
  } catch (_) { return null; } finally { if(timer)clearTimeout(timer); }
}
async function pingContent(tabId) { return !!(await pingContentState(tabId)); }
async function closeBootstrapReloadTab() {
  let row=null;
  try { row=(await chrome.storage.local.get(BOOTSTRAP_RELOAD_TAB_KEY))[BOOTSTRAP_RELOAD_TAB_KEY]||null; } catch (_) {}
  if (!row) return false;
  try { await chrome.storage.local.remove(BOOTSTRAP_RELOAD_TAB_KEY); } catch (_) {}
  const tabId=Number(row.tabId);
  if (!Number.isInteger(tabId) || tabId<0 || !chrome.tabs?.remove) return false;
  try { await chrome.tabs.remove(tabId); return true; } catch (_) { return false; }
}

async function ensureContentArmed() {
  if (!chrome.tabs?.query || !chrome.scripting?.executeScript) return 0;
  let injected=0,alive=0;
  let tabs=[];
  try { tabs=await chrome.tabs.query({url:["https://chatgpt.com/*"]}); } catch (_) {}
  for (const tab of tabs) {
    if (!Number.isInteger(tab.id) || tab.discarded) continue;
    if (await pingContent(tab.id)) { alive++; continue; }
    const files=tab.status==="complete"?["reinject-marker.js","content.js","boost.js"]:["content.js","boost.js"];
    try { await chrome.scripting.executeScript({target:{tabId:tab.id},files}); injected++; } catch (_) {}
  }
  // This is a control receipt, not best-effort telemetry. A freshly reloaded
  // MV3 worker may be suspended before emit()'s normal timer fires, so persist
  // the receipt first and attempt delivery synchronously in this worker lifetime.
  pendingDurable=true;
  emit({ts:Date.now(),kind:"extension",note:"content_arm_complete",request_count:injected,other_count:alive});
  await persistPendingNow();
  await flush();
  try { await chrome.storage.local.remove(REINJECT_KEY); } catch (_) {}
  return injected;
}
void restoreTransport().then(async()=>{
  await closeBootstrapReloadTab();
  await ensureContentArmed();
  if (pending.length || outboxPresent) scheduleFlush(0); else void reconcileDaemonVersion(true);
});

function isConversationList(url) {
  try {
    let p = new URL(url).pathname.replace(/^\/backend-api(?=\/)/, "");
    return /^\/conversations(?:\/|$)/.test(p);
  } catch (_) { return false; }
}
const rendezvousCandidatesByUrl = new Map();
const rendezvousCandidatesByRequest = new Map();
const RENDEZVOUS_MATCH_MS = 1000;
const RENDEZVOUS_LOCAL_TTL_MS = 15000;
const MAX_RENDEZVOUS_LOCAL = 256;

async function handshakeCall(action, meta) {
  const ctrl = new AbortController();
  const timer = setTimeout(()=>ctrl.abort(), 550);
  try {
    const r = await fetch(LOCAL+"/handshake/"+action, {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify(meta), cache:"no-store", signal:ctrl.signal
    });
    if (!r.ok) return null;
    return await r.json();
  } catch (_) { return null; } finally { clearTimeout(timer); }
}
function reconcileRendezvous(requestId) {
  const p = rendezvousPending.get(requestId);
  if (!p) return;
  if (p.joinDone && p.role === "owner" && p.finished && !p.completeSent && p.terminalId && p.ownerCap) {
    if (p.holdComplete) return;
    p.completeSent = true;
    void handshakeCall("complete", {
      terminal_id:p.terminalId, participant:p.participantId, owner_cap:p.ownerCap,
      result_meta:p.finishMeta
    }).finally(()=>rendezvousPending.delete(requestId));
  } else if (p.joinDone && p.role !== "owner") {
    rendezvousPending.delete(requestId);
  } else if (p.joinDone && p.finished && !p.terminalId) {
    rendezvousPending.delete(requestId);
  }
}
function setRendezvousPending(requestId, state) {
  rendezvousPending.set(requestId, state);
  setTimeout(()=>{ if (rendezvousPending.get(requestId) === state) rendezvousPending.delete(requestId); }, RENDEZVOUS_LOCAL_TTL_MS);
}
function pendingFromCandidate(c) {
  return {
    participantId:c.participantId, joinDone:false, role:null, terminalId:null, ownerCap:null,
    finished:!!c.finished, finishMeta:c.finishMeta||null, completeSent:false, holdComplete:false
  };
}
async function joinPromoted(c, logicalKey) {
  const cur = rendezvousPending.get(c.requestId);
  if (!cur) return null;
  const x = await handshakeCall("join", {
    logical_key:logicalKey, generation:"unproven",
    scope:"conversation_list:exact-cross-tab-shadow", participant:c.participantId, ttl_ms:12000
  });
  const live = rendezvousPending.get(c.requestId);
  if (!live) return x;
  live.joinDone=true; live.role=x?.role||null; live.terminalId=x?.terminal_id||null; live.ownerCap=x?.owner_cap||null;
  reconcileRendezvous(c.requestId);
  return x;
}
async function promotePair(first, second, logicalKey) {
  const ownerState=pendingFromCandidate(first);
  ownerState.holdComplete=true;
  setRendezvousPending(first.requestId, ownerState);
  setRendezvousPending(second.requestId, pendingFromCandidate(second));
  const owner = await joinPromoted(first, logicalKey);
  if (!owner?.role) {
    // UNKNOWN is not retried or amplified. Let any unseen upstream terminal expire naturally.
    rendezvousPending.delete(second.requestId);
    return;
  }
  await joinPromoted(second, logicalKey);
  const liveOwner=rendezvousPending.get(first.requestId);
  if (liveOwner) { liveOwner.holdComplete=false; reconcileRendezvous(first.requestId); }
}
function expireCandidate(url, requestId) {
  const c = rendezvousCandidatesByUrl.get(url);
  if (c?.requestId === requestId) rendezvousCandidatesByUrl.delete(url);
  rendezvousCandidatesByRequest.delete(requestId);
}
function startRendezvous(d) {
  if (!isConversationList(d.url) || rendezvousPending.size >= MAX_RENDEZVOUS_LOCAL || rendezvousCandidatesByRequest.size >= MAX_RENDEZVOUS_LOCAL) return;
  const now = Date.now();
  const prev = rendezvousCandidatesByUrl.get(d.url);
  if (prev && prev.tabId !== d.tabId && now - prev.anchorTs <= RENDEZVOUS_MATCH_MS) {
    rendezvousCandidatesByUrl.delete(d.url);
    rendezvousCandidatesByRequest.delete(prev.requestId);
    const logicalKey=crypto.randomUUID();
    const current={requestId:d.requestId,tabId:d.tabId,url:d.url,anchorTs:now,participantId:crypto.randomUUID(),finished:false,finishMeta:null};
    void promotePair(prev,current,logicalKey);
    return;
  }

  // First sighting is only a local candidate. No daemon rendezvous is created until another tab matches it.
  if (prev) expireCandidate(d.url,prev.requestId);
  const c={requestId:d.requestId,tabId:d.tabId,url:d.url,anchorTs:now,participantId:crypto.randomUUID(),finished:false,finishMeta:null};
  rendezvousCandidatesByUrl.set(d.url,c);
  rendezvousCandidatesByRequest.set(d.requestId,c);
  setTimeout(()=>expireCandidate(d.url,d.requestId),RENDEZVOUS_MATCH_MS+100);
}
function finishRendezvous(d, failed, durationMs) {
  const meta={status:failed?0:(d.statusCode||0),duration_ms:Math.max(0,durationMs||0),outcome:failed?"error":"complete"};
  const p = rendezvousPending.get(d.requestId);
  if (p) { p.finished=true; p.finishMeta=meta; reconcileRendezvous(d.requestId); return; }
  const c = rendezvousCandidatesByRequest.get(d.requestId);
  if (c) { c.finished=true; c.finishMeta=meta; }
}

const API_FILTER = {urls:["https://chatgpt.com/*"], types:["xmlhttprequest","websocket"]};
chrome.webRequest.onBeforeRequest.addListener(d=>{
  void reconcileDaemonVersion();
  active.set(d.requestId,{t:performance.now(),startTs:Date.now(),method:d.method,type:d.type,tab:d.tabId,ttfb:null});
  startRendezvous(d);
},API_FILTER);
chrome.webRequest.onHeadersReceived.addListener(d=>{
  const s=active.get(d.requestId); if(!s) return; s.ttfb=Math.max(0,performance.now()-s.t);
},API_FILTER);
function finish(d,failed=false){
  const s=active.get(d.requestId); active.delete(d.requestId);
  const duration=s?Math.max(0,performance.now()-s.t):0, endTs=Date.now();
  emit({ts:endTs,start_ts:s?.startTs??Math.max(0,endTs-duration),kind:"net",stage:"summary",category:"api",duration_ms:duration,
    ttfb_ms:s?.ttfb??0,status:failed?0:(d.statusCode||0),method:s?.method||d.method||"",resource_type:s?.type||d.type||"",tab_id:s?.tab??d.tabId});
  finishRendezvous(d, failed, duration);
}
chrome.webRequest.onCompleted.addListener(d=>finish(d,false),API_FILTER);
chrome.webRequest.onErrorOccurred.addListener(d=>finish(d,true),API_FILTER);
chrome.runtime.onMessage.addListener((m,sender)=>{
  if(m?.source!=="catfood-atom") return;
  if(m.event) emit({...m.event,tab_id:sender.tab?.id??-1});
  if(m.events) emitMany(m.events.map(e=>({...e,tab_id:sender.tab?.id??-1})));
});
