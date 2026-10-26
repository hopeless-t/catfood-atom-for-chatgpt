const D="http://127.0.0.1:8766",$=x=>document.getElementById(x);
const FINDINGS={
  rate_limit:["Rate-limit errors","ChatGPT returned HTTP 429 responses."],
  request_burst:["Many requests at once","A large number of requests started close together."],
  ui_update_volume:["Heavy page updates","The page changed its DOM structure many times."],
  main_thread_load:["Browser thread blocked","Long tasks kept the main UI thread busy."],
  frame_stalls:["Screen stutter","One or more animation-frame gaps were unusually long."],
  interaction_latency:["Slow click / typing response","An observed interaction took unusually long."],
  layout_instability:["Page moving around","Visible page layout shifted without recent user input."]
};
async function go(){try{const s=await(await fetch(D+"/snapshot",{cache:"no-store"})).json();
$("ttfb").textContent=Math.round(s.network.avg_ttfb_ms)+" ms";
$("burst").textContent=s.network.max_requests_1s+" /s";
$("input").textContent=Math.round(s.interaction.max_duration_ms)+" ms";
$("gap").textContent=Math.round(s.render.max_gap_ms)+" ms";
$("mut").textContent=s.render.mutations;
$("r429").textContent=s.network.status_counts["429"]||0;
const b=$("findings");b.innerHTML="";
for(const f of s.findings){const [title,explain]=FINDINGS[f.id]||[f.id,"Performance finding."];const d=document.createElement("div");d.className="f";const t=document.createElement("div");t.className="ft";t.textContent=title;const x=document.createElement("div");x.className="fd";x.textContent=explain+" "+f.detail;d.append(t,x);b.appendChild(d)}}catch(_){}}go();setInterval(go,1000);
