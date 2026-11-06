# B06 Price Query API

`price_query` is the standard-library, local-only WSGI reference for `CDH-WEB-CONTRACT-V2`. The prior `/api/v1` envelope remains available for local compatibility; new integration uses `/api/v2`.

The normal server requires an explicit SQLite **copy** below an explicit fixture root, opens it with URI `mode=ro` plus `PRAGMA query_only=ON`, and never migrates or writes that copy. It returns only non-synthetic `USER_ENTERED` and `USER_FILE` observations. Product, variant/SKU, seller, minimum quantity and source price basis remain separate identities.

## Normal copied-data server

```powershell
$env:PYTHONPATH = "services/price_query"
python -m price_query.server --database-copy <approved-copy.sqlite3> --fixture-root <approved-copy-directory> --host 127.0.0.1 --port 8765
```

This command is not authorized to point at the formal user database. Create an approved copy through a separately authorized workflow.

## One-command synthetic E2E server

```powershell
python tests/web/price_query/e2e_fixture_server.py --api-port 8765 --frontend-port 4173
```

The command creates an ephemeral synthetic SQLite fixture, starts only a loopback API on `127.0.0.1:8765`, labels every response `SYNTHETIC_DEMO_ONLY`, and removes the fixture when stopped. The frontend at `127.0.0.1:4173` must proxy only `/api/v2/*` to `http://127.0.0.1:8765`; the API deliberately does not emit permissive CORS headers.

See [CONTRACT_V2.md](CONTRACT_V2.md) and [LOOPBACK_PROXY_CONTRACT.md](LOOPBACK_PROXY_CONTRACT.md).

The implementation does not read `.env`, perform outbound HTTP, expose an affiliate redirect, connect to Coupang, issue notifications, or perform coupon/cart/order/payment operations. Affiliate output stays `UNCONFIGURED` and disabled.
