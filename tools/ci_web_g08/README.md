# G08 exact Windows integration verifier

This verifier is pinned to the R09 A10 R08 continuation, B11, B12, C09, and
F07 release identities. It performs only offline, synthetic, loopback work.

Run from the project root:

```powershell
python -m tools.ci_web_g08 --run-id <unique-id> --receipt-ack input/orchestrator_bundles/UNIFIED_CONTINUOUS_20261105_R09/extracted/RECEIPT_ACK.json
```

The runner audits every input before extraction, reuses `node_modules` only
when the A10 `package-lock.json` hash exactly matches the local dependency
tree, and launches Chrome with a new isolated profile. The frontend server
serves the exact A10 `dist`; its same-origin read-only proxy forwards GET/HEAD
only to the exact B11 WSGI application on `127.0.0.1`.

The B12/C09 probe is immutable dry-run preview only. Default provenance is
denied, the single allowed case is the exact C09 synthetic fixture, and both
the B11 release ZIP and all controlled SQLite fixtures are hashed before and
after. No package install, external request, real data access, database write,
deployment, affiliate click, or transaction is authorized.
