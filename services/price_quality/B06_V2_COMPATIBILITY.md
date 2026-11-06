# B06 V2 read-only compatibility statement

B07 does not change the B06 HTTP API. A future B08 adapter may map only reviewed B07 output into B06 V2:

- B07 `USER_AUTHORIZED_COPY` maps to B06 `USER_RECORDED`; `SYNTHETIC_FIXTURE` maps to `SYNTHETIC_DEMO_ONLY`.
- Product/seller/variant/quantity/price-basis partitioning is compatible; B07 additionally requires package and condition evidence.
- B07 series without exact identity evidence must not be presented as exact B06 matches.
- B07 M7/M30/M90 `valid_day_count` can supply sample-day fields; missing days remain missing.
- `period_low_twd` is an observation-period low, never a transaction or whole-market low.
- `item_condition=UNKNOWN` remains unknown. B07 must not upgrade it to `NEW`.
- Affiliate fields are outside B07 and remain B06/F controlled and disabled without official evidence.

This is a compatibility proposal, not integration authority.
