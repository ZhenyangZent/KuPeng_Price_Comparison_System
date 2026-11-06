# B16 private-local CSV/JSON batch import

B16 composes the approved B15 REV2 local service. It does not create a second price database and does not change the B15 schema. It adds bounded file parsing, no-write preview, explicit confirmation, atomic multi-row commit, idempotent duplicate handling, and row-level error reporting.

Run an offline configuration check from the project root:

```text
python -m private_batch_import_b16 --check
```

The package roots `services/private_batch_import_b16` and `services/private_observation_b15` must both be on `PYTHONPATH` when launched outside the included review replay. The server binds only `127.0.0.1`. Tests use temporary project roots and synthetic files; they never select the formal database.

See `API_CONTRACT.md` and `examples/` for A15 integration inputs and response examples.

