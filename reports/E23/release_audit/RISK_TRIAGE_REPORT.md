# E23 blocked archive triage

The seven original 20-file audit checkpoints remain immutable. A separate metadata-only pass classified all 134 previously blocked originals. It read outer SHA-256 and ZIP central directories, but opened **zero member payloads**. The categories are next review gates, not permission to publish:

- 44 originals contain filenames that identify a private database, credential, cookie, environment file or similarly restricted member. Their original bytes stay excluded. A public derivative would require a separate inventory, omission log, new SHA-256 and full review of every retained member.
- 9 originals have path, email, phone or credential-pattern findings requiring targeted redaction review. They are not safe to publish unchanged.
- 50 need deeper media or nested-archive provenance review. A screenshot or synthetic-looking image is not automatically safe: pixels, metadata, rights and provenance still need checking in isolation.
- 31 need deeper bounded text and manifest review. Some include logs or large project indexes; those are not automatically safe because their content may contain private paths or sensitive values.

Per-file categories and outer SHA are saved in `triage_batch_00.json` through `triage_batch_06.json`. No additional original was published in this pass. Previously published six exact-byte historical assets remain unchanged. E23 does not assert that all 134 have completed content review; the risk grouping gives D14 and the next E batch stable, explicit work queues.

The original 140-file baseline is frozen in `BASELINE_140.json`; later releases use `incremental_snapshot_000.json` and separate audit checkpoints. Snapshot 000 was created before H13 REV2 and E23 REV3 were registered in the release ledger, so those two rows correctly retain the **at-snapshot** ledger identity status. The ledger now records both exact hashes and central decisions; do not rewrite snapshot 000 to make the past appear different.
