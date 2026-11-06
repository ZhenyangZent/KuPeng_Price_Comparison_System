# A02 Receipt Contract Conformance

Frozen input: `CDH_AB_RECEIPT_CONTRACT_V1.md`. A02 does not modify this contract or `CDH-EXCHANGE-1`.

| Contract field or rule | A02 behavior |
|---|---|
| `receipt_version` | Exact `CDH-D01-RECEIPT-1`; future versions fail closed. |
| `exchange_version` | Exact `CDH-EXCHANGE-1`. |
| `generated_at_utc` | UTC timezone required, excessive future rejected, older than 24 hours labelled stale. |
| `source_status` | Exact `SOURCE_BLOCKED`; receipt cannot grant source permission. |
| `snapshot_sha256` | Exactly 64 lowercase hex and compared with exact `latest.json` bytes. Snapshot contract is independently validated after hash match. |
| `entries` | Bounded to 10,000, exact required fields, no duplicates/case collisions. |
| `filename` | Top-level `submission_<canonical-uuid>.json`; separators, traversal and noncanonical case rejected. |
| `file_sha256` | Exactly 64 lowercase hex and compared with the current bounded inbox file. |
| `status` | Closed set: `IMPORTED`, `DUPLICATE_NOOP`, `QUARANTINED`, `RETRY_NEEDED`. |
| Processed | Only matching filename + SHA with `IMPORTED`/`DUPLICATE_NOOP`. |
| Pending | New/unlisted file, changed hash, or matching `RETRY_NEEDED`. |
| Error | Matching `QUARANTINED`; never counted imported. |
| Missing/malformed/inconsistent | Counts become `狀態未知` or `正在同步／尚未一致`; raw count stays explicitly informational. |

Receipt size is bounded to 5 MiB; inbox items to 1 MiB; snapshots to 50 MiB. Receipt data is never interpreted as a command, URL, filesystem path, qualification upgrade, or notification instruction.
