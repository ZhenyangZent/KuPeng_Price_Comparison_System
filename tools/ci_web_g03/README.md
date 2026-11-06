# CDH G03 reproducible web CI

This module verifies the exact A06, B06, B07 and F02 review archives, safely extracts them into an isolated local workspace, and executes their offline web/API contract suites. It never installs dependencies and never contacts product sources.

Run from the repository root:

```powershell
python -m tools.ci_web_g03 --root . --run-id local
```

Exit codes: `0` pass, `2` test failure, `3` dependency unavailable, `4` archive/security failure, `5` version conflict, `6` runner error.

Node dependencies are reused only when the local `package-lock.json` has the exact same SHA-256 as A06. Missing Node, npm, Chrome or a matching dependency tree yields `NOT_EXECUTED_DEPENDENCY`; no install is attempted.
