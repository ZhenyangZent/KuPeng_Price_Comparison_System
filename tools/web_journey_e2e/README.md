# H01 offline journey runner

This tool performs two isolated, offline acceptance layers:

1. B06 `CDH-WEB-CONTRACT-V2` probes against a temporary synthetic SQLite copy on `127.0.0.1:8765`.
2. Headless Chromium/Edge CDP journeys against the SHA-bound A05 release build on `127.0.0.1:4173`.

It never loads the project `.env`, downloads a browser, opens Firefox, follows an outbound CTA, or contacts Coupang. Playwright was absent, so the runner uses Node's built-in WebSocket client and an installed Chromium browser with an isolated profile and non-loopback host blocking.

Run from the project root:

```powershell
node --test tests/web/journey_e2e/tool.test.mjs
node tools/web_journey_e2e/run.mjs
```

Evidence is written beneath `reports/H01/evidence`; temporary browser and database state stays beneath `review/H01/runtime`.

