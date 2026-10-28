# v0.5.59

- Fixes cross-tab diagnostic contamination in multi-window Chrome sessions.
- Popup/analysis snapshots now scope to the current sanitized active-surface tab when available instead of aggregating every ChatGPT tab sharing the extension client ID.
- Keeps client-only fallback behavior for legacy/no-surface clients.
- A two-tab failure-world test proves a severe tab and a quiet tab remain isolated.
- Live readback in a three-window session: another active ChatGPT tab remained open in a second window while the current scoped tab reported no findings, no LoAF pressure, and no interaction warning.
- Includes the v0.5.58 adaptive-motion retirement and v0.5.57 client-cancellation traceback fix.
