# H02 A06 + B06 offline E2E

H02 verifies the exact received A06 and B06 review ZIPs, safely extracts immutable baselines beneath `review/H02/baselines`, starts the extracted A06 Vite preview with its fixed `/cdh-local-api` proxy, starts the extracted B06 implementation on loopback, and drives the real page with headless Edge CDP.

Commands from the project root:

```powershell
python tools/web_journey_h02/prepare_baselines.py
node --test tests/web/journey_h02/tool.test.mjs
node tools/web_journey_h02/run.mjs
```

No package is downloaded. No root `.env`, Firefox profile, Registry, external Coupang endpoint, affiliate link, deployment, or transaction is accessed.

