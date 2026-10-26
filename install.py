#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

APP_NAME = "catfood-atom-for-chatgpt"
LABEL = "com.catfood.atom.chatgpt"
HOST = "127.0.0.1"
PORT = 8766
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
        return home / "Library" / "Application Support" / "CATFOOD Atom for ChatGPT" / "app"
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    return local / "CATFOOD Atom for ChatGPT" / "app"


def state_dir(kind: str) -> Path:
    home = Path.home()
    if kind == "linux":
        return Path(os.environ.get("XDG_STATE_HOME", home / ".local" / "state")) / "catfood-atom"
    if kind == "macos":
        return home / "Library" / "Application Support" / "CATFOOD Atom for ChatGPT" / "state"
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    return local / "CATFOOD Atom for ChatGPT" / "state"


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
    shutil.copytree(ROOT / "extension", ext)


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
        time.sleep(0.1)
    return None


def linux_unit(dest: Path) -> tuple[Path, str]:
    service = Path.home() / ".config" / "systemd" / "user" / "catfood-atom.service"
    py = python_for_background("linux")
    py_q = str(py).replace("\\", "\\\\").replace('"', '\\"')
    app_q = str(dest / "atomd.py").replace("\\", "\\\\").replace('"', '\\"')
    text = f"""[Unit]\nDescription=CATFOOD Atom local metrics service\nAfter=default.target\n\n[Service]\nType=simple\nExecStart=\"{py_q}\" \"{app_q}\" --host {HOST} --port {PORT}\nRestart=on-failure\nRestartSec=1\n\n[Install]\nWantedBy=default.target\n"""
    return service, text


def install_linux(dest: Path, *, dry_run: bool) -> None:
    service, text = linux_unit(dest)
    write_text(service, text, dry_run=dry_run)
    run(["systemctl", "--user", "daemon-reload"], dry_run=dry_run)
    run(["systemctl", "--user", "enable", "catfood-atom.service"], dry_run=dry_run)
    run(["systemctl", "--user", "restart", "catfood-atom.service"], dry_run=dry_run)


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
    startup = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "catfood-atom.cmd"
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


def install(kind: str, *, dry_run: bool) -> None:
    dest = app_dir(kind)
    copy_payload(dest, dry_run=dry_run)
    if kind == "linux":
        install_linux(dest, dry_run=dry_run)
    elif kind == "macos":
        install_macos(dest, dry_run=dry_run)
    else:
        install_windows(dest, dry_run=dry_run)
    if dry_run:
        print(f"Extension directory: {dest / 'extension'}")
        return
    item = wait_health()
    if not item:
        raise SystemExit(f"Local service did not become healthy on http://{HOST}:{PORT}")
    print(json.dumps(item, separators=(",", ":")))
    print("\nLoad this folder from your Chromium-based browser's extension page:")
    print(dest / "extension")


def uninstall_linux(*, dry_run: bool) -> None:
    service = Path.home() / ".config" / "systemd" / "user" / "catfood-atom.service"
    run(["systemctl", "--user", "disable", "--now", "catfood-atom.service"], dry_run=dry_run, check=False)
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
    ap = argparse.ArgumentParser(description="Install or remove CATFOOD Atom for ChatGPT.")
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
