# B14 strict JSON ingress and immutable preview

B14 is a versioned wrapper over the exact B13/B12/C09/B11 offline stack. It rejects an exact duplicate JSON member name in every object before semantic validation or provenance evaluation. JSON member comparison is case-sensitive after Unicode escape decoding: `sku_id` plus `sku_\u0069d` is a duplicate, while `sku_id` plus `SKU_ID` is not an ingress duplicate and remains subject to the downstream exact schema.

The rejection response contains only a stable error code and the SHA-256 of the complete input bytes. It never returns the duplicate member name, value, raw record, or local path. CSV continues through the exact B13 controls. The preview performs no database writes, source collection, URL dereference, CTA action, or commerce action.

The read-only interface is `GET /api/import-preview/v2/status` and `GET /api/import-preview/v2/history/<identity_key>`. It binds only to `127.0.0.1`, denies Origin-bearing requests, rejects non-GET methods and emits no CORS allowance.

Windows check mode:

```powershell
python -m import_staging_b14.server --input <fixture.json> --input-root <fixture-dir> --dependency-root <release-dir> --b13-release <B13.zip> --b12-release <B12.zip> --c09-release <C09.zip> --b11-release <B11.zip> --as-of 2026-11-05T06:00:00Z --check
```
