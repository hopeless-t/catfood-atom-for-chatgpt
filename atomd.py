#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, statistics, sys, threading, time
from collections import Counter, OrderedDict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import urllib.request, urllib.error

VERSION = "0.5.59"
MAX_EVENTS = 5000
MAX_BODY = 64 * 1024
SURFACE_LOCK = threading.Lock()
SURFACE_CLIENT_MAX = 64
SURFACES = OrderedDict()
SURFACE_HOSTS = {"chatgpt.com", "auth.openai.com"}
CHANGE_COND = threading.Condition()
CHANGE_SEQ = 0
CLIENT_CHANGE_MAX = 64
CLIENT_CHANGE_SEQS = OrderedDict()

def mark_client_change(client):
    global CHANGE_SEQ
    client = str(client or "")[:64]
    if not client: return 0
    with CHANGE_COND:
        CHANGE_SEQ += 1
        CLIENT_CHANGE_SEQS[client] = CHANGE_SEQ
        CLIENT_CHANGE_SEQS.move_to_end(client)
        while len(CLIENT_CHANGE_SEQS) > CLIENT_CHANGE_MAX:
            CLIENT_CHANGE_SEQS.popitem(last=False)
        CHANGE_COND.notify_all()
        return CHANGE_SEQ

def client_change_seq(client):
    client = str(client or "")[:64]
    with CHANGE_COND:
        return int(CLIENT_CHANGE_SEQS.get(client, 0) or 0)

def wait_client_change(client, after, timeout_s):
    client = str(client or "")[:64]
    deadline = time.monotonic() + max(0.0, timeout_s)
    with CHANGE_COND:
        while int(CLIENT_CHANGE_SEQS.get(client, 0) or 0) <= after:
            remaining = deadline - time.monotonic()
            if remaining <= 0: break
            CHANGE_COND.wait(remaining)
        current = int(CLIENT_CHANGE_SEQS.get(client, 0) or 0)
    return current, current > after

def _surface_path(host: str, raw: str) -> str:
    path = str(raw or "/").split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/"):
        path = "/"
    if host == "auth.openai.com":
        if path.startswith("/advanced-account-security/secure-methods"):
            return "/advanced-account-security/secure-methods"
        if path.startswith("/advanced-account-security"):
            return "/advanced-account-security"
        return "/other"
    if host == "chatgpt.com":
        if path.startswith("/c/"):
            return "/c/:conversation"
        return "/"
    return "/"

def _sanitize_surface(raw):
    raw = raw if isinstance(raw, dict) else {}
    eligible = bool(raw.get("eligible"))
    host = str(raw.get("host") or "").lower()[:120]
    if host not in SURFACE_HOSTS:
        eligible = False; host = ""
    safe_title = str(raw.get("title") or "")[:160] if eligible and host == "auth.openai.com" else None
    return {
        "eligible":eligible,
        "host":host if eligible else None,
        "path":_surface_path(host, raw.get("path")) if eligible else None,
        "title":safe_title,
        "tab_id":int(raw.get("tab_id", -1)) if str(raw.get("tab_id", -1)).lstrip("-").isdigit() else -1,
        "window_id":int(raw.get("window_id", -1)) if str(raw.get("window_id", -1)).lstrip("-").isdigit() else -1,
    }

def accept_surface(data):
    if not isinstance(data, dict): return None
    client = str(data.get("extension_id") or "")[:64]
    if not client: return None
    selected = _sanitize_surface(data.get("surface"))
    candidates=[]; seen=set()
    raw_candidates=data.get("candidates") if isinstance(data.get("candidates"),list) else []
    for raw in raw_candidates[:8]:
        item=_sanitize_surface(raw)
        if not item["eligible"]: continue
        key=(item["host"],item["path"],item["tab_id"],item["window_id"])
        if key in seen: continue
        seen.add(key); candidates.append(item)
    item = {
        "extension_id":client,
        "extension_version":str(data.get("extension_version") or "")[:32],
        "worker_epoch":str(data.get("worker_epoch") or "")[:80],
        "reason":str(data.get("reason") or "")[:40],
        "received_at":time.time(),
        **selected,
        "candidates":candidates,
    }
    with SURFACE_LOCK:
        SURFACES[client] = item; SURFACES.move_to_end(client)
        while len(SURFACES) > SURFACE_CLIENT_MAX: SURFACES.popitem(last=False)
    mark_client_change(client)
    return dict(item)


def surface_view(client=None):
    with SURFACE_LOCK:
        if client:
            item = SURFACES.get(client)
            return {"ok":True,"version":VERSION,"surface":dict(item) if item else None,"scope_client":client}
        items = [dict(v) for v in SURFACES.values()]
    return {"ok":True,"version":VERSION,"surfaces":items}
HANDSHAKE_BASE = os.environ.get("CATFOOD_HANDSHAKE_BASE", "http://127.0.0.1:8766").rstrip("/")
HANDSHAKE_SECRET_FILE = Path(os.environ.get("CATFOOD_HANDSHAKE_SECRET_FILE", str(Path.home() / "chatgpt-handshake-lab" / "private_state" / "rendezvous.secret")))

def handshake_proxy(action: str, payload: dict):
    if action not in {"join", "complete"}:
        return 400, {"ok":False,"error":"bad_handshake_action"}
    try:
        secret = HANDSHAKE_SECRET_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return 503, {"ok":False,"error":"handshake_secret_unavailable"}
    if not secret:
        return 503, {"ok":False,"error":"handshake_secret_empty"}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    req = urllib.request.Request(
        f"{HANDSHAKE_BASE}/rendezvous/{action}", data=raw, method="POST",
        headers={"Content-Type":"application/json", "X-CATFOOD-Rendezvous":secret},
    )
    try:
        with urllib.request.urlopen(req, timeout=0.45) as r:
            body = json.loads(r.read() or b"{}")
            return int(r.status), body
    except urllib.error.HTTPError as exc:
        try: body = json.loads(exc.read() or b"{}")
        except Exception: body = {"ok":False,"error":"handshake_upstream_http"}
        return int(exc.code), body
    except Exception as exc:
        return 502, {"ok":False,"error":f"handshake_upstream_{type(exc).__name__}"}
def _state_dir():
    home = Path.home()
    if sys.platform.startswith("linux"):
        return Path(os.environ.get("XDG_STATE_HOME", home / ".local" / "state")) / "catfood-atom-boost"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "CATFOOD Atom + Boost for ChatGPT" / "state"
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return local / "CATFOOD Atom + Boost for ChatGPT" / "state"
    return home / ".catfood-atom" / "state"

STATE_DIR = _state_dir()
LOG_PATH = STATE_DIR / "events.jsonl"
PERSIST_EVENTS = os.environ.get("CATFOOD_PERSIST_EVENTS", "0").strip().lower() in {"1","true","yes","on"}
LOG_MAX_BYTES = max(64 * 1024, int(os.environ.get("CATFOOD_EVENT_LOG_MAX_BYTES", str(8 * 1024 * 1024))))
ALLOWED_KINDS = {"net", "render", "longtask", "loaf", "frame", "input", "layout", "navigation", "visibility", "tab", "extension", "test"}
ALLOWED_FIELDS = {
    "ts", "start_ts", "kind", "stage", "category", "duration_ms", "ttfb_ms", "status", "method", "resource_type",
    "mutations", "added", "removed", "attributes", "characters", "frame_count", "max_gap_ms", "jank_frames",
    "tab_id", "visible", "event_type", "input_delay_ms", "processing_ms", "layout_shift", "had_recent_input",
    "dom_interactive_ms", "dom_content_loaded_ms", "load_ms", "blocking_ms", "script_total_ms", "script_chatgpt_ms",
    "script_extension_ms", "script_other_ms", "unattributed_ms", "render_tail_ms", "style_layout_tail_ms", "note",
    "request_count", "asset_count", "other_count", "ttfb_sum_ms", "ttfb_count", "resource_max_active", "resource_peak_1s", "resource_peak_5s", "status_429",
    "client_id", "client_version", "worker_epoch"
}

class Store:
    def __init__(self):
        self.events = deque(maxlen=MAX_EVENTS)
        self.lock = threading.Lock()
        STATE_DIR.mkdir(parents=True, exist_ok=True)

    def _normalize(self, raw: dict):
        e = {k: raw[k] for k in ALLOWED_FIELDS if k in raw}
        e["ts"] = float(e.get("ts") or time.time() * 1000)
        e["kind"] = str(e.get("kind", "test"))[:32]
        if e["kind"] not in ALLOWED_KINDS:
            e["kind"] = "test"
        for key in ("stage", "category", "method", "resource_type", "event_type", "note", "client_id", "client_version", "worker_epoch"):
            if key in e:
                e[key] = str(e[key])[:120]
        numeric = ("start_ts", "duration_ms", "ttfb_ms", "status", "mutations", "added", "removed", "attributes", "characters",
                   "frame_count", "max_gap_ms", "jank_frames", "tab_id", "input_delay_ms", "processing_ms",
                   "layout_shift", "dom_interactive_ms", "dom_content_loaded_ms", "load_ms", "blocking_ms", "script_total_ms",
                   "script_chatgpt_ms", "script_extension_ms", "script_other_ms", "unattributed_ms", "render_tail_ms", "style_layout_tail_ms",
                   "request_count", "asset_count", "other_count", "ttfb_sum_ms", "ttfb_count", "resource_max_active", "resource_peak_1s", "resource_peak_5s", "status_429")
        for key in numeric:
            if key in e:
                try: e[key] = float(e[key])
                except Exception: e.pop(key, None)
        for key in ("visible", "had_recent_input"):
            if key in e: e[key] = bool(e[key])
        return e

    def add_many(self, raws):
        items = [self._normalize(raw) for raw in raws if isinstance(raw, dict)]
        if not items:
            return []
        lines = "".join(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n" for e in items)
        with self.lock:
            self.events.extend(items)
            if PERSIST_EVENTS:
                try:
                    if LOG_PATH.exists() and LOG_PATH.stat().st_size + len(lines.encode("utf-8")) > LOG_MAX_BYTES:
                        rotated = LOG_PATH.with_suffix(LOG_PATH.suffix + ".1")
                        try: rotated.unlink(missing_ok=True)
                        except OSError: pass
                        try: LOG_PATH.replace(rotated)
                        except OSError: pass
                    with LOG_PATH.open("a", encoding="utf-8") as f:
                        f.write(lines)
                except OSError:
                    pass
        return items

    def add(self, raw: dict):
        items = self.add_many([raw])
        return items[0] if items else None

    def reset(self, client_id=None):
        with self.lock:
            if not client_id:
                self.events.clear(); return
            kept = [e for e in self.events if e.get("client_id") != client_id]
            self.events.clear(); self.events.extend(kept)

    def snapshot(self, client_id=None, events_override=None, tab_id=None):
        now = time.time() * 1000
        if events_override is None:
            with self.lock: events = list(self.events)
            if client_id:
                events = [e for e in events if e.get("client_id") == client_id]
        else:
            events = list(events_override)
        if tab_id is not None:
            events = [e for e in events if int(e.get("tab_id", -1) or -1) == int(tab_id)]
        recent = [e for e in events if now - e.get("ts", now) <= 60_000]
        net = [e for e in recent if e.get("kind") == "net"]
        starts = [e for e in net if e.get("stage") == "start"]
        heads = [e for e in net if e.get("stage") == "headers"]
        ends = [e for e in net if e.get("stage") in {"end", "error"}]
        summaries = [e for e in net if e.get("stage") == "summary"]
        resource_batches = [e for e in net if e.get("stage") == "resource_batch"]
        completed = ends + summaries
        issued = starts + summaries
        resource_count = sum(max(0, int(e.get("request_count", 0) or 0)) for e in resource_batches)
        render = [e for e in recent if e.get("kind") == "render"]
        is_foreground = lambda e: e.get("visible") is not False  # UNKNOWN/legacy stays foreground-compatible.
        longs_all = [e for e in recent if e.get("kind") == "longtask"]
        loafs_all = [e for e in recent if e.get("kind") == "loaf"]
        frames_all = [e for e in recent if e.get("kind") == "frame"]
        inputs_all = [e for e in recent if e.get("kind") == "input"]
        layouts_all = [e for e in recent if e.get("kind") == "layout"]
        longs = [e for e in longs_all if is_foreground(e)]
        loafs = [e for e in loafs_all if is_foreground(e)]
        frames = [e for e in frames_all if is_foreground(e)]
        inputs = [e for e in inputs_all if is_foreground(e)]
        layouts = [e for e in layouts_all if is_foreground(e)]
        background_loafs = [e for e in loafs_all if e.get("visible") is False]
        background_longs = [e for e in longs_all if e.get("visible") is False]

        status_counts = Counter(int(e.get("status", 0) or 0) for e in completed if int(e.get("status", 0) or 0) > 0)
        status_counts[429] += sum(max(0, int(e.get("status_429", 0) or 0)) for e in resource_batches)
        if status_counts.get(429, 0) == 0: status_counts.pop(429, None)
        category_counts = Counter(e.get("category", "other") for e in completed)
        category_counts["asset"] += sum(max(0, int(e.get("asset_count", 0) or 0)) for e in resource_batches)
        category_counts["other"] += sum(max(0, int(e.get("other_count", 0) or 0)) for e in resource_batches)
        ttfb = [float(e["ttfb_ms"]) for e in heads + summaries if "ttfb_ms" in e and float(e["ttfb_ms"]) >= 0]
        ttfb_sum = sum(ttfb) + sum(max(0.0, float(e.get("ttfb_sum_ms", 0) or 0)) for e in resource_batches)
        ttfb_count = len(ttfb) + sum(max(0, int(e.get("ttfb_count", 0) or 0)) for e in resource_batches)
        api_ttfb = sorted(float(e["ttfb_ms"]) for e in heads + summaries if e.get("category") == "api" and "ttfb_ms" in e and float(e["ttfb_ms"]) >= 0)
        api_ttfb_median = statistics.median(api_ttfb) if api_ttfb else 0.0
        api_ttfb_p95 = api_ttfb[max(0, (95 * len(api_ttfb) + 99) // 100 - 1)] if api_ttfb else 0.0
        api_ttfb_avg = sum(api_ttfb) / len(api_ttfb) if api_ttfb else 0.0
        api_ttfb_max = api_ttfb[-1] if api_ttfb else 0.0
        api_get200 = [e for e in summaries if e.get("category") == "api" and str(e.get("method") or "").upper() == "GET" and int(e.get("status", 0) or 0) == 200 and "ttfb_ms" in e and "duration_ms" in e]
        get200_ttfb = sorted(max(0.0, float(e.get("ttfb_ms", 0) or 0)) for e in api_get200)
        get200_after = sorted(max(0.0, float(e.get("duration_ms", 0) or 0) - float(e.get("ttfb_ms", 0) or 0)) for e in api_get200)
        get200_share = sorted((max(0.0, float(e.get("ttfb_ms", 0) or 0)) / max(0.001, float(e.get("duration_ms", 0) or 0))) for e in api_get200 if float(e.get("duration_ms", 0) or 0) > 0)
        def pct95(vals): return vals[max(0, (95 * len(vals) + 99) // 100 - 1)] if vals else 0.0
        get200_ttfb_p95 = pct95(get200_ttfb)
        get200_after_p95 = pct95(get200_after)
        get200_share_median = statistics.median(get200_share) if get200_share else 0.0
        server_wait_tail = len(api_get200) >= 10 and get200_ttfb_p95 >= 1500 and get200_after_p95 <= 100 and get200_share_median >= 0.90
        def start_time(e):
            return float(e.get("start_ts", e.get("ts", 0)) or 0)
        def peak_burst(events, window):
            issue_times = sorted(start_time(e) for e in events)
            best = left = 0
            for right, t in enumerate(issue_times):
                while left <= right and t - issue_times[left] > window: left += 1
                best = max(best, right - left + 1)
            return best
        api_starts = [e for e in starts if e.get("category") == "api"] + [e for e in summaries if e.get("category") == "api"]
        lifecycle = [(float(e.get("ts", 0)), 1) for e in starts]
        lifecycle += [(float(e.get("ts", 0)), -1) for e in ends]
        lifecycle += [(start_time(e), 1) for e in summaries]
        lifecycle += [(float(e.get("ts", 0)), -1) for e in summaries]
        active = max_active = 0
        for _, d in sorted(lifecycle, key=lambda x: (x[0], -x[1])):
            active = max(0, active + d); max_active = max(max_active, active)
        max_active = max(max_active, max([int(e.get("resource_max_active", 0) or 0) for e in resource_batches] or [0]))
        resource_peak_1s = max([int(e.get("resource_peak_1s", 0) or 0) for e in resource_batches] or [0])
        resource_peak_5s = max([int(e.get("resource_peak_5s", 0) or 0) for e in resource_batches] or [0])

        mutations = sum(int(e.get("mutations", 0) or 0) for e in render)
        long_ms = sum(float(e.get("duration_ms", 0) or 0) for e in longs)
        loaf_ms = sum(float(e.get("duration_ms", 0) or 0) for e in loafs)
        loaf_blocking = sum(float(e.get("blocking_ms", 0) or 0) for e in loafs)
        main_thread_pressure = max(long_ms, loaf_blocking)
        loaf_chatgpt = sum(float(e.get("script_chatgpt_ms", 0) or 0) for e in loafs)
        loaf_extension = sum(float(e.get("script_extension_ms", 0) or 0) for e in loafs)
        loaf_other = sum(float(e.get("script_other_ms", 0) or 0) for e in loafs)
        loaf_unattributed = sum(float(e.get("unattributed_ms", 0) or 0) for e in loafs)
        loaf_render_tail = sum(float(e.get("render_tail_ms", 0) or 0) for e in loafs)
        loaf_style_tail = sum(float(e.get("style_layout_tail_ms", 0) or 0) for e in loafs)
        background_loaf_ms = sum(float(e.get("duration_ms", 0) or 0) for e in background_loafs)
        background_loaf_blocking = sum(float(e.get("blocking_ms", 0) or 0) for e in background_loafs)
        background_chatgpt = sum(float(e.get("script_chatgpt_ms", 0) or 0) for e in background_loafs)
        background_long_ms = sum(float(e.get("duration_ms", 0) or 0) for e in background_longs)
        background_pressure = max(background_long_ms, background_loaf_blocking)
        background_max_loaf = max([float(e.get("duration_ms", 0) or 0) for e in background_loafs] or [0])
        raf_jank = sum(int(e.get("jank_frames", 0) or 0) for e in frames)
        gap = max([float(e.get("max_gap_ms", 0) or 0) for e in frames] or [0])
        loaf_max = max([float(e.get("duration_ms", 0) or 0) for e in loafs] or [0])
        stall = max(gap, loaf_max)
        jank = max(raf_jank, len(loafs))
        input_total = max([float(e.get("duration_ms", 0) or 0) for e in inputs] or [0])
        input_queue = max([float(e.get("input_delay_ms", 0) or 0) for e in inputs] or [0])
        shift = sum(float(e.get("layout_shift", 0) or 0) for e in layouts if not e.get("had_recent_input"))

        findings = []
        if status_counts.get(429, 0): findings.append({"severity":"high","id":"rate_limit","detail":f"{status_counts[429]} HTTP 429 responses in 60s"})
        if peak_burst(api_starts, 1000) >= 20: findings.append({"severity":"medium","id":"request_burst","detail":f"peak {peak_burst(api_starts, 1000)} API requests/s"})
        if server_wait_tail:
            findings.append({"severity":"high","id":"server_wait_tail","detail":f"GET 200 p95 response-start wait {round(get200_ttfb_p95,1)} ms; post-headers p95 {round(get200_after_p95,1)} ms"})
        if main_thread_pressure > 200:
            source = "LoAF blocking" if loaf_blocking >= long_ms else "long-task"
            findings.append({"severity":"high","id":"main_thread_load","detail":f"{round(main_thread_pressure,1)} ms {source} time in 60s"})
        if stall > 100 or jank > 10:
            label = "max LoAF duration" if loaf_max >= gap else "max frame gap"
            findings.append({"severity":"high","id":"frame_stalls","detail":f"{label} {round(stall,1)} ms"})
        if background_pressure > 1000 or background_max_loaf > 250:
            findings.append({"severity":"medium","id":"background_main_thread_load","detail":f"{round(background_pressure,1)} ms hidden-tab main-thread pressure; max hidden LoAF {round(background_max_loaf,1)} ms"})
        if input_total > 200 or input_queue > 100: findings.append({"severity":"high","id":"interaction_latency","detail":f"max interaction {round(input_total,1)} ms"})
        if shift > 0.25: findings.append({"severity":"medium","id":"layout_instability","detail":f"layout shift score {round(shift,3)}"})

        return {
            "version": VERSION, "window_ms": 60_000, "events_total": len(events), "scope_client": client_id, "scope_tab_id": tab_id,
            "network": {"issued":len(issued)+resource_count, "completed":len(completed)+resource_count, "max_active":max_active,
                        "avg_ttfb_ms":round(ttfb_sum/ttfb_count,2) if ttfb_count else 0,
                        "api_median_ttfb_ms":round(api_ttfb_median,2), "api_avg_ttfb_ms":round(api_ttfb_avg,2),
                        "api_p95_ttfb_ms":round(api_ttfb_p95,2), "api_max_ttfb_ms":round(api_ttfb_max,2),
                        "get200_samples":len(api_get200), "get200_ttfb_p95_ms":round(get200_ttfb_p95,2),
                        "get200_after_headers_p95_ms":round(get200_after_p95,2), "get200_ttfb_share_median":round(get200_share_median,4),
                        "server_wait_tail":server_wait_tail,
                        "max_requests_1s":max(peak_burst(issued, 1000),resource_peak_1s), "max_requests_5s":max(peak_burst(issued, 5000),resource_peak_5s),
                        "max_api_requests_1s":peak_burst(api_starts, 1000), "max_api_requests_5s":peak_burst(api_starts, 5000),
                        "status_counts":{str(k):v for k,v in status_counts.items()}, "category_counts":dict(category_counts)},
            "interaction": {"events":len(inputs), "max_duration_ms":round(input_total,2), "max_input_delay_ms":round(input_queue,2)},
            "render": {"mutations":mutations, "long_tasks":len(longs), "long_task_ms":round(long_ms,2), "main_thread_pressure_ms":round(main_thread_pressure,2),
                       "loaf_frames":len(loafs), "loaf_ms":round(loaf_ms,2), "loaf_blocking_ms":round(loaf_blocking,2),
                       "loaf_chatgpt_script_ms":round(loaf_chatgpt,2), "loaf_extension_script_ms":round(loaf_extension,2),
                       "loaf_other_script_ms":round(loaf_other,2), "loaf_unattributed_ms":round(loaf_unattributed,2),
                       "loaf_render_tail_ms":round(loaf_render_tail,2), "loaf_style_layout_tail_ms":round(loaf_style_tail,2),
                       "background_loaf_frames":len(background_loafs), "background_loaf_ms":round(background_loaf_ms,2),
                       "background_loaf_blocking_ms":round(background_loaf_blocking,2), "background_chatgpt_script_ms":round(background_chatgpt,2),
                       "background_max_loaf_ms":round(background_max_loaf,2),
                       "jank_frames":jank, "max_gap_ms":round(gap,2), "max_loaf_ms":round(loaf_max,2), "max_stall_ms":round(stall,2), "layout_shift_score":round(shift,4)},
            "findings": findings,
            "privacy": "No conversation text, request bodies, response bodies, cookies, auth headers, raw URLs, or query strings are stored."
        }

    def view(self, client_id=None, limit=100, tab_id=None):
        with self.lock: events = list(self.events)
        if client_id:
            events = [e for e in events if e.get("client_id") == client_id]
        if tab_id is not None:
            events = [e for e in events if int(e.get("tab_id", -1) or -1) == int(tab_id)]
        return {"snapshot": self.snapshot(client_id, events_override=events, tab_id=tab_id), "events": events[-limit:], "scope_client": client_id, "scope_tab_id": tab_id}

STORE = Store()

# MV3 service workers can disappear after sending but before receiving an ACK.
# Retain only recent batch identities so replay of an UNKNOWN delivery is safe.
BATCH_RECEIPTS = deque(maxlen=2048)
BATCH_RECEIPT_SET = set()
BATCH_RECEIPT_LOCK = threading.Lock()
BATCH_ACCEPTED_TOTAL = 0
BATCH_DUPLICATE_TOTAL = 0
LAST_BATCH_ID = None
LAST_BATCH_AT = None
DELIVERY_CLIENT_MAX = 64
DELIVERY_CLIENTS = OrderedDict()

def accept_batch(batch_id, raws, client_meta=None):
    global BATCH_ACCEPTED_TOTAL, BATCH_DUPLICATE_TOTAL, LAST_BATCH_ID, LAST_BATCH_AT
    bid = str(batch_id or "")[:128]
    if not bid:
        return None, False
    meta = client_meta if isinstance(client_meta, dict) else {}
    cid = str(meta.get("extension_id") or "")[:64]
    ver = str(meta.get("extension_version") or "")[:32]
    epoch = str(meta.get("worker_epoch") or "")[:128]
    with BATCH_RECEIPT_LOCK:
        duplicate = bid in BATCH_RECEIPT_SET
        now = time.time()
        if cid:
            row = DELIVERY_CLIENTS.get(cid)
            if row is None:
                if len(DELIVERY_CLIENTS) >= DELIVERY_CLIENT_MAX:
                    DELIVERY_CLIENTS.popitem(last=False)
                row = {"extension_id":cid,"accepted_batches":0,"duplicate_batches":0}
                DELIVERY_CLIENTS[cid] = row
            else:
                DELIVERY_CLIENTS.move_to_end(cid)
            row.update({"extension_version":ver or None,"worker_epoch":epoch or None,"last_batch_at":now})
            row["duplicate_batches" if duplicate else "accepted_batches"] += 1
        if duplicate:
            BATCH_DUPLICATE_TOTAL += 1; LAST_BATCH_ID = bid; LAST_BATCH_AT = now
            if cid: mark_client_change(cid)
            return 0, True
        tagged = [{**raw, "client_id":cid, "client_version":ver, "worker_epoch":epoch} for raw in raws[:200] if isinstance(raw, dict)]
        items = STORE.add_many(tagged)
        if len(BATCH_RECEIPTS) == BATCH_RECEIPTS.maxlen:
            old = BATCH_RECEIPTS[0]; BATCH_RECEIPT_SET.discard(old)
        BATCH_RECEIPTS.append(bid); BATCH_RECEIPT_SET.add(bid)
        BATCH_ACCEPTED_TOTAL += 1; LAST_BATCH_ID = bid; LAST_BATCH_AT = now
        if cid: mark_client_change(cid)
        return len(items), False

def delivery_health():
    with BATCH_RECEIPT_LOCK:
        return {"accepted_batches":BATCH_ACCEPTED_TOTAL,"duplicate_batches":BATCH_DUPLICATE_TOTAL,"last_batch_id":LAST_BATCH_ID,"last_batch_at":LAST_BATCH_AT,"dedupe_window":BATCH_RECEIPTS.maxlen,"client_window":DELIVERY_CLIENT_MAX,"clients":[dict(v) for v in DELIVERY_CLIENTS.values()]}

def active_surface_tab_id(client):
    if not client: return None
    sv = surface_view(client).get("surface")
    if not isinstance(sv, dict): return None
    try:
        tab_id = int(sv.get("tab_id", -1))
    except Exception:
        return None
    return tab_id if tab_id >= 0 else None

def world_view(client):
    sv = surface_view(client)
    tab_id = active_surface_tab_id(client)
    return {"ok":True,"version":VERSION,"pid":os.getpid(),"event_log":{"enabled":PERSIST_EVENTS,"max_bytes":LOG_MAX_BYTES},
            "delivery":delivery_health(),"snapshot":STORE.snapshot(client, tab_id=tab_id),"surface":sv.get("surface"),
            "scope_client":client,"scope_tab_id":tab_id,"change_seq":client_change_seq(client)}

class Handler(BaseHTTPRequestHandler):
    server_version = "catfood-atom/" + VERSION
    def log_message(self, *_): return
    def _cors(self):
        origin = self.headers.get("Origin", "")
        if origin.startswith("chrome-extension://"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
        try:
            self.send_response(code); self._cors(); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # Long-poll/analysis clients may cancel after their own timeout. That is
            # transport cancellation, not a daemon failure; do not emit a traceback.
            return
    def do_OPTIONS(self): self.send_response(204); self._cors(); self.end_headers()
    def do_GET(self):
        p = urlparse(self.path)
        if p.path == "/health": return self._json(200, {"ok":True,"version":VERSION,"pid":os.getpid(),"event_log":{"enabled":PERSIST_EVENTS,"max_bytes":LOG_MAX_BYTES},"delivery":delivery_health()})
        q = parse_qs(p.query)
        client = str(q.get("client", [""])[0])[:64] or None
        if p.path == "/world":
            if not client: return self._json(400, {"ok":False,"error":"client_required"})
            return self._json(200, world_view(client))
        if p.path == "/changes":
            if not client: return self._json(400, {"ok":False,"error":"client_required"})
            try: after=max(0,int(q.get("after", [0])[0])); timeout_ms=min(5000,max(0,int(q.get("timeout_ms", [1000])[0])))
            except Exception: return self._json(400, {"ok":False,"error":"bad_wait_query"})
            seq, changed = wait_client_change(client, after, timeout_ms/1000.0)
            return self._json(200, {"ok":True,"version":VERSION,"scope_client":client,"change_seq":seq,"changed":changed})
        if p.path == "/snapshot": return self._json(200, STORE.snapshot(client, tab_id=active_surface_tab_id(client)))
        if p.path == "/surface": return self._json(200, surface_view(client))
        if p.path == "/view":
            limit = min(500, max(1, int(q.get("limit", [100])[0])))
            return self._json(200, STORE.view(client, limit, tab_id=active_surface_tab_id(client)))
        if p.path == "/events":
            limit = min(500, max(1, int(q.get("limit", [100])[0])))
            with STORE.lock: items = list(STORE.events)
            if client: items = [e for e in items if e.get("client_id") == client]
            return self._json(200, {"events":items[-limit:],"scope_client":client})
        return self._json(404, {"error":"not_found"})
    def do_POST(self):
        parsed = urlparse(self.path); p = parsed.path; q = parse_qs(parsed.query)
        if p == "/reset":
            client = str(q.get("client", [""])[0])[:64] or None
            STORE.reset(client); return self._json(200, {"ok":True,"scope_client":client})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n <= 0 or n > MAX_BODY: return self._json(413, {"error":"bad_size"})
            data = json.loads(self.rfile.read(n))
        except Exception as exc:
            return self._json(400, {"error":type(exc).__name__})
        if p == "/surface":
            item = accept_surface(data)
            if item is None: return self._json(400, {"ok":False,"error":"bad_surface"})
            return self._json(200, {"ok":True,"surface":item})
        if p == "/event":
            if isinstance(data, dict) and isinstance(data.get("events"), list) and data.get("batch_id"):
                accepted, duplicate = accept_batch(data.get("batch_id"), data.get("events"), data)
                return self._json(200, {"ok":True,"batch_id":str(data.get("batch_id"))[:128],"accepted":accepted,"duplicate":duplicate})
            if isinstance(data, list):
                items = STORE.add_many(data[:200])
                return self._json(200, {"ok":True,"accepted":len(items)})
            if isinstance(data, dict):
                item = STORE.add(data); return self._json(200, {"ok":True,"accepted":1 if item else 0})
            return self._json(400, {"error":"bad_payload"})
        if p in {"/handshake/join", "/handshake/complete"}:
            if not isinstance(data, dict): return self._json(400, {"ok":False,"error":"bad_payload"})
            action = p.rsplit("/", 1)[-1]
            code, body = handshake_proxy(action, data)
            return self._json(code, body)
        return self._json(404, {"error":"not_found"})

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--host", default="127.0.0.1"); ap.add_argument("--port", type=int, default=8767)
    a = ap.parse_args()
    if a.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("CATFOOD Atom refuses non-loopback bind")
    server = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"CATFOOD Atom {VERSION} listening on http://{a.host}:{a.port}", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass

if __name__ == "__main__": main()
