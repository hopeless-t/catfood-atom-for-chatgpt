#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HOME/.local/lib/catfood-atom-for-chatgpt"
SERVICE_DIR="$HOME/.config/systemd/user"
mkdir -p "$APP_DIR" "$SERVICE_DIR"
install -m 0755 "$ROOT/atomd.py" "$APP_DIR/atomd.py"
install -m 0644 "$ROOT/systemd/catfood-atom.service" "$SERVICE_DIR/catfood-atom.service"
systemctl --user daemon-reload
systemctl --user enable --now catfood-atom.service
for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:8766/health; then break; fi
  sleep .1
done
echo
echo "Load this folder from chrome://extensions -> Developer mode -> Load unpacked:"
echo "$ROOT/extension"
