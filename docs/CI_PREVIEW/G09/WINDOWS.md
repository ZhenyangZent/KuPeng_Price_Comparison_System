# G09 Windows replay

Pinned releases:

- `CDH_A_R09_001_REVIEW.zip` — `40e54a65a7c2bfe808bcaa528e75058ab96c98c4f68d9cfa09259b7e5b97a0cd`
- `CDH_B_R07_001_REVIEW.zip` — `6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a`

Run the command in `tools/ci_web_g09/README.md`. A valid scoped result must
show the A11 preview tests, B11 V4/V3 tests, G09 safety tests, and
`a11_b11_daily_dom_browser` as `PASS`. The browser artifact must independently
show four exact visible sections and must contain a viewport screenshot where
both raw and daily values are readable.

The frontend lock is `ba93658c201fc3a802b0dba50038c4a091b06d89fcc34fe8d11754dd9db2a5aa`.
If a matching dependency tree or complete offline package cache is absent,
A11 Vitest must remain `NOT_RUN_DEPENDENCY_UNAVAILABLE`; do not reuse a
different lock or download packages silently.
