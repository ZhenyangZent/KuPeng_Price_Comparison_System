from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .audit import AuditResult, Finding


DATA_CLASSIFICATIONS = frozenset({"SYNTHETIC_DEMO_ONLY", "USER_PROVIDED_OBSERVATIONS"})


def _finding(code: str, severity: str, location: str, detail: str, owner: str) -> Finding:
    return Finding(code, severity, location, detail, owner)


def audit_crossline_contract(
    search: dict[str, Any],
    detail: dict[str, Any],
    affiliate_response: dict[str, Any],
    *,
    variant_query_total: int,
) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    search_classification = search.get("data_classification")
    if search_classification not in DATA_CLASSIFICATIONS:
        findings.append(_finding("SEARCH_DATA_CLASSIFICATION_MISSING", "HIGH", "GET /api/v1/products", "Response must distinguish synthetic demo data from approved user observations.", "B"))
    if detail.get("data_source_status") != "USER_RECORDED_ONLY":
        findings.append(_finding("DETAIL_DATA_SOURCE_STATUS_MISSING", "HIGH", "GET /api/v1/products/{id}", "Detail response must carry the source trust status.", "B"))
    detail_classification = detail.get("data_classification")
    if detail_classification not in DATA_CLASSIFICATIONS:
        findings.append(_finding("DETAIL_DATA_CLASSIFICATION_MISSING", "HIGH", "GET /api/v1/products/{id}", "Detail response must carry the same runtime classification as search.", "B"))
    elif search_classification in DATA_CLASSIFICATIONS and detail_classification != search_classification:
        findings.append(_finding("DATA_CLASSIFICATION_MISMATCH", "HIGH", "search/detail", "Search and detail classifications disagree.", "A/B"))
    nested = affiliate_response.get("affiliate")
    if not isinstance(nested, dict):
        findings.append(_finding("AFFILIATE_DTO_NOT_NESTED", "HIGH", "GET /api/v1/products/{id}/affiliate", "Freeze one DTO shape: schema_version + product_id + affiliate object.", "B/F"))
    if variant_query_total < 1:
        findings.append(_finding("VARIANT_SEARCH_CONTRACT_MISMATCH", "HIGH", "GET /api/v1/products?q={variant}", "UI promises SKU/spec search but backend returned no variant match.", "A/B"))
    for index, offer in enumerate(detail.get("offers", ()) if isinstance(detail.get("offers"), list) else ()):
        if isinstance(offer, dict) and offer.get("item_condition") == "NEW" and offer.get("item_condition_source") not in {"USER_ENTERED", "USER_FILE", "VERIFIED_PROVIDER"}:
            findings.append(_finding("ITEM_CONDITION_UNPROVEN", "HIGH", f"detail.offers[{index}]", "NEW requires an observed/verified source; otherwise return UNKNOWN or null.", "B"))
    return tuple(findings)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def audit_frontend_backend_sources(frontend_root: str | Path, backend_root: str | Path) -> AuditResult:
    frontend = Path(frontend_root)
    backend = Path(backend_root)
    types_text = _read(frontend / "src" / "types.ts")
    affiliate_text = _read(frontend / "src" / "affiliate.ts")
    env_text = _read(frontend / ".env.example")
    vite_text = _read(frontend / "vite.config.ts")
    server_text = _read(backend / "price_query" / "server.py")
    api_text = _read(backend / "price_query" / "api.py")
    return _audit_source_texts(types_text, affiliate_text, env_text, vite_text, server_text, api_text)


def _audit_source_texts(
    types_text: str,
    affiliate_text: str,
    env_text: str,
    vite_text: str,
    server_text: str,
    api_text: str,
) -> AuditResult:
    findings: list[Finding] = []

    if 'data_classification: "SYNTHETIC_DEMO_ONLY"' in types_text and "USER_PROVIDED_OBSERVATIONS" not in types_text:
        findings.append(_finding("FRONTEND_CLASSIFICATION_SYNTHETIC_ONLY", "HIGH", "A/src/types.ts", "Frontend type cannot represent approved user-provided observations.", "A"))

    required_tokens = ("allowed", "bound_sku_id", "expires_at", "provider_status", "disclosure")
    missing = [token for token in required_tokens if token not in affiliate_text.casefold()]
    if missing:
        findings.append(_finding("FRONTEND_AFFILIATE_GUARD_INCOMPLETE", "CRITICAL", "A/src/affiliate.ts", "Missing fail-closed checks: " + ",".join(missing), "A/F"))

    env_match = re.search(r"(?m)^VITE_CDH_API_BASE=(\S+)$", env_text)
    port_match = re.search(r'default=(\d+)\)', server_text)
    if env_match and port_match:
        frontend_port = urlparse(env_match.group(1)).port
        backend_port = int(port_match.group(1))
        if frontend_port != backend_port:
            findings.append(_finding("LOOPBACK_PORT_MISMATCH", "HIGH", "A/.env.example vs B/server.py", f"Frontend uses {frontend_port}; backend defaults to {backend_port}.", "A/B"))
    if "proxy:" not in vite_text and "proxy " not in vite_text:
        findings.append(_finding("SAME_ORIGIN_PROXY_MISSING", "HIGH", "A/vite.config.ts", "Use a loopback-only same-origin proxy for local integration.", "A"))
    if "access-control-allow-origin" not in api_text.casefold() and "proxy:" not in vite_text:
        findings.append(_finding("LOCAL_TRANSPORT_NOT_INTEGRATED", "HIGH", "A/B local HTTP boundary", "Neither a same-origin proxy nor a restricted CORS policy is configured.", "A/B"))

    bytes_scanned = sum(len(text.encode("utf-8")) for text in (types_text, affiliate_text, env_text, vite_text, server_text, api_text))
    return AuditResult(tuple(findings), 6, bytes_scanned)


def _zip_text(archive: zipfile.ZipFile, suffix: str) -> str:
    matches = [name for name in archive.namelist() if name.replace("\\", "/").endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(f"TARGET_ZIP_MEMBER_COUNT:{suffix}:{len(matches)}")
    return archive.read(matches[0]).decode("utf-8")


def audit_frontend_backend_release_zips(a05_zip: str | Path, b05_zip: str | Path) -> AuditResult:
    with zipfile.ZipFile(a05_zip) as frontend, zipfile.ZipFile(b05_zip) as backend:
        return _audit_source_texts(
            _zip_text(frontend, "apps/price-web/frontend/src/types.ts"),
            _zip_text(frontend, "apps/price-web/frontend/src/affiliate.ts"),
            _zip_text(frontend, "apps/price-web/frontend/.env.example"),
            _zip_text(frontend, "apps/price-web/frontend/vite.config.ts"),
            _zip_text(backend, "services/price_query/price_query/server.py"),
            _zip_text(backend, "services/price_query/price_query/api.py"),
        )
