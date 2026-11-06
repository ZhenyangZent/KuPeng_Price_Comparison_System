# C01 Architecture

The core is an offline pipeline:

1. Normalize typed synthetic data into offer, scenario, evidence, and money states.
2. Calculate one fixed-quantity scenario using exact integer minor units and `Fraction` for unit cost.
3. Build a pre-event history snapshot from first-per-UTC-hour samples and Asia/Taipei completed days.
4. Run one pure notification policy with hard gates before S0/S1/S2/S3/TARGET/O1/O2.
5. Atomically persist `deal_events` and `notification_outbox` through one `EventStore` write path using a canonical scenario/quote semantic key.
6. Claim an event in a short transaction, release the writer lock, call the mock sink, then finalize after a second current-state validation.

All identities use NFC-normalized canonical JSON plus SHA-256. Quote, policy context, baseline, decision, current state and event must bind to the same scenario scope. Raw observations and daily statistics are separate SQLite tables, and source published/observed/received clocks are retained. `DELIVERED` means only that the local mock sink accepted the payload.

