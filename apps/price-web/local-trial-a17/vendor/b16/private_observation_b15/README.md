# B15 private local manual observations

B15 implements the R11 `preview → explicit confirm → isolated SQLite commit → search/detail readback` flow. Preview is memory-only. A commit requires a valid loopback Host, an allowed Origin when present, the session CSRF token, an unexpired one-time confirmation token and `explicit_confirm=true`.

The server chooses the database path; requests cannot provide a path. The only production location is `data/private_user_observations_b15/private_user_observations.sqlite3`. Automated tests use temporary controlled roots under `review/B15`. Existing B11/B14 databases and releases are read only and SHA-bound.

REV2 requires an explicit `allowed_project_root`. It rejects every existing symlink, junction, or reparse component from the filesystem anchor through the project root and storage targets, checks lexical and resolved containment, and repeats identity checks around directory creation, database opening, backup creation, cleanup, and commit. A missing HTTP Host is rejected.

Pending previews expire after 10 minutes and are bounded to 128 entries and 2 MiB. Backups retain at most 8 files for 30 days within a 256 MiB quota, while attempting to preserve the two newest recovery points; if the minimum recovery set cannot fit, the new commit fails closed.

Manual coupon prices are always stored as `user_reported_after_coupon`; `confirmed_after_coupon` remains empty because a private manual entry does not independently prove platform eligibility. Unknown shipping keeps required totals null. The read adapter uses B11-style Search/Detail envelopes with the distinct schema `CDH-PRIVATE-PRICE-V1` and private classification.

Run a no-database check:

```powershell
python -m private_observation_b15.server --check
```
