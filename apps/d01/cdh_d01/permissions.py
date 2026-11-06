from __future__ import annotations

import csv
from pathlib import Path

from .database import insert_permission_rows


REVIEWED_AT = "2026-11-02T15:30:00Z"


BASELINE_PERMISSIONS: list[dict[str, str]] = [
    {
        "source_id": "coupang_tw_public", "operation": "AUTOMATED_PRODUCT_OR_PRICE_COLLECTION",
        "evidence_url": "https://www.tw.coupang.com/np/policies/terms",
        "evidence_summary": "G0 found prior written consent required; direct policy readback returned HTTP 403 on 2026-11-02, so no newer permission was established.",
        "scope": "PUBLIC_DOCUMENT_RESEARCH_ONLY; no SKU fetch", "reviewed_at_utc": REVIEWED_AT,
        "status": "RESTRICTED", "quota": "N/A",
    },
    {
        "source_id": "coupang_seller_open_api", "operation": "BUYER_MARKET_DISCOVERY",
        "evidence_url": "https://developers.coupang.com/zh-TW/getting-started/issue-open-api-keynew",
        "evidence_summary": "Official key issuance requires a verified active Wing seller; this does not authorize buyer-side market discovery.",
        "scope": "AUTHORIZED_SELLER_OPERATIONS_ONLY", "reviewed_at_utc": REVIEWED_AT,
        "status": "RESTRICTED", "quota": "PROVIDER_CONTROLLED",
    },
    {
        "source_id": "coupang_partners_product_api", "operation": "TAIWAN_PRIVATE_PRICE_MONITORING",
        "evidence_url": "https://partners.coupangcdn.com/partners-guide/partners-guide-20240716100922.pdf",
        "evidence_summary": "Affiliate approval, Taiwan coverage, persistence, and private comparison rights are not established.",
        "scope": "UNVERIFIED_AFFILIATE_SCOPE", "reviewed_at_utc": REVIEWED_AT,
        "status": "UNVERIFIED", "quota": "SEARCH_10_PER_HOUR_IN_GUIDE",
    },
    {
        "source_id": "coupang_wow_official", "operation": "POLICY_DOCUMENT_RESEARCH",
        "evidence_url": "https://tw.coupangcorp.com/archives/6646/",
        "evidence_summary": "Official 2026-10-17 article describes general WOW/Rocket shipping policy; it does not prove account, SKU, stock, quantity, fee, or checkout eligibility.",
        "scope": "GENERAL_POLICY_REFERENCE_ONLY", "reviewed_at_utc": REVIEWED_AT,
        "status": "POLICY_REFERENCE_ONLY", "quota": "MANUAL_DOCUMENT_RESEARCH",
    },
    {
        "source_id": "coupang_promo_official", "operation": "MANUAL_PROMO_CLUE_RESEARCH",
        "evidence_url": "https://tw.coupangcorp.com/archives/6698/",
        "evidence_summary": "Official 2026-10-27 announcement states selected new-user products start at TWD 1; activity details and items remain subject to the activity page.",
        "scope": "PROMO_CLUE_ONLY; not an observed SKU price", "reviewed_at_utc": REVIEWED_AT,
        "status": "DOCUMENT_RESEARCH_ONLY", "quota": "MANUAL_DOCUMENT_RESEARCH",
    },
    {
        "source_id": "ptt_lifeismoney_atom", "operation": "CONTINUOUS_POLLING",
        "evidence_url": "https://www.ptt.cc/atom/Lifeismoney.xml",
        "evidence_summary": "Interface existence does not grant continuous polling, retention, or redistribution rights.",
        "scope": "UNVERIFIED_COMMUNITY_CLUE", "reviewed_at_utc": REVIEWED_AT,
        "status": "UNVERIFIED", "quota": "UNKNOWN",
    },
    {
        "source_id": "dcard", "operation": "AUTOMATED_CONTENT_COLLECTION",
        "evidence_url": "https://www.dcard.tw/terms",
        "evidence_summary": "G0 found automated collection and commercial-use restrictions without written approval.",
        "scope": "HUMAN_VIEWING_ONLY", "reviewed_at_utc": REVIEWED_AT,
        "status": "RESTRICTED", "quota": "N/A",
    },
    {
        "source_id": "threads_api", "operation": "KEYWORD_SEARCH_POLLING",
        "evidence_url": "https://www.postman.com/meta/threads/collection/dht3nzz/threads-api",
        "evidence_summary": "Requires Meta App, OAuth, applicable permissions/App Review, and lifecycle compliance; none is granted to D01.",
        "scope": "CONDITIONAL_COMMUNITY_CLUE_ONLY", "reviewed_at_utc": REVIEWED_AT,
        "status": "UNVERIFIED", "quota": "META_CONTROLLED",
    },
    {
        "source_id": "biggo", "operation": "AUTOMATED_DATA_IMPORT",
        "evidence_url": "https://biggo.com.tw/official/disclaimers?tag=privacy",
        "evidence_summary": "No downstream API, feed, export, persistence, or reuse permission was established.",
        "scope": "UNVERIFIED_COMPARISON_CANDIDATE", "reviewed_at_utc": REVIEWED_AT,
        "status": "UNVERIFIED", "quota": "UNKNOWN",
    },
    {
        "source_id": "feebee_public_bi", "operation": "CONTINUOUS_MACHINE_EXPORT",
        "evidence_url": "https://feebee.com.tw/terms/ | https://bi.feebee.com.tw/terms",
        "evidence_summary": "Public systematic extraction is restricted; a special contract for Coupang Taiwan and derived use is absent.",
        "scope": "CONTRACT_REQUIRED", "reviewed_at_utc": REVIEWED_AT,
        "status": "UNVERIFIED", "quota": "CUSTOM_UNKNOWN",
    },
    {
        "source_id": "cp_price", "operation": "AUTOMATED_DATA_IMPORT",
        "evidence_url": "https://coupang-price-hub.pages.dev/terms",
        "evidence_summary": "Unapproved automated bulk requests are restricted; API/feed/export/relicensing was not established.",
        "scope": "HUMAN_SERVICE_ONLY", "reviewed_at_utc": REVIEWED_AT,
        "status": "RESTRICTED", "quota": "UNKNOWN",
    },
    {
        "source_id": "affiliates_one_coupang", "operation": "CATALOG_FEED_IMPORT",
        "evidence_url": "https://blog.affiliates.one/zh-TW/blog/post/coupang-ku-peng-tai-wan-lian-meng-ji-hua",
        "evidence_summary": "Promotional attribution does not establish catalogue export, monitoring, persistence, or downstream reuse rights.",
        "scope": "AFFILIATE_PROMOTION_ONLY", "reviewed_at_utc": REVIEWED_AT,
        "status": "UNVERIFIED", "quota": "UNKNOWN",
    },
    {
        "source_id": "line_shopping_merchant_api", "operation": "COUPANG_BUYER_CATALOG_READ",
        "evidence_url": "https://terms2.line.me/OA_Shop_ToB_terms_of_service?lang=zh-Hant",
        "evidence_summary": "Merchant API scope does not authorize buyer-side reading of a third-party Coupang catalogue.",
        "scope": "OWN_MERCHANT_DATA_ONLY", "reviewed_at_utc": REVIEWED_AT,
        "status": "NOT_APPLICABLE", "quota": "N/A",
    },
    {
        "source_id": "synthetic_feed", "operation": "INGEST_SYNTHETIC",
        "evidence_url": "input/orchestrator_bundles/D01/extracted/CDH_D01_001_INPUT_BUNDLE/01_CODEX_TASK.md",
        "evidence_summary": "D01 authority explicitly permits bounded local synthetic fixtures with permanent synthetic marking.",
        "scope": "LOCAL_SYNTHETIC_ONLY", "reviewed_at_utc": REVIEWED_AT,
        "status": "LOCAL_ONLY", "quota": "10000_ROWS_PER_IMPORT",
    },
    {
        "source_id": "user_import", "operation": "INGEST_USER_IMPORT",
        "evidence_url": "input/orchestrator_bundles/D01/extracted/CDH_D01_001_INPUT_BUNDLE/01_CODEX_TASK.md",
        "evidence_summary": "D01 authority permits user-selected local JSON/CSV; import does not transfer upstream source permission.",
        "scope": "USER_PROVIDED_LOCAL_ONLY", "reviewed_at_utc": REVIEWED_AT,
        "status": "LOCAL_ONLY", "quota": "10000_ROWS_PER_IMPORT",
    },
]


def seed_permissions(conn) -> int:
    return insert_permission_rows(conn, BASELINE_PERMISSIONS)


def write_permission_matrix(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["source_id", "operation", "status", "scope", "reviewed_at_utc", "quota", "evidence_url", "evidence_summary"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in BASELINE_PERMISSIONS:
            safe = dict(row)
            for key, value in safe.items():
                if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"}:
                    safe[key] = "'" + value
            writer.writerow(safe)

