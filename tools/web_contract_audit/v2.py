from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import Assessment, Finding


SCHEMA = "CDH-WEB-CONTRACT-V2"
CLASSIFICATION_PAIRS = {
    ("USER_RECORDED_ONLY", "USER_RECORDED"): frozenset({"USER_ENTERED", "USER_FILE"}),
    ("SYNTHETIC_FIXTURE_ONLY", "SYNTHETIC_DEMO_ONLY"): frozenset({"SYNTHETIC"}),
}


def _finding(code: str, severity: str, owner: str, location: str, detail: str, reproduction: str) -> Finding:
    return Finding(code, severity, owner, location, detail, reproduction)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _classification(payload: dict[str, Any], location: str, findings: list[Finding]) -> frozenset[str]:
    pair = (payload.get("data_source_status"), payload.get("data_classification"))
    allowed_sources = CLASSIFICATION_PAIRS.get(pair)
    if allowed_sources is None:
        findings.append(_finding("V2_CLASSIFICATION_PAIR_INVALID", "CRITICAL", "B", location, "Source status and classification must be an approved pair.", "Mutate one classification field in a synthetic response."))
        return frozenset()
    return allowed_sources


def _summary(item: dict[str, Any], *, location: str, evaluated_at: datetime, findings: list[Finding]) -> None:
    price = item.get("last_observed_price_twd")
    flags = set(item.get("quality_flags") or [])
    if price is not None and (isinstance(price, bool) or not isinstance(price, int) or price < 0):
        findings.append(_finding("OBSERVED_PRICE_INVALID", "HIGH", "B", location, "Observed price must be null or a non-negative integer.", "Supply a negative, boolean or fractional synthetic price."))
    if price == 0 and "PRICE_IS_USER_OBSERVED_NOT_CHECKOUT_TOTAL" not in flags:
        findings.append(_finding("ZERO_PRICE_LACKS_OBSERVED_ONLY_FLAG", "HIGH", "B/Orchestrator", location, "Zero is not proof of a free checkout total.", "Remove the observed-only quality flag from a zero-price fixture."))
    shipping = item.get("shipping_status")
    if shipping not in {"FREE", "PAID", "UNKNOWN"}:
        findings.append(_finding("SHIPPING_STATUS_INVALID", "HIGH", "B", location, "Shipping status must be explicit.", "Use a missing or invented shipping status."))
    if shipping == "UNKNOWN" and (item.get("shipping_fee_twd") == 0 or item.get("complete_cost_twd") is not None):
        findings.append(_finding("UNKNOWN_SHIPPING_MUST_NOT_BECOME_ZERO_COST", "CRITICAL", "B/A", location, "Unknown shipping/fees cannot be treated as zero or complete cost.", "Attach shipping_fee_twd=0 to an UNKNOWN fixture."))
    observed_at = _parse_time(item.get("last_observed_at"))
    observed_days = item.get("observed_days")
    if price is None and (observed_at is not None or observed_days not in (0, None)):
        findings.append(_finding("NULL_PRICE_HISTORY_CONTRADICTION", "HIGH", "B", location, "Null current price must not coexist with claimed observations.", "Set null price with a timestamp or positive observed_days."))
    if observed_at is not None:
        if observed_at > evaluated_at:
            findings.append(_finding("OBSERVATION_IN_FUTURE", "HIGH", "B", location, "Future observations are forbidden.", "Use an observation timestamp after evaluated_at."))
        if (evaluated_at - observed_at).days > 7 and "STALE_LAST_OBSERVATION" not in flags:
            findings.append(_finding("STALE_OBSERVATION_UNLABELED", "MEDIUM", "B/A", location, "Stale observations require an explicit quality flag.", "Use an observation older than seven days without the stale flag."))


def assess_v2_bundle(
    search: dict[str, Any],
    detail: dict[str, Any],
    affiliate_response: dict[str, Any],
    *,
    evaluated_at: datetime,
) -> Assessment:
    findings: list[Finding] = []
    checks = 0
    for name, payload in (("search", search), ("detail", detail), ("affiliate", affiliate_response)):
        checks += 2
        if payload.get("schema_version") != SCHEMA:
            findings.append(_finding("V2_SCHEMA_INVALID", "CRITICAL", "B", name, "Every successful V2 response must use CDH-WEB-CONTRACT-V2.", "Change schema_version in a synthetic response."))
    search_sources = _classification(search, "search", findings)
    detail_sources = _classification(detail, "detail", findings)
    affiliate_sources = _classification(affiliate_response, "affiliate", findings)
    checks += 3
    pairs = {(value.get("data_source_status"), value.get("data_classification")) for value in (search, detail, affiliate_response)}
    if len(pairs) != 1:
        findings.append(_finding("V2_CLASSIFICATION_INCONSISTENT", "CRITICAL", "B/A", "bundle", "Search, detail and affiliate must preserve one classification.", "Mix one synthetic and one user-classified response."))
    items = search.get("items")
    if not isinstance(items, list):
        findings.append(_finding("SEARCH_ITEMS_INVALID", "CRITICAL", "B", "search.items", "Search items must be an array.", "Replace items with a scalar."))
        items = []
    page, limit, total = search.get("page"), search.get("limit"), search.get("total")
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in (page, limit, total)) or page < 1 or not 1 <= limit <= 100 or total < len(items) or len(items) > limit:
        findings.append(_finding("PAGINATION_INVALID", "HIGH", "B", "search", "Pagination counters and bounds are inconsistent.", "Return more items than limit or invalid page/total."))
    checks += 2
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            findings.append(_finding("SEARCH_ITEM_INVALID", "HIGH", "B", f"search.items[{index}]", "Item must be an object.", "Insert a scalar item."))
            continue
        _summary(item, location=f"search.items[{index}]", evaluated_at=evaluated_at, findings=findings)
    product = detail.get("product")
    if not isinstance(product, dict):
        findings.append(_finding("DETAIL_PRODUCT_INVALID", "CRITICAL", "B", "detail.product", "Detail product must be an object.", "Remove detail.product."))
        product = {}
    else:
        _summary(product, location="detail.product", evaluated_at=evaluated_at, findings=findings)
    offers = detail.get("offers")
    identities: set[tuple[object, ...]] = set()
    if not isinstance(offers, list):
        findings.append(_finding("OFFERS_INVALID", "HIGH", "B", "detail.offers", "Offers must be an array.", "Replace offers with a scalar."))
    else:
        for index, offer in enumerate(offers):
            if not isinstance(offer, dict):
                findings.append(_finding("OFFER_INVALID", "HIGH", "B", f"detail.offers[{index}]", "Offer must be an object.", "Insert a scalar offer."))
                continue
            identity = tuple(offer.get(name) for name in ("product_id", "sku_id", "seller_id", "minimum_purchase_quantity", "source_price_basis"))
            if identity in identities:
                findings.append(_finding("OFFER_IDENTITY_MERGED_OR_DUPLICATED", "CRITICAL", "B", f"detail.offers[{index}]", "Product/variant/seller/quantity/basis identities must remain separate.", "Duplicate an identity tuple in a synthetic detail response."))
            identities.add(identity)
            if offer.get("item_condition") != "UNKNOWN" or offer.get("item_condition_source") != "NOT_RECORDED":
                findings.append(_finding("ITEM_CONDITION_UNPROVEN", "HIGH", "B", f"detail.offers[{index}]", "Condition without source evidence must remain UNKNOWN/NOT_RECORDED.", "Change the synthetic offer condition to NEW."))
    history = detail.get("history")
    history_sources: set[str] = set()
    observed_days: set[str] = set()
    if not isinstance(history, list):
        findings.append(_finding("HISTORY_INVALID", "HIGH", "B", "detail.history", "History must be an array.", "Replace history with a scalar."))
    else:
        for index, row in enumerate(history):
            if not isinstance(row, dict):
                findings.append(_finding("HISTORY_ROW_INVALID", "HIGH", "B", f"detail.history[{index}]", "History row must be an object.", "Insert a scalar row."))
                continue
            source = row.get("source_type")
            history_sources.add(str(source))
            stamp = _parse_time(row.get("observed_at"))
            if source not in detail_sources:
                findings.append(_finding("MIXED_OR_UNKNOWN_HISTORY_SOURCE", "CRITICAL", "B", f"detail.history[{index}]", "History source conflicts with response classification.", "Mix SYNTHETIC and USER_FILE rows."))
            if stamp is None or stamp > evaluated_at:
                findings.append(_finding("HISTORY_TIME_INVALID", "HIGH", "B", f"detail.history[{index}]", "History timestamps must be valid and not future.", "Use a malformed or future timestamp."))
            else:
                observed_days.add(stamp.date().isoformat())
    if len(history_sources & {"SYNTHETIC"}) and len(history_sources & {"USER_ENTERED", "USER_FILE"}):
        findings.append(_finding("SYNTHETIC_USER_HISTORY_MIXED", "CRITICAL", "B", "detail.history", "Synthetic fixtures must never mix into user history.", "Combine one synthetic and one user row."))
    if isinstance(product.get("observed_days"), int) and product.get("observed_days") != len(observed_days):
        findings.append(_finding("OBSERVED_DAYS_INTERPOLATED_OR_INCONSISTENT", "HIGH", "B", "detail.product.observed_days", "Observed day count must equal actual distinct history days.", "Inflate observed_days beyond the supplied history dates."))
    checks += 8
    affiliate = affiliate_response.get("affiliate")
    if not isinstance(affiliate, dict):
        findings.append(_finding("AFFILIATE_NOT_NESTED", "CRITICAL", "B/F", "affiliate", "V2 affiliate DTO must be nested.", "Flatten the affiliate fields."))
    else:
        state = affiliate.get("state")
        if state == "UNCONFIGURED" and (affiliate.get("click_url") is not None or affiliate.get("verified_product_match") is not False):
            findings.append(_finding("UNCONFIGURED_AFFILIATE_CLICKABLE", "CRITICAL", "B/F", "affiliate", "UNCONFIGURED must have null URL and false match.", "Put an ordinary Coupang URL in an UNCONFIGURED response."))
        if isinstance(affiliate.get("click_url"), str) and "coupang" in affiliate["click_url"].casefold() and state != "VERIFIED":
            findings.append(_finding("ORDINARY_COUPANG_URL_NOT_AFFILIATE", "CRITICAL", "A/F/Orchestrator", "affiliate.click_url", "A product URL is not proof of an approved affiliate URL.", "Insert a normal Coupang product URL while state is UNCONFIGURED.",))
    checks += 3
    return Assessment.from_iterable(findings, checks=checks)
