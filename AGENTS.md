# Coupang Deal Hunter repository rules

- Read `docs/00_START_HERE.md` and `docs/HANDOFF/MASTER_HANDOFF.md` before changing code.
- Work only in the assigned workline. Preserve immutable review releases and failed evidence.
- Central `RECEIVED` ACK means receipt, never product acceptance. Bind adopted versions to exact SHA-256.
- Use local synthetic data and an isolated private SQLite store. Never read a real `.env`, Firefox profile, credentials, cookies, or production database.
- Do not scrape Coupang, deploy publicly, enable affiliate links or notifications, or perform a shopping transaction without separate authority.
- Publish only files that pass path, source, secret, personal-data, ZIP, and size checks. A public Git branch is a publication action.
- Keep new candidates on a review branch until central acceptance. Follow `docs/HANDOFF/GITHUB_SYNC_POLICY.md`.
