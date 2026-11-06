# CDH G05 V4 coupon-history preflight

Run the exact R06 baseline from the project root:

```powershell
python -m tools.ci_web_g05 --root . --run-id baseline --headless
```

The runner requires exact A08 and B09-002 archives plus an exact lock-matched pre-provisioned Node tree. It performs no installation and uses only loopback synthetic services. Missing dependencies are `NOT_RUN_DEPENDENCY`.

V4 coupon evaluation is TEST_ONLY. The old 9/9 V2/V3 contract uses the acknowledged G04 helper dependency included in the review package. A09/B10 crossline/headless remains `NOT_RUN_INPUT_UNAVAILABLE` until both immutable releases and exact hashes are available.
