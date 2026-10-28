#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

APP_NAME = "catfood-atom-boost-for-chatgpt"
LABEL = "com.catfood.atom.boost.chatgpt"
HOST = "127.0.0.1"
PORT = 8767
SERVICE_NAME = "catfood-atom-boost.service"
PRODUCT_NAME = "CATFOOD Atom + Boost for ChatGPT"
ROOT = Path(__file__).resolve().parent


def detect_platform() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if os.name == "nt":
        return "windows"
    raise SystemExit(f"Unsupported platform: {sys.platform}")


def app_dir(kind: str) -> Path:
    home = Path.home()
    if kind == "linux":
        return home / ".local" / "lib" / APP_NAME
    if kind == "macos":
        return home / "Library" / "Application Support" / PRODUCT_NAME / "app"
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    return local / PRODUCT_NAME / "app"


def state_dir(kind: str) -> Path:
    home = Path.home()
    if kind == "linux":
        return Path(os.environ.get("XDG_STATE_HOME", home / ".local" / "state")) / "catfood-atom-boost"
    if kind == "macos":
        return home / "Library" / "Application Support" / PRODUCT_NAME / "state"
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    return local / PRODUCT_NAME / "state"


def python_for_background(kind: str) -> Path:
    exe = Path(sys.executable).resolve()
    if kind == "windows":
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.exists():
            return pythonw
    return exe


def run(cmd: list[str], *, dry_run: bool, check: bool = True) -> subprocess.CompletedProcess | None:
    print("+", " ".join(str(x) for x in cmd))
    if dry_run:
        return None
    return subprocess.run(cmd, check=check)


def is_runtime_extension_file(path: Path) -> bool:
    name = path.name
    if ".pre-" in name or name.endswith(".bak") or name.endswith("~"):
        return False
    if "__pycache__" in path.parts or name.endswith((".pyc", ".pyo")):
        return False
    return True

def runtime_extension_files(ext: Path) -> list[Path]:
    return sorted(p for p in ext.rglob("*") if p.is_file() and is_runtime_extension_file(p))

def payload_fingerprint(base: Path) -> str | None:
    try:
        files = [base / "atomd.py", base / "status.py"]
        ext = base / "extension"
        files.extend(runtime_extension_files(ext))
        if any(not p.is_file() for p in files[:2]) or not ext.is_dir():
            return None
        h = hashlib.sha256()
        for path in files:
            rel = path.relative_to(base).as_posix().encode()
            h.update(len(rel).to_bytes(4, "big")); h.update(rel)
            raw = path.read_bytes()
            h.update(len(raw).to_bytes(8, "big")); h.update(raw)
        return h.hexdigest()
    except OSError:
        return None

def same_version_body_drift(source: Path, dest: Path, target_version: str) -> bool:
    source_fp, dest_fp = payload_fingerprint(source), payload_fingerprint(dest)
    if not source_fp or not dest_fp or source_fp == dest_fp:
        return False
    try:
        dest_version=json.loads((dest/"extension/manifest.json").read_text(encoding="utf-8"))["version"]
    except Exception:
        return False
    return dest_version == target_version

def linux_deployment_current(dest: Path, target_version: str) -> bool:
    source_fp = payload_fingerprint(ROOT)
    dest_fp = payload_fingerprint(dest)
    if not source_fp or source_fp != dest_fp:
        return False
    service, expected = linux_unit(dest)
    try:
        if service.read_text(encoding="utf-8") != expected:
            return False
    except OSError:
        return False
    item = health()
    if not item or item.get("version") != target_version:
        return False
    active = subprocess.run(["systemctl", "--user", "is-active", "--quiet", SERVICE_NAME], check=False)
    return active.returncode == 0

def copy_payload(dest: Path, *, dry_run: bool) -> None:
    print(f"Install directory: {dest}")
    if dry_run:
        return
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "atomd.py", dest / "atomd.py")
    shutil.copy2(ROOT / "status.py", dest / "status.py")
    ext = dest / "extension"
    if ext.exists():
        shutil.rmtree(ext)
    src_ext = ROOT / "extension"
    ext.mkdir(parents=True)
    for src in runtime_extension_files(src_ext):
        rel = src.relative_to(src_ext)
        dst = ext / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def write_text(path: Path, text: str, *, dry_run: bool) -> None:
    print(f"Write: {path}")
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def health() -> dict | None:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/health", timeout=0.5) as r:
            return json.load(r)
    except Exception:
        return None


def wait_health(timeout: float = 5.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        item = health()
        if item:
            return item
        time.sleep(0.02)
    return None


def linux_unit(dest: Path) -> tuple[Path, str]:
    service = Path.home() / ".config" / "systemd" / "user" / SERVICE_NAME
    py = python_for_background("linux")
    py_q = str(py).replace("\\", "\\\\").replace('"', '\\"')
    app_q = str(dest / "atomd.py").replace("\\", "\\\\").replace('"', '\\"')
    text = f"""[Unit]\nDescription=CATFOOD Atom + Boost local metrics service\nAfter=default.target\n\n[Service]\nType=simple\nExecStart=\"{py_q}\" \"{app_q}\" --host {HOST} --port {PORT}\nRestart=on-failure\nRestartSec=1\n\n[Install]\nWantedBy=default.target\n"""
    return service, text


def install_linux(dest: Path, *, dry_run: bool) -> None:
    service, text = linux_unit(dest)
    current = None
    if not dry_run:
        try: current = service.read_text(encoding="utf-8")
        except OSError: pass
    unit_changed = dry_run or current != text
    if unit_changed:
        write_text(service, text, dry_run=dry_run)
        run(["systemctl", "--user", "daemon-reload"], dry_run=dry_run)
        run(["systemctl", "--user", "enable", SERVICE_NAME], dry_run=dry_run)
    else:
        print(f"Unit unchanged: {service}")
        enabled = subprocess.run(["systemctl", "--user", "is-enabled", "--quiet", SERVICE_NAME], check=False)
        if enabled.returncode != 0:
            run(["systemctl", "--user", "enable", SERVICE_NAME], dry_run=False)
    run(["systemctl", "--user", "restart", SERVICE_NAME], dry_run=dry_run)


def macos_plist(dest: Path) -> tuple[Path, str]:
    plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    py = python_for_background("macos")
    py_xml = escape(str(py))
    app_xml = escape(str(dest / "atomd.py"))
    out_xml = escape(str(dest / "atomd.stdout.log"))
    err_xml = escape(str(dest / "atomd.stderr.log"))
    text = f'''<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0">\n<dict>\n  <key>Label</key><string>{LABEL}</string>\n  <key>ProgramArguments</key>\n  <array>\n    <string>{py_xml}</string>\n    <string>{app_xml}</string>\n    <string>--host</string><string>{HOST}</string>\n    <string>--port</string><string>{PORT}</string>\n  </array>\n  <key>RunAtLoad</key><true/>\n  <key>KeepAlive</key><true/>\n  <key>StandardOutPath</key><string>{out_xml}</string>\n  <key>StandardErrorPath</key><string>{err_xml}</string>\n</dict>\n</plist>\n'''
    return plist, text


def install_macos(dest: Path, *, dry_run: bool) -> None:
    plist, text = macos_plist(dest)
    write_text(plist, text, dry_run=dry_run)
    domain = f"gui/{os.getuid()}"
    run(["launchctl", "bootout", domain, str(plist)], dry_run=dry_run, check=False)
    run(["launchctl", "bootstrap", domain, str(plist)], dry_run=dry_run)
    run(["launchctl", "kickstart", "-k", f"{domain}/{LABEL}"], dry_run=dry_run, check=False)


def windows_startup_file(dest: Path) -> tuple[Path, str]:
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    startup = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "catfood-atom-boost.cmd"
    py = python_for_background("windows")
    text = f'@echo off\r\nstart "" /B "{py}" "{dest / "atomd.py"}" --host {HOST} --port {PORT}\r\n'
    return startup, text


def stop_windows_daemon(*, dry_run: bool) -> None:
    item = health()
    pid = item.get("pid") if isinstance(item, dict) else None
    if isinstance(pid, int) or (isinstance(pid, float) and pid.is_integer()):
        run(["taskkill", "/PID", str(int(pid)), "/F"], dry_run=dry_run, check=False)


def install_windows(dest: Path, *, dry_run: bool) -> None:
    startup, text = windows_startup_file(dest)
    write_text(startup, text, dry_run=dry_run)
    if dry_run:
        print(f"Would start: {python_for_background('windows')} {dest / 'atomd.py'} --host {HOST} --port {PORT}")
        return
    stop_windows_daemon(dry_run=False)
    py = str(python_for_background("windows"))
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [py, str(dest / "atomd.py"), "--host", HOST, "--port", str(PORT)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=flags, close_fds=True,
    )


def find_chrome_extension_registration(preferences: Path, candidate_paths: list[Path]) -> dict | None:
    try:
        data = json.loads(preferences.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    wanted = set()
    for item in candidate_paths:
        try: wanted.add(str(item.expanduser().resolve()))
        except OSError: wanted.add(str(item.expanduser()))
    for extension_id, row in ((data.get("extensions") or {}).get("settings") or {}).items():
        raw = row.get("path")
        if not raw: continue
        try: actual = str(Path(raw).expanduser().resolve())
        except OSError: actual = str(Path(raw).expanduser())
        if actual not in wanted: continue
        info = row.get("service_worker_registration_info") or {}
        return {"extension_id":extension_id,"path":actual,"worker_version":info.get("version")}
    return None

def _linux_user_session_env() -> dict:
    env = os.environ.copy()
    keys = {"DISPLAY","XAUTHORITY","XDG_RUNTIME_DIR","DBUS_SESSION_BUS_ADDRESS"}
    if not keys.issubset(env):
        try:
            out = subprocess.run(["systemctl","--user","show-environment"],capture_output=True,text=True,timeout=2,check=False).stdout
            for line in out.splitlines():
                if "=" not in line: continue
                k,v=line.split("=",1)
                if k in keys and v and not env.get(k): env[k]=v
        except Exception:
            pass
    return env

def version_at_least(value: str | None, target: tuple[int,int,int]) -> bool:
    try:
        parts=tuple(int(x) for x in str(value or "").split(".")[:3])
        return parts >= target
    except Exception:
        return False

def extension_reload_plan(reg: dict | None, target_version: str) -> str:
    if not reg:
        return "not_registered"
    worker = reg.get("worker_version")
    if worker == target_version:
        return "already_current"
    if version_at_least(worker, (0,5,10)):
        return "runtime_handshake"
    return "bootstrap_reload"

def daemon_client_info(extension_id: str, timeout: float=0.4) -> dict | None:
    if not extension_id: return None
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/health", timeout=timeout) as r:
            item=json.loads(r.read().decode())
    except Exception:
        return None
    clients=((item.get("delivery") or {}).get("clients") or []) if isinstance(item,dict) else []
    for client in clients:
        if client.get("extension_id")==extension_id:
            return dict(client)
    return None

def daemon_client_version(extension_id: str, timeout: float=0.4) -> str | None:
    client=daemon_client_info(extension_id,timeout=timeout)
    value=str((client or {}).get("extension_version") or "")
    return value or None

def runtime_handshake_grace(extension_id: str | None) -> float:
    # After daemon restart the delivery registry is empty. Do not wait for an
    # idle MV3 worker by default. If it already reconnected, allow only a tiny
    # bounded handoff window before the deterministic bootstrap path.
    client=daemon_client_info(extension_id or "")
    if not client:
        return 0.0
    try:
        age=max(0.0,time.time()-float(client.get("last_batch_at")))
    except (TypeError,ValueError):
        return 0.0
    if age <= 1.0:
        return 0.15
    if age <= 3.0:
        return 0.05
    return 0.0


def wait_extension_worker_version(prefs: Path, candidate_paths: list[Path], target_version: str, timeout: float=1.5, extension_id: str | None=None) -> dict | None:
    deadline=time.monotonic()+max(0.0,timeout)
    last=None
    while True:
        last=find_chrome_extension_registration(prefs,candidate_paths)
        if last and last.get("worker_version")==target_version:
            return {**last,"verification":"preferences"}
        eid=extension_id or (last or {}).get("extension_id")
        if eid and daemon_client_version(eid)==target_version:
            return {**(last or {"extension_id":eid}),"worker_version":target_version,"verification":"daemon_delivery"}
        if time.monotonic()>=deadline:
            return last
        time.sleep(0.02)

def reload_existing_linux_chrome_extension(dest: Path, target_version: str, *, dry_run: bool=False, timeout: float=6.0) -> dict:
    prefs = Path.home()/".config/google-chrome/Default/Preferences"
    reg = find_chrome_extension_registration(prefs,[ROOT/"extension",dest/"extension"])
    if not reg:
        return {"status":"not_registered"}
    if reg.get("worker_version") == target_version:
        return {"status":"already_current",**reg}
    lock = Path.home()/".config/google-chrome/SingletonLock"
    running = False
    if lock.is_symlink():
        try:
            pid=int(os.readlink(lock).rsplit("-",1)[1]); os.kill(pid,0); running=True
        except (OSError,ValueError,IndexError):
            pass
    if not running:
        return {"status":"browser_not_running",**reg,"target_version":target_version}
    browser = shutil.which("google-chrome-stable") or shutil.which("google-chrome")
    if not browser:
        return {"status":"browser_not_found",**reg,"target_version":target_version}
    url=f"chrome-extension://{reg['extension_id']}/reload.html?target={target_version}&nonce={time.time_ns()}"
    if dry_run:
        return {"status":"would_reload",**reg,"target_version":target_version,"url":url}
    launch_t0=time.perf_counter()
    subprocess.run([browser,url],env=_linux_user_session_env(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=4,check=False)
    bootstrap_launch_ms=round((time.perf_counter()-launch_t0)*1000,2)
    poll_t0=time.perf_counter(); poll_count=0
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        time.sleep(0.02); poll_count+=1
        cur=find_chrome_extension_registration(prefs,[ROOT/"extension",dest/"extension"])
        if cur and cur.get("worker_version")==target_version:
            return {"status":"reloaded",**cur,"target_version":target_version,"verification":"preferences","bootstrap_launch_ms":bootstrap_launch_ms,"live_poll_ms":round((time.perf_counter()-poll_t0)*1000,2),"poll_count":poll_count}
        if daemon_client_version(reg.get("extension_id"))==target_version:
            return {"status":"reloaded",**(cur or reg),"worker_version":target_version,"target_version":target_version,"verification":"daemon_delivery","bootstrap_launch_ms":bootstrap_launch_ms,"live_poll_ms":round((time.perf_counter()-poll_t0)*1000,2),"poll_count":poll_count}
    cur=find_chrome_extension_registration(prefs,[ROOT/"extension",dest/"extension"]) or reg
    return {"status":"reload_timeout",**cur,"target_version":target_version}

def install(kind: str, *, dry_run: bool) -> None:
    install_t0=time.perf_counter()
    phase_ms={}
    dest = app_dir(kind)
    target_version=json.loads((ROOT/"extension/manifest.json").read_text(encoding="utf-8"))["version"]
    if kind == "linux" and not dry_run and dest.exists() and same_version_body_drift(ROOT,dest,target_version):
        source_fp, dest_fp = payload_fingerprint(ROOT), payload_fingerprint(dest)
        raise SystemExit(f"same-version body drift requires version bump: version={target_version} source={source_fp[:12]} installed={dest_fp[:12]}")
    deployment_noop = kind == "linux" and not dry_run and linux_deployment_current(dest, target_version)
    if deployment_noop:
        print(json.dumps({"deployment":"already_current","version":target_version,"fingerprint":payload_fingerprint(dest)},separators=(",", ":")))
    else:
        phase_t0=time.perf_counter()
        copy_payload(dest, dry_run=dry_run)
        phase_ms["copy_payload"]=round((time.perf_counter()-phase_t0)*1000,2)
        phase_t0=time.perf_counter()
        if kind == "linux":
            install_linux(dest, dry_run=dry_run)
        elif kind == "macos":
            install_macos(dest, dry_run=dry_run)
        else:
            install_windows(dest, dry_run=dry_run)
        phase_ms["service_install_restart"]=round((time.perf_counter()-phase_t0)*1000,2)
    if dry_run:
        print(f"Extension directory: {dest / 'extension'}")
        return
    phase_t0=time.perf_counter()
    item = wait_health()
    phase_ms["wait_health"]=round((time.perf_counter()-phase_t0)*1000,2)
    if not item:
        raise SystemExit(f"Local service did not become healthy on http://{HOST}:{PORT}")
    print(json.dumps(item, separators=(",", ":")))
    if kind == "linux":
        phase_t0=time.perf_counter()
        prefs=Path.home()/".config/google-chrome/Default/Preferences"
        reg=find_chrome_extension_registration(prefs,[ROOT/"extension",dest/"extension"])
        plan=extension_reload_plan(reg,target_version)
        if plan=="runtime_handshake":
            eid=(reg or {}).get("extension_id")
            grace=runtime_handshake_grace(eid)
            runtime_wait_t0=time.perf_counter()
            cur=wait_extension_worker_version(prefs,[ROOT/"extension",dest/"extension"],target_version,timeout=grace,extension_id=eid)
            runtime_wait_ms=round((time.perf_counter()-runtime_wait_t0)*1000,2)
            if cur and cur.get("worker_version")==target_version:
                reload_result={"status":"runtime_handshake_reloaded",**cur,"target_version":target_version}
            else:
                reload_result=reload_existing_linux_chrome_extension(dest,target_version,dry_run=False)
                if reload_result.get("status")=="reloaded": reload_result.update({"fallback_from":"runtime_handshake_timeout","runtime_grace_s":grace,"runtime_wait_ms":runtime_wait_ms})
                if reload_result.get("status")=="reload_timeout":
                    raise SystemExit(f"Chrome extension version skew remains after runtime+bootstrap reload: {reload_result}")
        elif plan=="already_current":
            reload_result={"status":"already_current",**(reg or {}),"target_version":target_version}
        else:
            reload_result=reload_existing_linux_chrome_extension(dest,target_version,dry_run=False)
            if reload_result.get("status")=="reload_timeout":
                raise SystemExit(f"Chrome extension version skew remains after bootstrap reload: {reload_result}")
        phase_ms["extension_reconcile"]=round((time.perf_counter()-phase_t0)*1000,2)
        print(json.dumps({"chrome_extension_reload":reload_result},separators=(",", ":")))
    phase_ms["total"]=round((time.perf_counter()-install_t0)*1000,2)
    print(json.dumps({"install_phases_ms":phase_ms,"deployment_noop":deployment_noop},separators=(",", ":")))
    print("\nLoad this folder from your Chromium-based browser's extension page:")
    print(dest / "extension")


def uninstall_linux(*, dry_run: bool) -> None:
    service = Path.home() / ".config" / "systemd" / "user" / SERVICE_NAME
    run(["systemctl", "--user", "disable", "--now", SERVICE_NAME], dry_run=dry_run, check=False)
    print(f"Remove: {service}")
    if not dry_run:
        service.unlink(missing_ok=True)
    run(["systemctl", "--user", "daemon-reload"], dry_run=dry_run, check=False)


def uninstall_macos(*, dry_run: bool) -> None:
    plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    domain = f"gui/{os.getuid()}"
    run(["launchctl", "bootout", domain, str(plist)], dry_run=dry_run, check=False)
    print(f"Remove: {plist}")
    if not dry_run:
        plist.unlink(missing_ok=True)


def uninstall_windows(dest: Path, *, dry_run: bool) -> None:
    startup, _ = windows_startup_file(dest)
    if not dry_run:
        stop_windows_daemon(dry_run=False)
    print(f"Remove: {startup}")
    if not dry_run:
        startup.unlink(missing_ok=True)


def uninstall(kind: str, *, dry_run: bool, purge_state: bool) -> None:
    dest = app_dir(kind)
    if kind == "linux":
        uninstall_linux(dry_run=dry_run)
    elif kind == "macos":
        uninstall_macos(dry_run=dry_run)
    else:
        uninstall_windows(dest, dry_run=dry_run)
    print(f"Remove: {dest}")
    if not dry_run and dest.exists():
        shutil.rmtree(dest)
    if purge_state:
        state = state_dir(kind)
        print(f"Remove state: {state}")
        if not dry_run and state.exists():
            shutil.rmtree(state)


def main() -> None:
    ap = argparse.ArgumentParser(description="Install or remove CATFOOD Atom + Boost for ChatGPT.")
    ap.add_argument("--uninstall", action="store_true", help="remove the local service and installed files")
    ap.add_argument("--purge-state", action="store_true", help="also delete locally stored metrics when uninstalling")
    ap.add_argument("--dry-run", action="store_true", help="print actions without changing the system")
    ap.add_argument("--platform", choices=["linux", "macos", "windows"], help=argparse.SUPPRESS)
    a = ap.parse_args()
    kind = a.platform or detect_platform()
    if a.purge_state and not a.uninstall:
        ap.error("--purge-state requires --uninstall")
    if a.uninstall:
        uninstall(kind, dry_run=a.dry_run, purge_state=a.purge_state)
    else:
        install(kind, dry_run=a.dry_run)


if __name__ == "__main__":
    main()
