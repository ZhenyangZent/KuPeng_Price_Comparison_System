# B14/C11 continuation gate

Current status: `NOT_RUN_INPUT_UNAVAILABLE`.

R10 did not provide exact B14 or C11 release filenames and SHA-256 values, and
neither release was present in `review/releases` at final run time. G09 did not
substitute B13 or C10.

When independently authorized exact inputs arrive, the continuation must:

1. verify ZIP SHA-256, CRC, manifest coverage, and receipt identity;
2. prove duplicate JSON keys are rejected before semantic parsing;
3. drive the exact authorized synthetic record through immutable preview;
4. retain `database_write_count=0`, `external_request_count=0`, and
   `collection_authorized=false`;
5. preserve the failed B13 duplicate-key evidence as history.
