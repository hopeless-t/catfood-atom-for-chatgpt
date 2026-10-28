(()=>{
  const runtimeReinject=globalThis.__CATFOOD_RUNTIME_REINJECT__===true;
  try{delete globalThis.__CATFOOD_RUNTIME_REINJECT__;}catch(_){}
  if(globalThis.__CATFOOD_CONTENT_ACTIVE_V1__)return;
  globalThis.__CATFOOD_CONTENT_ACTIVE_V1__=true;
  function reloadSafety(){
    let hasDraft=false,editableFocused=false;
    try{
      const editables=[...document.querySelectorAll('textarea,input[type="text"],input:not([type]),[contenteditable="true"]')];
      for(const el of editables){const v=('value' in el)?String(el.value||''):String(el.textContent||'');if(v.trim()){hasDraft=true;break;}}
      const a=document.activeElement;
      editableFocused=!!a&&!!a.matches?.('textarea,input[type="text"],input:not([type]),[contenteditable="true"]');
    }catch(_){}
    const visible=document.visibilityState==="visible";
    return {visible,has_draft:hasDraft,editable_focused:editableFocused,safe_to_reload:!visible&&!hasDraft&&!editableFocused};
  }
  try{chrome.runtime.onMessage.addListener((m,_sender,sendResponse)=>{if(m?.source==="catfood-worker"&&m?.action==="ping"){sendResponse({ok:true,version:chrome.runtime.getManifest().version,...reloadSafety()});}});}catch(_){}
  const SEND_BATCH_MAX=64;
  let sendQueue=[],sendScheduled=false;
  const flushSend=()=>{
    sendScheduled=false;
    if(!sendQueue.length)return;
    const events=sendQueue.splice(0,SEND_BATCH_MAX);
    try{const p=chrome.runtime.sendMessage({source:"catfood-atom",events});if(p?.catch)p.catch(()=>{});}catch(_){}
    if(sendQueue.length){sendScheduled=true;Promise.resolve().then(flushSend);}
  };
  const send=e=>{
    sendQueue.push(e);
    if(sendQueue.length>=SEND_BATCH_MAX){flushSend();return;}
    if(!sendScheduled){sendScheduled=true;Promise.resolve().then(flushSend);}
  };
  const perfEpoch=Date.now()-performance.now();
  const visibilityTimeline=[{t:performance.now(),visible:document.visibilityState==="visible"}];
  const noteVisibility=()=>{const row={t:performance.now(),visible:document.visibilityState==="visible"};const last=visibilityTimeline[visibilityTimeline.length-1];if(!last||last.visible!==row.visible)visibilityTimeline.push(row);if(visibilityTimeline.length>64)visibilityTimeline.splice(0,visibilityTimeline.length-64);};
  try{addEventListener("visibilitychange",noteVisibility);}catch(_){}
  const visibleAt=t=>{const x=Number(t||0);for(let i=visibilityTimeline.length-1;i>=0;i--)if(visibilityTimeline[i].t<=x)return visibilityTimeline[i].visible;return visibilityTimeline[0]?.visible??(document.visibilityState==="visible");};
  const wallTs=t=>perfEpoch+Math.max(0,Number(t||0));
  let armed=false;
  function arm(){
    if(armed)return;armed=true;
    if(!runtimeReinject)try{
      const n=performance.getEntriesByType("navigation")[0];
      if(n)send({ts:Date.now(),kind:"navigation",dom_interactive_ms:n.domInteractive||0,dom_content_loaded_ms:n.domContentLoadedEventEnd||0,load_ms:n.loadEventEnd||0,visible:document.visibilityState==="visible"});
      const harvestResources=()=>{
        const originTs=Date.now()-performance.now();
        const category=t=>["script","link","css","img","image","font","video","audio"].includes(t)?"asset":"other";
        const rows=[];
        for(const r of performance.getEntriesByType("resource")){
          const t=String(r.initiatorType||"");
          if(t==="fetch"||t==="xmlhttprequest") continue; // API is observed live by webRequest.
          const start=originTs+Math.max(0,r.startTime||0), end=originTs+Math.max(r.startTime||0,r.responseEnd||r.startTime||0);
          const ttfb=(r.responseStart||0)>(r.startTime||0)?Math.max(0,(r.responseStart||0)-(r.startTime||0)):null;
          rows.push({start,end,category:category(t),ttfb,status:Number(r.responseStatus||0)});
        }
        if(!rows.length)return;
        const issue=rows.map(r=>r.start).sort((a,b)=>a-b);
        const peak=window=>{let best=0,left=0;for(let right=0;right<issue.length;right++){while(issue[right]-issue[left]>window)left++;best=Math.max(best,right-left+1)}return best};
        const points=[];for(const r of rows){points.push([r.start,1],[r.end,-1])}points.sort((a,b)=>a[0]-b[0]||b[1]-a[1]);
        let active=0,maxActive=0,asset=0,other=0,ttfbSum=0,ttfbCount=0,status429=0;
        for(const [_,d] of points){active=Math.max(0,active+d);maxActive=Math.max(maxActive,active)}
        for(const r of rows){if(r.category==="asset")asset++;else other++;if(r.ttfb!==null){ttfbSum+=r.ttfb;ttfbCount++}if(r.status===429)status429++}
        send({ts:Date.now(),kind:"net",stage:"resource_batch",category:"resource",request_count:rows.length,asset_count:asset,other_count:other,
          ttfb_sum_ms:ttfbSum,ttfb_count:ttfbCount,resource_max_active:maxActive,resource_peak_1s:peak(1000),resource_peak_5s:peak(5000),status_429:status429});
      };
      if(typeof requestIdleCallback==="function")requestIdleCallback(harvestResources,{timeout:1000});
      else setTimeout(harvestResources,250);
    }catch(_){}
    let nativeLoaf=false;
    try{const p=new PerformanceObserver(l=>{for(const e of l.getEntries()){let chatgpt=0,extension=0,other=0;for(const x of (e.scripts||[])){const d=Number(x.duration||0),u=String(x.sourceURL||"");if(u.startsWith("chrome-extension://"))extension+=d;else if(u.includes("chatgpt.com")||u.includes("oaistatic.com"))chatgpt+=d;else other+=d;}const scripts=chatgpt+extension+other,end=(e.startTime||0)+(e.duration||0),render=e.renderStart||0,style=e.styleAndLayoutStart||0;const entryVisible=visibleAt(e.startTime);send({ts:wallTs(e.startTime),kind:"loaf",duration_ms:e.duration||0,blocking_ms:e.blockingDuration||0,script_total_ms:scripts,script_chatgpt_ms:chatgpt,script_extension_ms:extension,script_other_ms:other,unattributed_ms:Math.max(0,(e.duration||0)-scripts),render_tail_ms:render?Math.max(0,end-render):0,style_layout_tail_ms:style?Math.max(0,end-style):0,visible:entryVisible});if(entryVisible&&((e.duration||0)>=120||(e.blockingDuration||0)>=50)){try{document.dispatchEvent(new CustomEvent("catfood:adaptive-motion-pressure"))}catch(_){}}}});p.observe({type:"long-animation-frame",buffered:true});nativeLoaf=true;}catch(_){}
    if(!nativeLoaf){try{const p=new PerformanceObserver(l=>{for(const e of l.getEntries())send({ts:wallTs(e.startTime),kind:"longtask",duration_ms:e.duration,visible:visibleAt(e.startTime)});});p.observe({type:"longtask",buffered:true});}catch(_){}}
    try{const p=new PerformanceObserver(l=>{for(const e of l.getEntries())send({ts:wallTs(e.startTime),kind:"layout",layout_shift:e.value,had_recent_input:!!e.hadRecentInput,visible:visibleAt(e.startTime)});});p.observe({type:"layout-shift",buffered:true});}catch(_){}
    try{const p=new PerformanceObserver(l=>{for(const e of l.getEntries()){if(!["click","pointerdown","pointerup","keydown","keyup","input"].includes(e.name))continue;const a=e.processingStart||e.startTime,b=e.processingEnd||a;send({ts:wallTs(e.startTime),kind:"input",event_type:e.name,duration_ms:e.duration||0,input_delay_ms:Math.max(0,a-e.startTime),processing_ms:Math.max(0,b-a),visible:visibleAt(e.startTime)});}});p.observe({type:"event",buffered:true,durationThreshold:16});}catch(_){}
    if(!nativeLoaf){
      const FRAME_HEARTBEAT_MS=15000;
      let last=performance.now(),frames=0,jank=0,gapMax=0,start=last,lastFrameEmit=Date.now();
      const resetFrameWindow=(now=performance.now())=>{last=now;frames=0;jank=0;gapMax=0;start=now;};
      addEventListener("visibilitychange",()=>resetFrameWindow());
      function raf(now){
        if(document.visibilityState!=="visible"){resetFrameWindow(now);requestAnimationFrame(raf);return;}
        const gap=now-last;last=now;frames++;gapMax=Math.max(gapMax,gap);if(gap>50)jank++;
        if(now-start>=1000){const wall=Date.now(),abnormal=jank>0||gapMax>50;if(abnormal||wall-lastFrameEmit>=FRAME_HEARTBEAT_MS){send({ts:wall,kind:"frame",frame_count:frames,jank_frames:jank,max_gap_ms:gapMax,visible:true});lastFrameEmit=wall;}frames=0;jank=0;gapMax=0;start=now;}
        requestAnimationFrame(raf)
      }
      requestAnimationFrame(raf);
    }
  }
  const later=()=>setTimeout(arm,0);
  if(document.readyState==="complete")later();else addEventListener("load",later,{once:true});
})();
