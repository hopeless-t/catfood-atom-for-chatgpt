# CATFOOD Atom for ChatGPT

A small local performance observer for ChatGPT Web.

It helps answer a simple question: **when ChatGPT Web feels slow, where is the delay coming from?**

CATFOOD Atom is currently an observer, not a speed-up extension. It does not change, cancel, replay, or replace ChatGPT requests.

## What it can show

- Request timing and TTFB
- HTTP status counts, including 429 responses
- Request bursts and concurrent activity
- Interaction latency
- DOM update volume
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

The local service accepts metrics on loopback only (`127.0.0.1`).

## Requirements

- Linux
- A working `systemd --user` session
- Python 3
- `curl`
- Google Chrome or Chromium with support for unpacked Manifest V3 extensions

You do not need Node.js, npm, Docker, or a cloud account.

## Install

### 1. Clone the repository

```bash
git clone https://github.com/hopeless-t/catfood-atom-for-chatgpt.git
cd catfood-atom-for-chatgpt
```

### 2. Run the installer

```bash
./install.sh
```

The installer:

1. Copies the local metrics service to `~/.local/lib/catfood-atom-for-chatgpt/`.
2. Installs a user service at `~/.config/systemd/user/catfood-atom.service`.
3. Starts or restarts the local service on `127.0.0.1:8766`.
4. Prints the path of the Chrome extension directory.

A successful install prints a health response similar to:

```json
{"ok":true,"version":"0.1.1","pid":12345}
```

### 3. Load the Chrome extension

Open:

```text
chrome://extensions
```

Then:

1. Enable **Developer mode**.
2. Click **Load unpacked**.
3. Select the `extension/` directory inside this repository.
4. Confirm that **CATFOOD Atom for ChatGPT** appears and is enabled.
5. Reload any already-open `chatgpt.com` tabs once.

No Chrome Web Store installation is required.

## Verify the installation

### Check the local service

```bash
curl http://127.0.0.1:8766/health
```

Expected result:

```json
{"ok":true,"version":"0.1.1","pid":12345}
```

You can also inspect the user service:

```bash
systemctl --user status catfood-atom.service
```

### Check that metrics are arriving

Open `https://chatgpt.com/`, use it normally for a few seconds, then run:

```bash
./status.py
```

Example output:

```text
CATFOOD Atom for ChatGPT
requests: 18 issued / 18 completed; peak 6 /s; max active 4
TTFB: 420.5 ms; HTTP 429: 0
input: 32.0 ms; queue: 4.0 ms
render: 245 DOM updates; 0.0 ms long tasks; max gap 26.4 ms
```

The exact values will vary by session and machine.

## Use

Leave the extension enabled and use ChatGPT Web normally.

For a quick terminal summary:

```bash
./status.py
```

The extension observes browser-side performance signals and sends only the allowed metric fields to the local service.

## Update

From the repository directory:

```bash
git pull
./install.sh
```

Then open `chrome://extensions` and click **Reload** on **CATFOOD Atom for ChatGPT** so Chrome picks up extension changes.

## Uninstall

First remove **CATFOOD Atom for ChatGPT** from `chrome://extensions`.

Then run:

```bash
systemctl --user disable --now catfood-atom.service
rm -f "$HOME/.config/systemd/user/catfood-atom.service"
systemctl --user daemon-reload
rm -rf "$HOME/.local/lib/catfood-atom-for-chatgpt"
```

The local metrics log is stored separately. To delete it too:

```bash
rm -rf "$HOME/.local/state/catfood-atom"
```

Deleting the repository checkout after uninstall is optional.

## Troubleshooting

### `./status.py` cannot connect

Check the service:

```bash
systemctl --user status catfood-atom.service
```

Recent service logs:

```bash
journalctl --user -u catfood-atom.service -n 50 --no-pager
```

### The extension is installed but no metrics appear

1. Confirm the extension is enabled in `chrome://extensions`.
2. Reload the `chatgpt.com` tab after loading or reloading the extension.
3. Use ChatGPT Web for a few seconds.
4. Run `./status.py` again.

### Port `8766` is already in use

Check what is listening on it:

```bash
ss -ltnp | grep ':8766'
```

CATFOOD Atom expects its local service to own `127.0.0.1:8766`.

## Current scope

This release measures performance. It does not currently optimize ChatGPT Web, bypass rate limits, or alter requests.

## Disclaimer

Unofficial project. Not affiliated with or endorsed by OpenAI.
