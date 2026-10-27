#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, sys, threading, time
from collections import Counter, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

VERSION = "0.3.2"
MAX_EVENTS = 5000
MAX_BODY = 64 * 1024
def _state_dir():
    home = Path.home()
    if sys.platform.startswith("linux"):
        return Path(os.environ.get("XDG_STATE_HOME", home / ".local" / "state")) / "catfood-atom"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "CATFOOD Atom for ChatGPT" / "state"
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return local / "CATFOOD Atom for ChatGPT" / "state"
    return home / ".catfood-atom" / "state"

STATE_DIR = _state_dir()
LOG_PATH = STATE_DIR / "events.jsonl"
ALLOWED_KINDS = {"net", "render", "longtask", "frame", "input", "layout", "navigation", "visibility", "tab", "extension", "test"}
ALLOWED_FIELDS = {
    "ts", "kind", "stage", "category", "duration_ms", "ttfb_ms", "status", "method", "resource_type",
    "mutations", "added", "removed", "attributes", "characters", "frame_count", "max_gap_ms", "jank_frames",
    "tab_id", "visible", "event_type", "input_delay_ms", "processing_ms", "layout_shift", "had_recent_input",
    "dom_interactive_ms", "dom_content_loaded_ms", "load_ms", "note"
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
        for key in ("stage", "category", "method", "resource_type", "event_type", "note"):
            if key in e:
                e[key] = str(e[key])[:120]
        numeric = ("duration_ms", "ttfb_ms", "status", "mutations", "added", "removed", "attributes", "characters",
                   "frame_count", "max_gap_ms", "jank_frames", "tab_id", "input_delay_ms", "processing_ms",
                   "layout_shift", "dom_interactive_ms", "dom_content_loaded_ms", "load_ms")
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
            try:
                with LOG_PATH.open("a", encoding="utf-8") as f:
                    f.write(lines)
            except OSError:
                pass
        return items

    def add(self, raw: dict):
        items = self.add_many([raw])
        return items[0] if items else None

    def reset(self):
        with self.lock: self.events.clear()

    def snapshot(self):
        now = time.time() * 1000
        with self.lock: events = list(self.events)
        recent = [e for e in events if now - e.get("ts", now) <= 60_000]
        net = [e for e in recent if e.get("kind") == "net"]
        starts = [e for e in net if e.get("stage") == "start"]
        heads = [e for e in net if e.get("stage") == "headers"]
        ends = [e for e in net if e.get("stage") in {"end", "error"}]
        render = [e for e in recent if e.get("kind") == "render"]
        longs = [e for e in recent if e.get("kind") == "longtask"]
        frames = [e for e in recent if e.get("kind") == "frame"]
        inputs = [e for e in recent if e.get("kind") == "input"]
        layouts = [e for e in recent if e.get("kind") == "layout"]

        status_counts = Counter(int(e.get("status", 0) or 0) for e in ends)
        category_counts = Counter(e.get("category", "other") for e in ends)
        ttfb = [float(e.get("ttfb_ms", 0) or 0) for e in heads]
        def peak_burst(events, window):
            issue_times = sorted(float(e.get("ts", 0) or 0) for e in events)
            best = left = 0
            for right, t in enumerate(issue_times):
                while left <= right and t - issue_times[left] > window: left += 1
                best = max(best, right - left + 1)
            return best
        api_starts = [e for e in starts if e.get("category") == "api"]
        lifecycle = [(float(e.get("ts", 0)), 1) for e in starts]
        lifecycle += [(float(e.get("ts", 0)), -1) for e in ends]
        active = max_active = 0
        for _, d in sorted(lifecycle, key=lambda x: (x[0], -x[1])):
            active = max(0, active + d); max_active = max(max_active, active)

        mutations = sum(int(e.get("mutations", 0) or 0) for e in render)
        long_ms = sum(float(e.get("duration_ms", 0) or 0) for e in longs)
        jank = sum(int(e.get("jank_frames", 0) or 0) for e in frames)
        gap = max([float(e.get("max_gap_ms", 0) or 0) for e in frames] or [0])
        input_total = max([float(e.get("duration_ms", 0) or 0) for e in inputs] or [0])
        input_queue = max([float(e.get("input_delay_ms", 0) or 0) for e in inputs] or [0])
        shift = sum(float(e.get("layout_shift", 0) or 0) for e in layouts if not e.get("had_recent_input"))

        findings = []
        if status_counts.get(429, 0): findings.append({"severity":"high","id":"rate_limit","detail":f"{status_counts[429]} HTTP 429 responses in 60s"})
        if peak_burst(api_starts, 1000) >= 20: findings.append({"severity":"medium","id":"request_burst","detail":f"peak {peak_burst(api_starts, 1000)} API requests/s"})
        if mutations > 1000: findings.append({"severity":"medium","id":"ui_update_volume","detail":f"{mutations} DOM mutations in 60s"})
        if long_ms > 200: findings.append({"severity":"high","id":"main_thread_load","detail":f"{round(long_ms,1)} ms long-task time in 60s"})
        if gap > 100 or jank > 10: findings.append({"severity":"high","id":"frame_stalls","detail":f"max frame gap {round(gap,1)} ms"})
        if input_total > 200 or input_queue > 100: findings.append({"severity":"high","id":"interaction_latency","detail":f"max interaction {round(input_total,1)} ms"})
        if shift > 0.25: findings.append({"severity":"medium","id":"layout_instability","detail":f"layout shift score {round(shift,3)}"})

        return {
            "version": VERSION, "window_ms": 60_000, "events_total": len(events),
            "network": {"issued":len(starts), "completed":len(ends), "max_active":max_active,
                        "avg_ttfb_ms":round(sum(ttfb)/len(ttfb),2) if ttfb else 0,
                        "max_requests_1s":peak_burst(starts, 1000), "max_requests_5s":peak_burst(starts, 5000),
                        "max_api_requests_1s":peak_burst(api_starts, 1000), "max_api_requests_5s":peak_burst(api_starts, 5000),
                        "status_counts":{str(k):v for k,v in status_counts.items()}, "category_counts":dict(category_counts)},
            "interaction": {"events":len(inputs), "max_duration_ms":round(input_total,2), "max_input_delay_ms":round(input_queue,2)},
            "render": {"mutations":mutations, "long_tasks":len(longs), "long_task_ms":round(long_ms,2),
                       "jank_frames":jank, "max_gap_ms":round(gap,2), "layout_shift_score":round(shift,4)},
            "findings": findings,
            "privacy": "No conversation text, request bodies, response bodies, cookies, auth headers, raw URLs, or query strings are stored."
        }

STORE = Store()

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
        self.send_response(code); self._cors(); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_OPTIONS(self): self.send_response(204); self._cors(); self.end_headers()
    def do_GET(self):
        p = urlparse(self.path)
        if p.path == "/health": return self._json(200, {"ok":True,"version":VERSION,"pid":os.getpid()})
        if p.path == "/snapshot": return self._json(200, STORE.snapshot())
        if p.path == "/events":
            limit = min(500, max(1, int(parse_qs(p.query).get("limit", [100])[0])))
            with STORE.lock: items = list(STORE.events)[-limit:]
            return self._json(200, {"events":items})
        return self._json(404, {"error":"not_found"})
    def do_POST(self):
        p = urlparse(self.path).path
        if p == "/reset": STORE.reset(); return self._json(200, {"ok":True})
        if p != "/event": return self._json(404, {"error":"not_found"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n <= 0 or n > MAX_BODY: return self._json(413, {"error":"bad_size"})
            data = json.loads(self.rfile.read(n))
            if isinstance(data, list):
                STORE.add_many(data[:200])
                return self._json(200, {"ok":True})
            if isinstance(data, dict): STORE.add(data); return self._json(200, {"ok":True})
        except Exception as exc: return self._json(400, {"error":type(exc).__name__})
        return self._json(400, {"error":"bad_payload"})

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--host", default="127.0.0.1"); ap.add_argument("--port", type=int, default=8766)
    a = ap.parse_args()
    if a.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("CATFOOD Atom refuses non-loopback bind")
    server = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"CATFOOD Atom {VERSION} listening on http://{a.host}:{a.port}", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass

if __name__ == "__main__": main()
