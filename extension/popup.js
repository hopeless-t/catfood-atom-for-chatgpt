const D="http://127.0.0.1:8766",$=x=>document.getElementById(x);
const FINDINGS={
  rate_limit:["HTTP 429 — rate-limit errors","ChatGPT refused one or more requests under the current request/admission limit."],
  request_burst:["Request burst","Many requests started close together."],
  ui_update_volume:["DOM mutation volume","The page made many structural updates."],
  main_thread_load:["Long Task / main-thread load","Long-running browser work kept the main UI thread busy."],
  frame_stalls:["Frame stalls / jank","The screen had an unusually long pause between visual updates."],
  interaction_latency:["Interaction latency","A click, key, pointer, or input interaction took unusually long."],
  layout_instability:["Layout shift","Page content moved without a recent user interaction."]
};
$("openAnalysis").addEventListener("click",()=>chrome.tabs.create({url:chrome.runtime.getURL("analysis.html")}));
async function go(){try{const s=await(await fetch(D+"/snapshot",{cache:"no-store"})).json();
$("ttfb").textContent=Math.round(s.network.avg_ttfb_ms)+" ms";
$("burst").textContent=s.network.max_requests_1s+" /s";
$("input").textContent=Math.round(s.interaction.max_duration_ms)+" ms";
$("gap").textContent=Math.round(s.render.max_gap_ms)+" ms";
$("mut").textContent=s.render.mutations;
$("r429").textContent=s.network.status_counts["429"]||0;
const b=$("findings");b.innerHTML="";
for(const f of s.findings){const [title,explain]=FINDINGS[f.id]||[f.id,"Performance finding."];const d=document.createElement("div");d.className="f";const t=document.createElement("div");t.className="ft";t.textContent=title;const x=document.createElement("div");x.className="fd";x.textContent=explain+" "+f.detail;d.append(t,x);b.appendChild(d)}}catch(_){}}go();setInterval(go,1000);
