# v0.5.58

- Retires automatic adaptive-motion style toggling after a long live conversation exposed a feedback oscillator.
- Before the fix, repeated visible LoAFs formed an approximately two-second cadence, including 200–400+ ms stalls.
- After retirement, the same live conversation produced a fresh 12-second observation with 0 visible LoAF events; the following rolling snapshot reported LoAF=0, main-thread pressure=0, interaction warnings=0, and no findings.
- Manual reduce motion remains available and OFF by default.
- Includes the v0.5.57 client-cancellation traceback fix.
