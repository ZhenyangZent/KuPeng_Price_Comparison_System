# C11 consumer contract for A12/G09

Input must use `CDH-C11-B13-C10-BINDING-1` and bind the exact B13 and C10
release SHA-256 values, including B14
`db112964be7a5ada7b393902ee7a6de9d5a328b15b97880981046eef7cc9a6e9`.
The only admissible input hash is the pinned synthetic C09 bridge fixture.

Output uses `CDH-C11-SAFE-PREVIEW-DTO-1`.  Consumers may show this output only
inside an isolated synthetic test.  `PREVIEW_ALLOWED_TEST_ONLY` is not source
collection authority, production display authority, history-write authority,
or affiliate-link authority.

The output keeps `collection`, `history_retention`, `local_display`, and
`link_disclosure` separate.  For the only allowed fixture, the first three are
`ALLOW_TEST_ONLY`; link disclosure is `NOT_REQUESTED` and false.  Any record
rejection blocks all four permissions and removes identity, price and retention
from that record.

The adapter preserves `0` and `null` as different price values.  It exposes
only `before_coupon_price_twd`, `display_price_twd`, and
`required_total_twd`.  It never exposes B13 source/evidence identifiers, raw
record hashes, observations, history candidates, or raw content.

Duplicate JSON keys are rejected by exact B14 before semantics and again at the
strict C11 envelope entrypoint.  A legacy B13 DTO, duplicate-related response,
or input outside the pinned fixture is denied and cannot be reinterpreted as an
allow.
