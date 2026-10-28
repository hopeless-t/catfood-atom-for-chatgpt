# v0.5.57

- Fixes noisy `BrokenPipeError` / `ConnectionResetError` tracebacks when an analysis or long-poll client closes its local connection before the daemon writes the response.
- Client cancellation is treated as normal transport cancellation; unrelated exceptions are still allowed to surface.
- Reproduced with eight forced early-disconnect probes after the fix: no traceback, daemon remained active.
- Includes the current privacy-preserving server-wait-tail diagnostic and the existing conservative Boost defaults.
