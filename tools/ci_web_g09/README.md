# G09 A11/B11 daily-DOM verifier

This Windows verifier is pinned to A11 R09 and B11 R07. It audits both
release archives before isolated extraction, serves the exact A11 `dist`, and
connects it to the exact B11 WSGI application over ephemeral `127.0.0.1`
ports. Chrome always receives a fresh isolated profile.

The browser gate requires four separate visible sections:

- raw before coupon;
- raw confirmed after coupon;
- daily before coupon;
- daily confirmed after coupon.

It checks the visible date, representative price, sample count, section count,
wire/DOM count equality, empty-history behavior, disabled CTA, network origin,
and hostile Host/Origin rejection. Network JSON alone cannot pass this gate.

Run from the project root:

```powershell
python -m tools.ci_web_g09 --run-id <unique-id> --receipt-ack input/orchestrator_bundles/UNIFIED_CONTINUOUS_20261105_R10/extracted/RECEIPT_ACK_R09.json
```

B14/C11 preview integration remains `NOT_RUN_INPUT_UNAVAILABLE` unless their
exact ZIP filenames and full SHA-256 values are supplied by later authority.
