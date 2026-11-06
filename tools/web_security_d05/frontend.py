from __future__ import annotations

import re

from .models import Check, Finding


def assess_frontend(
    *,
    typescript_types: str,
    local_api: str,
    affiliate: str,
    app: str,
    vite_config: str,
    index_html: str,
    api_source: str,
) -> tuple[list[Check], list[Finding]]:
    checks: list[Check] = []
    findings: list[Finding] = []

    v2_schema = 'SCHEMA_VERSION = "CDH-WEB-CONTRACT-V2"' in typescript_types
    v2_path = 'const API_ROOT = "/cdh-local-api/api/v2"' in local_api
    checks.append(Check("A06_CONSUMES_B06_V2", v2_schema and v2_path, f"schema_v2={v2_schema}; api_v2={v2_path}"))
    if not (v2_schema and v2_path):
        findings.append(Finding(
            "D05-P1-001", "P1", "A", "A06 performs a frozen-contract downgrade to B06 V1",
            "A06 apps/price-web/frontend/src/types.ts and src/localApi.ts",
            "The browser is locked to CDH-WEB-CONTRACT-V1 and /api/v1 while the current B06 and F02 integration contract is the nested V2 envelope. Classification is remapped client-side and F02 V2 output is not directly consumable.",
            "Read SCHEMA_VERSION and API_ROOT from the exact A06 ZIP; compare them with B06 CONTRACT_V2.md and F02_V2_BINDING_CONTRACT.md.",
            "Add an A-line integration test that serves exact B06 V2 Search/Detail/Affiliate payloads and rejects any V1 response or flattened Affiliate envelope.",
        ))

    loopback = 'host: "127.0.0.1"' in vite_config and 'target: "http://127.0.0.1:8765"' in vite_config
    relative_fetch = 'const API_ROOT = "/cdh-local-api/' in local_api
    no_cors = "Access-Control-Allow-Origin" not in api_source
    checks.append(Check("LOOPBACK_SAME_ORIGIN_NO_CORS", loopback and relative_fetch and no_cors, f"fixed_loopback={loopback}; relative_fetch={relative_fetch}; cors_absent={no_cors}"))
    if not (loopback and relative_fetch):
        findings.append(Finding(
            "D05-P0-001", "P0", "A", "Local API routing is not fixed to same-origin loopback",
            "A06 vite.config.ts and src/localApi.ts",
            "A user-controlled or non-loopback target would create an SSRF or cross-origin data exposure path.",
            "Inspect Vite proxy target and browser API root in the exact A06 archive.",
            "Assert the only target is http://127.0.0.1:8765 and all browser requests use the fixed relative prefix.",
        ))

    injection_tokens = ("dangerouslySetInnerHTML", ".innerHTML=", ".innerHTML =", "document.write(")
    injection_free = not any(token in app for token in injection_tokens)
    checks.append(Check("REACT_TEXT_RENDERING_NO_RAW_HTML", injection_free, "raw HTML sink absent" if injection_free else "raw HTML sink present"))
    if not injection_free:
        findings.append(Finding(
            "D05-P0-002", "P0", "A", "Untrusted product data reaches a raw HTML sink",
            "A06 apps/price-web/frontend/src/App.tsx",
            "Product and source text can become script-capable markup.",
            "Search the exact A06 source for raw HTML assignment APIs.",
            "Render an HTML/script payload and assert it remains inert text in the DOM.",
        ))

    cta_fail_closed = (
        "approved_provider_id: null" in affiliate
        and "official_hosts: []" in affiliate
        and "return null" in affiliate
        and "safeAffiliateUrl" in app
        and "disabled" in app
        and 'rel="noopener noreferrer sponsored"' in app
    )
    checks.append(Check("CTA_FAIL_CLOSED_WITHOUT_TW_AUTHORITY", cta_fail_closed, f"fail_closed={cta_fail_closed}"))
    if not cta_fail_closed:
        findings.append(Finding(
            "D05-P0-003", "P0", "A/F", "Affiliate CTA is not demonstrably fail-closed",
            "A06 affiliate.ts and App.tsx",
            "A URL may become clickable without the frozen Taiwan authority and exact binding gates.",
            "Inspect policy defaults, safeAffiliateUrl call site, disabled fallback, and outbound rel attributes.",
            "Run the hostile URL, wrong identity, expired, revoked, and no-authority matrix against the rendered CTA.",
        ))

    csp = re.search(r"http-equiv\s*=\s*[\"']Content-Security-Policy[\"']", index_html, re.I) is not None
    checks.append(Check("STATIC_DOCUMENT_CSP", csp, "CSP meta present" if csp else "CSP meta absent"))
    if not csp:
        findings.append(Finding(
            "D05-P2-001", "P2", "A", "Static frontend has no Content Security Policy",
            "A06 apps/price-web/frontend/index.html and dist/index.html",
            "React escaping and fail-closed links currently reduce exploitability, but there is no browser-enforced script/connect/frame boundary if a future sink or dependency regression appears.",
            "Inspect the exact source and built index.html for a CSP meta or documented response-header policy.",
            "Add a build assertion for a restrictive local-only CSP and a browser smoke test that rejects non-loopback connect-src.",
        ))

    headers = {name for name in ("Content-Security-Policy", "Referrer-Policy", "X-Frame-Options", "Permissions-Policy") if name in api_source}
    checks.append(Check("LOCAL_API_DEFENSE_HEADERS", len(headers) == 4, f"present={sorted(headers)}"))
    if len(headers) != 4:
        findings.append(Finding(
            "D05-P2-002", "P2", "B", "Loopback API lacks a complete defense-in-depth header set",
            "B06 services/price_query/price_query/api.py",
            "The JSON API correctly sets no-store and nosniff and exposes no CORS allow-origin, but does not emit all of CSP, Referrer-Policy, frame, and Permissions-Policy defenses.",
            "Call the exact B06 WSGI app and enumerate response headers.",
            "Add a B-line header test; preserve no CORS and no-store while adding reviewed local-only security headers.",
        ))
    return checks, findings
