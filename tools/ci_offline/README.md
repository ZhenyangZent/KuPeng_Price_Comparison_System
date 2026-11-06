# Offline CI runner

`check_project` is a standard-library Python entrypoint for bounded local checks. It never installs packages, calls `npm install`/`npx`, reads the root `.env`, pushes Git, deploys, or contacts Coupang.

```powershell
python -m tools.ci_offline.check_project --output-dir reports/G02/run --suite g02_self --suite frontend_vitest --scan-source tools/ci_offline --scan-source tests/ci_offline
```

Review ZIP identity uses `PATH::SHA256`:

```powershell
python -m tools.ci_offline.check_project --suite g02_self --review-zip review/releases/CDH_G01_001_REVIEW.zip::ea2a3ef3f524191f82708eb800993a37fe4fab09b7922ebea3c6b4b3754856a3
```

Exit codes are stable: `0` pass, `2` executed test failure, `3` missing dependency/policy skip, `4` archive or secret-scan failure, `5` workline version conflict, `6` runner error, `64` CLI usage error.
