# G06 exact-release V4 integration verifier

The runner accepts only explicit frontend/backend ZIP paths and full SHA-256 values. It validates identity, CRC, the release manifest, archive paths, sensitive filenames, and likely secrets before isolated extraction.

Profiles:

- `a09-b10-expected-fail`: starts the exact B10 WSGI application on an ephemeral `127.0.0.1` port, performs real HTTP Search and Detail requests, then passes those exact responses to the exact A09 parser. Success means the two known wire failures were reproduced; it is not an integration pass.
- `a10-b11-exact`: reserved for exact received A10/B11 releases. Missing inputs, browser, dependency lock, or an exact-release E2E entry point must be reported as `NOT_RUN_*`; no stub or frozen HTML can satisfy the gate.

No package install, external request, deployment, real data, affiliate click, or transaction is performed.
