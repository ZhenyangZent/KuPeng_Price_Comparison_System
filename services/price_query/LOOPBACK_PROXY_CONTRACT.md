# Loopback proxy contract — ports 4173 and 8765

This contract is for local E2E development only. It is not public deployment authority.

- Browser-visible origin: `http://127.0.0.1:4173`
- API listener: `http://127.0.0.1:8765`
- Allowed proxy source path: `/api/v2/*`
- Allowed proxy target: the identical path on `http://127.0.0.1:8765`
- Allowed listener hosts: `127.0.0.1` or `localhost`; wildcard and LAN binds are forbidden.
- The frontend proxy must reject user-controlled target hosts, absolute-form URLs, path traversal and non-HTTP upgrade/tunnel requests.
- The API emits no `Access-Control-Allow-Origin:*`; browser requests remain same-origin through the 4173 proxy.
- Affiliate `click_url` is data only and is never a proxy target. `UNCONFIGURED`, null, unbound or unverified values keep the CTA disabled.

The backend can be started with the one-command E2E fixture documented in `README.md`. The A workline owns its frontend proxy implementation; B does not modify A files.
