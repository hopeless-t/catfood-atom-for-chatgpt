# CATFOOD Atom for ChatGPT

A small local performance observer for ChatGPT Web.

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

It does not store conversation text, request or response bodies, cookies, authorization headers, raw URLs, or query strings.

## Install

Linux with a systemd user session and Chrome/Chromium:

```bash
./install.sh
```

Then open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**, and select the `extension/` directory printed by the installer.

For a terminal summary:

```bash
./status.py
```

## Disclaimer

Unofficial project. Not affiliated with or endorsed by OpenAI.
