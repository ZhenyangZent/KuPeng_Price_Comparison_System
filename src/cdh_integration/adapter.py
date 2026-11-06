from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from cdh_core.history import build_baseline
from cdh_core.models import (
    POLICY_VERSION,
    EligibilityState,
    Observation,
    OfferIdentity,
    PurchaseScenario,
    StockState,
)
from cdh_core.policy import PolicyContext
from cdh_core.pricing import CouponTerms, FeeComponent, PricingInput
from cdh_core.models import EvidenceBasis, MoneyValue


OBSERVATION_FIELDS = frozenset(
    {"source_class", "sku", "product_url", "price_minor", "currency", "observed_at", "title"}
)
FIXTURE_FIELDS = frozenset(
    {
        "fixture_class",
        "fixture_id",
        "source_payload_sha256",
        "sku",
        "product_url",
        "seller_id",
        "condition",
        "package_signature",
        "delivery_type",
        "price_minor",
        "price_scenario_id",
        "observation_observed_at",
        "context_id",
        "membership_context",
        "eligibility_profile_version",
        "policy_version",
        "source_permission_version",
        "fixture_observed_at",
        "fixture_expires_at",
        "quantity",
        "minimum_quantity",
        "stock_state",
        "eligibility_state",
        "independently_purchasable",
        "requires_additional_items",
        "shipping_minor",
        "fees",
        "tax_minor",
        "subscription_or_deposit",
        "user_enabled",
        "notifications_enabled",
        "source_allowed",
        "coupon_plan_id",
        "coupon",
        "target_total_minor",
        "purchase_channel",
        "payment_method",
        "availability_version",
        "history",
        "price_basis",
        "quoted_quantity",
        "total_quote_evidence_id",
    }
)
PRICE_EVIDENCE_FIELDS = frozenset({"price_basis", "quoted_quantity", "total_quote_evidence_id"})
REQUIRED_FIXTURE_FIELDS = FIXTURE_FIELDS - PRICE_EVIDENCE_FIELDS
FEE_FIELDS = frozenset({"component_id", "amount_minor"})
HISTORY_FIELDS = frozenset({"observed_at", "unit_minor"})
COUPON_FIELDS = frozenset(
    {
        "coupon_id",
        "discount_minor",
        "minimum_subtotal_minor",
        "expires_at",
        "claimed",
        "remaining_uses",
        "eligibility",
        "restrictions_satisfied",
        "cap_behavior_confirmed",
        "requires_app",
        "allowed_payment_method",
        "threshold_policy",
        "rule_version",
        "terms_evidence_id",
    }
)
SKU_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class IntegrationValidationError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _closed_dict(value: object, fields: frozenset[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntegrationValidationError(code, "value must be an object")
    if set(value) != fields:
        missing = sorted(fields - set(value))
        extra = sorted(set(value) - fields)
        raise IntegrationValidationError(code, f"closed schema mismatch; missing={missing}; extra={extra}")
    return value


def _fixture_dict(value: object) -> dict[str, Any]:
    """Accept legacy q=1 fixtures while keeping the extended fixture schema closed."""
    if not isinstance(value, dict):
        raise IntegrationValidationError("INVALID_QUALIFICATION_FIXTURE_FIELDS", "value must be an object")
    missing = sorted(REQUIRED_FIXTURE_FIELDS - set(value))
    extra = sorted(set(value) - FIXTURE_FIELDS)
    if missing or extra:
        raise IntegrationValidationError(
            "INVALID_QUALIFICATION_FIXTURE_FIELDS",
            f"closed schema mismatch; missing={missing}; extra={extra}",
        )
    return value


def _strict_int(value: object, field: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IntegrationValidationError(f"INVALID_{field.upper()}", f"{field} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        raise IntegrationValidationError(f"INVALID_{field.upper()}", f"{field} is outside the allowed range")
    return value


def _strict_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise IntegrationValidationError(f"INVALID_{field.upper()}", f"{field} must be boolean")
    return value


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise IntegrationValidationError(f"INVALID_{field.upper()}", f"{field} has an invalid identifier")
    return value


def _utc(value: object, field: str) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise IntegrationValidationError(f"INVALID_{field.upper()}", f"{field} must be bounded UTC text")
    if not value.endswith("Z") and not value.endswith("+00:00"):
        raise IntegrationValidationError(f"INVALID_{field.upper()}", f"{field} must explicitly use UTC")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntegrationValidationError(f"INVALID_{field.upper()}", f"{field} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise IntegrationValidationError(f"INVALID_{field.upper()}", f"{field} must explicitly use UTC")
    return parsed


def _synthetic_url(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise IntegrationValidationError("URL_NOT_SYNTHETIC", "product_url must be bounded text")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "synthetic.invalid"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or not parsed.path.startswith("/products/")
        or parsed.query
        or parsed.fragment
        or "\\" in parsed.path
    ):
        raise IntegrationValidationError("URL_NOT_SYNTHETIC", "only synthetic.invalid product URLs are accepted")
    return value


@dataclass(frozen=True, slots=True)
class SyntheticObservation:
    source_class: str
    sku: str
    product_url: str
    price_minor: int
    currency: str
    observed_at: datetime
    title: str
    source_payload_sha256: str
    raw_payload: dict[str, object]

    @classmethod
    def parse(cls, payload: object) -> "SyntheticObservation":
        value = _closed_dict(payload, OBSERVATION_FIELDS, "INVALID_OBSERVATION_FIELDS")
        if value["source_class"] != "SYNTHETIC_TEST_PAGE":
            raise IntegrationValidationError("SOURCE_CLASS_NOT_SYNTHETIC", "source_class is not authorized")
        sku = value["sku"]
        if not isinstance(sku, str) or SKU_PATTERN.fullmatch(sku) is None:
            raise IntegrationValidationError("INVALID_SKU", "sku format rejected")
        title = value["title"]
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise IntegrationValidationError("INVALID_TITLE", "title must be 1-200 characters")
        if value["currency"] != "TWD":
            raise IntegrationValidationError("INVALID_CURRENCY", "only TWD is accepted")
        price = _strict_int(value["price_minor"], "price_minor", maximum=10_000_000)
        observed = _utc(value["observed_at"], "observed_at")
        raw = dict(value)
        return cls(
            source_class="SYNTHETIC_TEST_PAGE",
            sku=sku,
            product_url=_synthetic_url(value["product_url"]),
            price_minor=price,
            currency="TWD",
            observed_at=observed,
            title=title,
            source_payload_sha256=sha256_json(raw),
            raw_payload=raw,
        )


@dataclass(frozen=True, slots=True)
class QualificationFixture:
    raw: dict[str, object]
    fixture_sha256: str

    @classmethod
    def parse(cls, payload: object) -> "QualificationFixture":
        value = _fixture_dict(payload)
        if value["fixture_class"] != "SYNTHETIC_QUALIFICATION_FIXTURE":
            raise IntegrationValidationError("FIXTURE_CLASS_NOT_SYNTHETIC", "fixture class is not authorized")
        for field in (
            "fixture_id",
            "seller_id",
            "condition",
            "package_signature",
            "delivery_type",
            "context_id",
            "membership_context",
            "eligibility_profile_version",
            "source_permission_version",
            "availability_version",
        ):
            _identifier(value[field], field)
        if value["eligibility_profile_version"] == "UNVERIFIED":
            raise IntegrationValidationError("FIXTURE_ELIGIBILITY_UNVERIFIED", "explicit profile version is required")
        if value["policy_version"] != POLICY_VERSION:
            raise IntegrationValidationError("FIXTURE_POLICY_VERSION_MISMATCH", "fixture must bind the frozen C01 policy")
        source_hash = value["source_payload_sha256"]
        if not isinstance(source_hash, str) or re.fullmatch(r"[0-9a-f]{64}", source_hash) is None:
            raise IntegrationValidationError("INVALID_SOURCE_PAYLOAD_SHA256", "source payload SHA-256 is invalid")
        sku = value["sku"]
        if not isinstance(sku, str) or SKU_PATTERN.fullmatch(sku) is None:
            raise IntegrationValidationError("INVALID_FIXTURE_SKU", "fixture sku format rejected")
        _synthetic_url(value["product_url"])
        for field in ("price_minor", "quantity", "minimum_quantity", "shipping_minor", "tax_minor"):
            minimum = 1 if field in {"quantity", "minimum_quantity"} else 0
            _strict_int(value[field], field, minimum=minimum)
        quantity = int(value["quantity"])
        price_basis = value.get("price_basis")
        quoted_quantity = value.get("quoted_quantity")
        total_quote_evidence_id = value.get("total_quote_evidence_id")
        price_evidence_present = any(
            item is not None for item in (price_basis, quoted_quantity, total_quote_evidence_id)
        )
        if quantity > 1 and not price_evidence_present:
            raise IntegrationValidationError(
                "MULTI_QUANTITY_PRICE_BASIS_UNVERIFIED",
                "q>1 requires an explicit total-for-quantity quote and provenance",
            )
        if price_evidence_present:
            if price_basis != "TOTAL_FOR_QUANTITY":
                raise IntegrationValidationError(
                    "PRICE_BASIS_UNVERIFIED",
                    "the synthetic contract only accepts explicit total-for-quantity quotes",
                )
            _strict_int(quoted_quantity, "quoted_quantity", minimum=1)
            if quoted_quantity != quantity:
                raise IntegrationValidationError(
                    "QUOTED_QUANTITY_MISMATCH",
                    "quoted quantity must equal the selected purchase quantity",
                )
            _identifier(total_quote_evidence_id, "total_quote_evidence_id")
        if value["target_total_minor"] is not None:
            _strict_int(value["target_total_minor"], "target_total_minor")
        for field in (
            "independently_purchasable",
            "requires_additional_items",
            "subscription_or_deposit",
            "user_enabled",
            "notifications_enabled",
            "source_allowed",
        ):
            _strict_bool(value[field], field)
        if value["stock_state"] not in {item.value for item in StockState}:
            raise IntegrationValidationError("INVALID_STOCK_STATE", "stock state is not recognized")
        if value["eligibility_state"] not in {item.value for item in EligibilityState}:
            raise IntegrationValidationError("INVALID_ELIGIBILITY_STATE", "eligibility state is not recognized")
        observed = _utc(value["fixture_observed_at"], "fixture_observed_at")
        expires = _utc(value["fixture_expires_at"], "fixture_expires_at")
        _utc(value["observation_observed_at"], "observation_observed_at")
        if expires <= observed:
            raise IntegrationValidationError("INVALID_FIXTURE_WINDOW", "fixture expiry must follow observation")
        fees = value["fees"]
        if not isinstance(fees, list):
            raise IntegrationValidationError("INVALID_FEES", "fees must be a list")
        seen_fees: set[str] = set()
        for item in fees:
            fee = _closed_dict(item, FEE_FIELDS, "INVALID_FEE_FIELDS")
            component_id = _identifier(fee["component_id"], "fee_component_id")
            if component_id in seen_fees:
                raise IntegrationValidationError("DUPLICATE_FEE_ID", "fee component ids must be unique")
            seen_fees.add(component_id)
            _strict_int(fee["amount_minor"], "fee_amount_minor")
        history = value["history"]
        if not isinstance(history, list):
            raise IntegrationValidationError("INVALID_HISTORY", "history must be a list")
        for item in history:
            sample = _closed_dict(item, HISTORY_FIELDS, "INVALID_HISTORY_FIELDS")
            _utc(sample["observed_at"], "history_observed_at")
            _strict_int(sample["unit_minor"], "history_unit_minor")
        coupon = value["coupon"]
        coupon_plan_id = value["coupon_plan_id"]
        if coupon is None:
            if coupon_plan_id is not None:
                raise IntegrationValidationError("COUPON_TERMS_MISSING", "coupon plan requires explicit terms")
        else:
            terms = _closed_dict(coupon, COUPON_FIELDS, "INVALID_COUPON_FIELDS")
            if coupon_plan_id != terms["coupon_id"]:
                raise IntegrationValidationError("COUPON_PLAN_MISMATCH", "coupon plan and terms differ")
            _identifier(terms["coupon_id"], "coupon_id")
            _strict_int(terms["discount_minor"], "discount_minor")
            if terms["minimum_subtotal_minor"] is not None:
                _strict_int(terms["minimum_subtotal_minor"], "minimum_subtotal_minor")
            expiry = _utc(terms["expires_at"], "coupon_expires_at")
            if expiry <= observed:
                raise IntegrationValidationError("COUPON_EXPIRED_OR_INVALID", "coupon expiry is not valid")
            for field in (
                "claimed",
                "eligibility",
                "restrictions_satisfied",
                "cap_behavior_confirmed",
                "requires_app",
            ):
                _strict_bool(terms[field], f"coupon_{field}")
            _strict_int(terms["remaining_uses"], "remaining_uses", minimum=1)
            if terms["threshold_policy"] not in {"FIXED", "NONE"}:
                raise IntegrationValidationError("COUPON_THRESHOLD_UNVERIFIED", "coupon threshold must be explicit")
            if terms["threshold_policy"] == "FIXED" and terms["minimum_subtotal_minor"] is None:
                raise IntegrationValidationError("COUPON_THRESHOLD_UNVERIFIED", "fixed threshold requires a value")
            if terms["threshold_policy"] == "NONE" and terms["minimum_subtotal_minor"] not in (None, 0):
                raise IntegrationValidationError("COUPON_THRESHOLD_CONFLICT", "no-threshold coupon has a threshold")
            _identifier(terms["rule_version"], "coupon_rule_version")
            _identifier(terms["terms_evidence_id"], "coupon_terms_evidence_id")
            if terms["allowed_payment_method"] is not None:
                _identifier(terms["allowed_payment_method"], "allowed_payment_method")
        return cls(raw=dict(value), fixture_sha256=sha256_json(value))

    @staticmethod
    def expected_price_scenario_id(
        observation: SyntheticObservation,
        *,
        seller_id: str,
        package_signature: str,
        quantity: int,
    ) -> str:
        payload = {
            "source_payload_sha256": observation.source_payload_sha256,
            "sku": observation.sku,
            "seller_id": seller_id,
            "package_signature": package_signature,
            "price_minor": observation.price_minor,
            "quantity": quantity,
            "observed_at": observation.observed_at.isoformat(),
        }
        return "i01-price:" + sha256_json(payload)

    def bind(self, observation: SyntheticObservation, now: datetime) -> "QualifiedBundle":
        if now.tzinfo is None or now.utcoffset() is None:
            raise IntegrationValidationError("INVALID_CLOCK", "injected clock must be timezone-aware")
        value = self.raw
        checks = (
            (value["source_payload_sha256"] == observation.source_payload_sha256, "FIXTURE_SOURCE_HASH_MISMATCH"),
            (value["sku"] == observation.sku, "FIXTURE_SKU_MISMATCH"),
            (value["product_url"] == observation.product_url, "FIXTURE_URL_MISMATCH"),
            (value["price_minor"] == observation.price_minor, "FIXTURE_PRICE_MISMATCH"),
            (
                _utc(value["observation_observed_at"], "observation_observed_at") == observation.observed_at,
                "FIXTURE_OBSERVATION_TIME_MISMATCH",
            ),
        )
        for passed, code in checks:
            if not passed:
                raise IntegrationValidationError(code, "qualification fixture does not bind the exact observation")
        fixture_observed = _utc(value["fixture_observed_at"], "fixture_observed_at")
        fixture_expires = _utc(value["fixture_expires_at"], "fixture_expires_at")
        if not (fixture_observed <= observation.observed_at <= now < fixture_expires):
            raise IntegrationValidationError("FIXTURE_TIME_WINDOW_MISMATCH", "fixture is not valid for this observation and clock")
        expected_scenario = self.expected_price_scenario_id(
            observation,
            seller_id=str(value["seller_id"]),
            package_signature=str(value["package_signature"]),
            quantity=int(value["quantity"]),
        )
        if value["price_scenario_id"] != expected_scenario:
            raise IntegrationValidationError("FIXTURE_PRICE_SCENARIO_MISMATCH", "price scenario identity is not bound")
        if observation.price_minor % int(value["quantity"]) != 0:
            raise IntegrationValidationError("NON_INTEGRAL_UNIT_PRICE", "total price cannot be represented as an exact unit price")

        product_id = PurePosixPath(urlsplit(observation.product_url).path).name
        offer = OfferIdentity(
            platform="SYNTHETIC_INVALID",
            product_id=product_id,
            sku_id=observation.sku,
            seller_id=str(value["seller_id"]),
            condition=str(value["condition"]),
            package_signature=str(value["package_signature"]),
            delivery_type=str(value["delivery_type"]),
        )
        scenario = PurchaseScenario(
            offer=offer,
            context_id=str(value["context_id"]),
            quantity=int(value["quantity"]),
            membership_context=str(value["membership_context"]),
            coupon_plan_id=value["coupon_plan_id"],
            target_total_minor=value["target_total_minor"],
            eligibility_profile_version=str(value["eligibility_profile_version"]),
            price_basis="CURRENT_TOTAL",
            purchase_channel=str(value["purchase_channel"]),
            payment_method=str(value["payment_method"]),
        )
        source_id = f"I01-SYNTHETIC:{observation.source_payload_sha256}"
        core_observation = Observation(
            offer_key=offer.key,
            context_id=scenario.context_id,
            quantity=scenario.quantity,
            price_type=scenario.price_basis,
            unit_minor=observation.price_minor // scenario.quantity,
            observed_at=observation.observed_at,
            received_at=observation.observed_at,
            source_published_at=observation.observed_at,
            source_id=source_id,
            parser_version="cdh-i01-adapter-v1",
            membership_context=scenario.membership_context,
            eligibility_profile_version=scenario.eligibility_profile_version,
            coupon_plan_id=scenario.coupon_plan_id,
            purchase_channel=scenario.purchase_channel,
            payment_method=scenario.payment_method,
        )
        provenance = value.get("total_quote_evidence_id") or "LEGACY-Q1-UNAMBIGUOUS"
        quote_evidence_id = (
            f"I01-QUOTE:{observation.source_payload_sha256}:{self.fixture_sha256}:{provenance}"
        )
        fees = tuple(
            FeeComponent(str(item["component_id"]), MoneyValue.known(int(item["amount_minor"]), evidence_id=quote_evidence_id))
            for item in value["fees"]
        )
        coupon = self._coupon_terms(scenario, quote_evidence_id)
        pricing = PricingInput(
            subtotal=MoneyValue.known(observation.price_minor, evidence_id=quote_evidence_id),
            shipping=MoneyValue.known(int(value["shipping_minor"]), evidence_id=quote_evidence_id),
            fees=fees,
            tax=MoneyValue.known(int(value["tax_minor"]), evidence_id=quote_evidence_id),
            minimum_quantity=int(value["minimum_quantity"]),
            independently_purchasable=bool(value["independently_purchasable"]),
            requires_additional_items=bool(value["requires_additional_items"]),
            coupon=coupon,
            evaluated_at=now,
            quote_evidence_id=quote_evidence_id,
            rule_version="i01-synthetic-qualification-v1",
            evidence_expires_at=fixture_expires,
        )
        policy = PolicyContext(
            user_enabled=bool(value["user_enabled"]),
            notifications_enabled=bool(value["notifications_enabled"]),
            source_allowed=bool(value["source_allowed"]),
            evidence_valid=True,
            eligibility=EligibilityState(str(value["eligibility_state"])),
            stock=StockState(str(value["stock_state"])),
            subscription_or_deposit=bool(value["subscription_or_deposit"]),
            historical_new_low=False,
            evaluated_at=now,
            evidence_observed_at=fixture_observed,
            evidence_expires_at=fixture_expires,
            evidence_id=f"I01-POLICY:{self.fixture_sha256}",
            rule_version=POLICY_VERSION,
            source_permission_version=str(value["source_permission_version"]),
            scenario_scope=scenario.scope_key,
            membership_context=scenario.membership_context,
            eligibility_profile_version=scenario.eligibility_profile_version,
        )
        history = [
            Observation(
                offer_key=offer.key,
                context_id=scenario.context_id,
                quantity=scenario.quantity,
                price_type=scenario.price_basis,
                unit_minor=int(sample["unit_minor"]),
                observed_at=_utc(sample["observed_at"], "history_observed_at"),
                received_at=_utc(sample["observed_at"], "history_observed_at"),
                source_published_at=_utc(sample["observed_at"], "history_observed_at"),
                source_id=f"I01-SYNTHETIC-HISTORY:{self.fixture_sha256}",
                parser_version="cdh-i01-adapter-v1",
                membership_context=scenario.membership_context,
                eligibility_profile_version=scenario.eligibility_profile_version,
                coupon_plan_id=scenario.coupon_plan_id,
                purchase_channel=scenario.purchase_channel,
                payment_method=scenario.payment_method,
            )
            for sample in value["history"]
        ]
        baseline = build_baseline(history, now, scenario) if history else None
        return QualifiedBundle(
            observation=observation,
            fixture=self,
            scenario=scenario,
            core_observation=core_observation,
            pricing=pricing,
            policy=policy,
            baseline=baseline,
        )

    def _coupon_terms(self, scenario: PurchaseScenario, quote_evidence_id: str) -> CouponTerms | None:
        terms = self.raw["coupon"]
        if terms is None:
            return None
        expiry = _utc(terms["expires_at"], "coupon_expires_at")
        threshold_policy = str(terms["threshold_policy"])
        return CouponTerms(
            coupon_id=str(terms["coupon_id"]),
            discount=MoneyValue.known(int(terms["discount_minor"]), evidence_id=quote_evidence_id),
            minimum_subtotal_minor=terms["minimum_subtotal_minor"],
            eligibility=bool(terms["eligibility"]),
            restrictions_satisfied=bool(terms["restrictions_satisfied"]),
            cap_behavior_confirmed=bool(terms["cap_behavior_confirmed"]),
            expires_at=expiry,
            applicable_offer_keys=frozenset({scenario.offer.key}),
            applicable_seller_ids=frozenset({scenario.offer.seller_id}),
            claimed=bool(terms["claimed"]),
            remaining_uses=int(terms["remaining_uses"]),
            requires_app=bool(terms["requires_app"]),
            allowed_payment_method=terms["allowed_payment_method"],
            threshold_evidence_id=(
                None if threshold_policy == "NONE" else f"I01-COUPON-THRESHOLD:{self.fixture_sha256}"
            ),
            rule_version=str(terms["rule_version"]),
            expiry_policy="FIXED",
            offer_scope_policy="LISTED",
            seller_scope_policy="LISTED",
            threshold_policy=threshold_policy,
            terms_evidence_id=str(terms["terms_evidence_id"]),
            terms_context_id=scenario.context_id,
            terms_membership_context=scenario.membership_context,
            terms_eligibility_profile_version=scenario.eligibility_profile_version,
            terms_evidence_basis=EvidenceBasis.OBSERVED,
            terms_source_record_sha256=self.fixture_sha256,
        )


@dataclass(frozen=True, slots=True)
class QualifiedBundle:
    observation: SyntheticObservation
    fixture: QualificationFixture
    scenario: PurchaseScenario
    core_observation: Observation
    pricing: PricingInput
    policy: PolicyContext
    baseline: object | None

