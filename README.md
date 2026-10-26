# CATFOOD Atom for ChatGPT

A small local performance observer for ChatGPT Web.

It helps answer a simple question: **when ChatGPT Web feels slow, where is the delay coming from?**

CATFOOD Atom is currently an observer, not a speed-up extension. It does not change, cancel, replay, replace, or bypass ChatGPT requests.

## Supported desktop systems

- Linux
- macOS
- Windows 10/11

The browser extension is shared across all three systems. The installer only changes how the small local metrics service starts in the background:

- Linux: `systemd --user`
- macOS: LaunchAgent (`launchd`)
- Windows: the current user's Startup folder

## What it can show

- Request timing and TTFB
- HTTP status counts, including 429 responses
- Request bursts and concurrent activity
- Interaction latency
- Structural DOM update volume
- Long main-thread tasks
- Frame stalls and jank
- Layout instability

All metrics stay on the local machine.

## Privacy

CATFOOD Atom does **not** store:

- Conversation text
- Request bodies
- Response bodies
- Cookies
- Authorization headers
- Raw URLs
- Query strings

The local service listens on loopback only (`127.0.0.1:8766`).

## Requirements

All systems need:

- Python 3
- Git, if you install by cloning this repository
- A Chromium-based desktop browser that supports unpacked Manifest V3 extensions, such as Chrome, Chromium, Edge, or Brave

No Node.js, npm, Docker, or cloud account is required.

Linux additionally needs a working `systemd --user` session.

## Install

### 1. Clone the repository

Linux / macOS:

```bash
git clone https://github.com/hopeless-t/catfood-atom-for-chatgpt.git
cd catfood-atom-for-chatgpt
```

Windows PowerShell:

```powershell
git clone https://github.com/hopeless-t/catfood-atom-for-chatgpt.git
cd catfood-atom-for-chatgpt
```

### 2. Install the local service

#### Linux

```bash
python3 install.py
```

You can also use the wrapper:

```bash
./install.sh
```

#### macOS

```bash
python3 install.py
```

You can also use:

```bash
./install.sh
```

#### Windows

```powershell
py -3 .\install.py
```

If the Python launcher is unavailable:

```powershell
python .\install.py
```

The optional PowerShell wrapper is also available:

```powershell
.\install.ps1
```

The installer copies the service, status tool, and extension into a stable per-user application directory, configures background startup for the current OS, starts the local service, and prints the installed extension path.

A successful install prints a health response similar to:

```json
{"ok":true,"version":"0.2.1","pid":12345}
```

### 3. Load the browser extension

Open the extension-management page in your Chromium-based browser. For Chrome and Chromium:

```text
chrome://extensions
```

For Edge:

```text
edge://extensions
```

Then:

1. Enable **Developer mode**.
2. Choose **Load unpacked**.
3. Select the `extension` directory printed by the installer.
4. Confirm that **CATFOOD Atom for ChatGPT** appears and is enabled.
5. Reload any already-open `chatgpt.com` tabs once.

No browser-store installation is required.

## Verify the installation

### Check the local service

Open this address in a browser:

```text
http://127.0.0.1:8766/health
```

Expected result:

```json
{"ok":true,"version":"0.2.1","pid":12345}
```

Linux/macOS can also use:

```bash
curl http://127.0.0.1:8766/health
```

Windows PowerShell can use:

```powershell
Invoke-RestMethod http://127.0.0.1:8766/health
```

### Check that metrics are arriving

Open `https://chatgpt.com/`, use it normally for a few seconds, then run the status tool from the repository checkout.

Linux / macOS:

```bash
python3 status.py
```

Windows:

```powershell
py -3 .\status.py
```

Example output:

```text
CATFOOD Atom for ChatGPT
requests: 18 issued / 18 completed; peak 6 /s; max active 4
TTFB: 420.5 ms; HTTP 429: 0
input: 32.0 ms; queue: 4.0 ms
render: 245 DOM updates; 0.0 ms long tasks; max gap 26.4 ms
```

The exact values vary by session and machine.

## Use

Leave the extension enabled and use ChatGPT Web normally. Run `status.py` whenever you want a quick local summary.

The extension observes browser-side performance signals and sends only allowed metric fields to the local loopback service.

## Update

From the repository directory:

```bash
git pull
```

Then reinstall the local payload.

Linux / macOS:

```bash
python3 install.py
```

Windows:

```powershell
py -3 .\install.py
```

Finally, open your browser's extensions page and click **Reload** on **CATFOOD Atom for ChatGPT** so the browser picks up extension changes.

## Uninstall

Remove **CATFOOD Atom for ChatGPT** from your browser's extensions page first.

Then run:

Linux / macOS:

```bash
python3 install.py --uninstall
```

Windows:

```powershell
py -3 .\install.py --uninstall
```

By default, uninstall removes the application and background-startup entry but preserves locally collected metrics.

To remove the local metrics too:

Linux / macOS:

```bash
python3 install.py --uninstall --purge-state
```

Windows:

```powershell
py -3 .\install.py --uninstall --purge-state
```

Deleting the repository checkout afterward is optional.

## Platform-specific troubleshooting

### Linux

Service status:

```bash
systemctl --user status catfood-atom.service
```

Recent logs:

```bash
journalctl --user -u catfood-atom.service -n 50 --no-pager
```

### macOS

Confirm the LaunchAgent exists:

```bash
ls ~/Library/LaunchAgents/com.catfood.atom.chatgpt.plist
```

The installed application directory also contains `atomd.stdout.log` and `atomd.stderr.log`.

### Windows

Confirm that the Startup entry exists by opening:

```text
shell:startup
```

You should see `catfood-atom.cmd`.

### The extension is installed but no metrics appear

1. Confirm the extension is enabled.
2. Reload the `chatgpt.com` tab after loading or reloading the extension.
3. Confirm `http://127.0.0.1:8766/health` responds.
4. Use ChatGPT Web for a few seconds.
5. Run `status.py` again.

### Port `8766` is already in use

Another process may already own the local port. Stop the conflicting process, then run the installer again.

## Current scope

This release measures performance. It does not currently optimize ChatGPT Web, bypass rate limits, or alter requests.

## Disclaimer

Unofficial project. Not affiliated with or endorsed by OpenAI.
