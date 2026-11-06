# CDH G04 immutable release preflight

G04 verifies exact frontend/backend review ZIP identities before safe extraction. It supports two explicit profiles:

- `baseline-defects`: passes only when exact A07/B08 reproduces the centrally observed 6-success/3-failure pattern, including rejection of `UNAVAILABLE` and the daily-median/raw-history mismatch.
- `canonical-fixed`: passes only when all nine crossline calls succeed, `UNAVAILABLE` remains null rather than zero, V2 uses the visible raw-history minimum, and V3 retains its separate daily-median minimum.

Current baseline command:

```powershell
python -m tools.ci_web_g04 --root . --run-id before_a07_b08 --profile baseline-defects --headless
```

Future immutable A08/B09 command (only after exact files and hashes are supplied):

```powershell
python -m tools.ci_web_g04 --root . --run-id after_a08_b09 --profile canonical-fixed --frontend-zip review/releases/CDH_A08_001_REVIEW.zip --frontend-sha <64-hex> --backend-zip review/releases/CDH_B09_001_REVIEW.zip --backend-sha <64-hex> --headless
```

No dependency installation occurs. Missing Node, npm, TypeScript or Chrome is `NOT_RUN_DEPENDENCY` with exit code `3`.
