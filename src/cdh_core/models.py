from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from fractions import Fraction
from typing import Any
from zoneinfo import ZoneInfo

CORE_VERSION = "0.5.0"
PRODUCT_MODE = "OFFLINE_ONLY"
POLICY_VERSION = "cdh-v3.0-c01-r04.5"
IDENTITY_VERSION = "identity-v2"
HISTORY_CALCULATION_VERSION = "history-v3.0-c01-r04.5"
HISTORY_TIMEZONE = ZoneInfo("Asia/Taipei")
PRICE_BASIS_RULE_VERSION = "complete-purchase-price-v1"
ALLOWED_COMPLETE_PRICE_BASES = frozenset({"CURRENT_TOTAL"})


class ValueState(StrEnum):
    KNOWN = "KNOWN"
    KNOWN_ZERO = "KNOWN_ZERO"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CONFLICT = "CONFLICT"
    PARSE_ERROR = "PARSE_ERROR"


class EvidenceBasis(StrEnum):
    OBSERVED = "OBSERVED"
    RULE_DERIVED = "RULE_DERIVED"
    USER_DECLARED = "USER_DECLARED"
    ADAPTER_CONTRACT_DEFAULT = "ADAPTER_CONTRACT_DEFAULT"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


class StockState(StrEnum):
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    UNKNOWN = "UNKNOWN"


class EligibilityState(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


class EventStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    WAITING_EVIDENCE = "WAITING_EVIDENCE"
    ELIGIBLE = "ELIGIBLE"
    FILTERED = "FILTERED"
    QUEUED = "QUEUED"
    IN_FLIGHT = "IN_FLIGHT"
    DELIVERED = "DELIVERED"
    DELIVERY_UNKNOWN = "DELIVERY_UNKNOWN"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


def require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def strict_int(value: Any, field_name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer, not bool/float")
    if value < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}")
    return value


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        return {key: _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_normalize(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def canonical_digest(kind: str, value: Any) -> str:
    payload = canonical_json({"kind": kind, "version": IDENTITY_VERSION, "value": value}).encode("utf-8")
    return f"{kind}:{IDENTITY_VERSION}:{hashlib.sha256(payload).hexdigest()}"


@dataclass(frozen=True, slots=True)
class MoneyValue:
    state: ValueState
    minor: int | None = None
    currency: str = "TWD"
    evidence_id: str | None = None

    def __post_init__(self) -> None:
        if self.currency != "TWD":
            raise ValueError("C01 supports TWD only")
        if self.state in (ValueState.KNOWN, ValueState.KNOWN_ZERO):
            strict_int(self.minor, "minor")
            if self.state == ValueState.KNOWN_ZERO and self.minor != 0:
                raise ValueError("KNOWN_ZERO requires minor=0")
            if self.state == ValueState.KNOWN and self.minor == 0:
                raise ValueError("zero must use KNOWN_ZERO")
        elif self.minor is not None:
            raise ValueError(f"{self.state} cannot carry a numeric value")

    @classmethod
    def known(cls, minor: int, *, evidence_id: str | None = None) -> "MoneyValue":
        strict_int(minor, "minor")
        state = ValueState.KNOWN_ZERO if minor == 0 else ValueState.KNOWN
        return cls(state=state, minor=minor, evidence_id=evidence_id)

    @classmethod
    def unavailable(cls, state: ValueState, *, evidence_id: str | None = None) -> "MoneyValue":
        if state in (ValueState.KNOWN, ValueState.KNOWN_ZERO):
            raise ValueError("use MoneyValue.known for numeric values")
        return cls(state=state, evidence_id=evidence_id)

    @property
    def is_numeric(self) -> bool:
        return self.state in (ValueState.KNOWN, ValueState.KNOWN_ZERO)

    @property
    def is_usable(self) -> bool:
        # A MoneyValue alone cannot authorize a zero for NOT_APPLICABLE.
        # Pricing must validate typed, component-bound provenance separately.
        return self.is_numeric

    def resolved_minor(self, *, allow_not_applicable: bool = False) -> int:
        if self.state == ValueState.NOT_APPLICABLE:
            raise ValueError("NOT_APPLICABLE requires typed component evidence in the pricing engine")
        if not self.is_numeric:
            raise ValueError(f"money is not numeric: {self.state}")
        assert self.minor is not None
        return self.minor


@dataclass(frozen=True, slots=True)
class OfferIdentity:
    platform: str
    product_id: str
    sku_id: str
    seller_id: str
    condition: str
    package_signature: str
    delivery_type: str

    def __post_init__(self) -> None:
        for name in self.__slots__:
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")

    @property
    def identity_payload(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.__slots__}

    @property
    def key(self) -> str:
        return canonical_digest("offer", self.identity_payload)


@dataclass(frozen=True, slots=True)
class PurchaseScenario:
    offer: OfferIdentity
    context_id: str
    quantity: int
    membership_context: str
    coupon_plan_id: str | None = None
    target_total_minor: int | None = None
    eligibility_profile_version: str = "UNVERIFIED"
    price_basis: str = "CURRENT_TOTAL"
    purchase_channel: str = "UNKNOWN"
    payment_method: str = "UNKNOWN"

    def __post_init__(self) -> None:
        strict_int(self.quantity, "quantity", minimum=1)
        for name in (
            "context_id",
            "membership_context",
            "eligibility_profile_version",
            "price_basis",
            "purchase_channel",
            "payment_method",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"{name} is required")
        if self.target_total_minor is not None:
            strict_int(self.target_total_minor, "target_total_minor")

    @property
    def scope_payload(self) -> dict[str, Any]:
        return {
            "offer_key": self.offer.key,
            "context_id": self.context_id,
            "quantity": self.quantity,
            "membership_context": self.membership_context,
            "eligibility_profile_version": self.eligibility_profile_version,
            "coupon_plan_id": self.coupon_plan_id,
            "price_basis": self.price_basis,
            "purchase_channel": self.purchase_channel,
            "payment_method": self.payment_method,
        }

    @property
    def scope_key(self) -> str:
        return canonical_digest("scenario", self.scope_payload)

    @property
    def user_policy_scope_key(self) -> str:
        """Stable user-policy scope across offer and membership/profile changes."""
        return canonical_digest(
            "user-policy-scope",
            {"platform": self.offer.platform, "context_id": self.context_id},
        )

    @property
    def history_series_payload(self) -> dict[str, Any]:
        return {
            "offer_key": self.offer.key,
            "context_id": self.context_id,
            "quantity": self.quantity,
            "price_basis": self.price_basis,
            "membership_context": self.membership_context,
            "eligibility_profile_version": self.eligibility_profile_version,
            "coupon_plan_id": self.coupon_plan_id,
            "purchase_channel": self.purchase_channel,
            "payment_method": self.payment_method,
        }

    @property
    def history_series_key(self) -> str:
        return canonical_digest("history-series", self.history_series_payload)


@dataclass(frozen=True, slots=True)
class Evidence:
    evidence_id: str
    field_name: str
    value: Any
    basis: EvidenceBasis
    offer_key: str
    context_id: str
    scenario_scope: str
    observed_at: datetime
    expires_at: datetime
    rule_version: str
    source_id: str = "SYNTHETIC"
    membership_context: str | None = None
    eligibility_profile_version: str | None = None
    coupon_plan_id: str | None = None
    price_basis: str | None = None

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.observed_at:
            raise ValueError("evidence must expire after observation")
        if not self.source_id or not self.rule_version:
            raise ValueError("source_id and rule_version are required")

    def compatibility(self, scenario: PurchaseScenario, now: datetime) -> tuple[bool, str]:
        require_aware(now, "now")
        if self.offer_key != scenario.offer.key:
            return False, "EVIDENCE_OFFER_MISMATCH"
        if self.context_id != scenario.context_id:
            return False, "EVIDENCE_CONTEXT_MISMATCH"
        if self.scenario_scope != scenario.scope_key:
            return False, "EVIDENCE_SCENARIO_MISMATCH"
        optional_bindings = (
            (self.membership_context, scenario.membership_context, "EVIDENCE_MEMBERSHIP_MISMATCH"),
            (self.eligibility_profile_version, scenario.eligibility_profile_version, "EVIDENCE_ELIGIBILITY_PROFILE_MISMATCH"),
            (self.coupon_plan_id, scenario.coupon_plan_id, "EVIDENCE_COUPON_PLAN_MISMATCH"),
            (self.price_basis, scenario.price_basis, "EVIDENCE_PRICE_BASIS_MISMATCH"),
        )
        for actual, expected, reason in optional_bindings:
            if actual is not None and actual != expected:
                return False, reason
        if self.basis in (EvidenceBasis.UNKNOWN, EvidenceBasis.CONFLICT):
            return False, f"EVIDENCE_{self.basis}"
        if now < self.observed_at:
            return False, "EVIDENCE_NOT_YET_VALID"
        if now >= self.expires_at:
            return False, "EVIDENCE_EXPIRED"
        return True, "EVIDENCE_COMPATIBLE"


@dataclass(frozen=True, slots=True)
class Observation:
    offer_key: str
    context_id: str
    quantity: int
    price_type: str
    unit_minor: int
    observed_at: datetime
    source_published_at: datetime | None = None
    received_at: datetime | None = None
    valid: bool = True
    parser_version: str = "c01-r04.5"
    source_id: str = "SYNTHETIC"
    membership_context: str = "UNKNOWN"
    eligibility_profile_version: str = "UNVERIFIED"
    coupon_plan_id: str | None = None
    purchase_channel: str = "UNKNOWN"
    payment_method: str = "UNKNOWN"

    def __post_init__(self) -> None:
        strict_int(self.quantity, "quantity", minimum=1)
        strict_int(self.unit_minor, "unit_minor")
        require_aware(self.observed_at, "observed_at")
        if self.source_published_at is not None:
            require_aware(self.source_published_at, "source_published_at")
        if self.received_at is not None:
            require_aware(self.received_at, "received_at")
        if not self.source_id or not self.parser_version:
            raise ValueError("source_id and parser_version are required")

    @property
    def series_payload(self) -> dict[str, Any]:
        return {
            "offer_key": self.offer_key,
            "context_id": self.context_id,
            "quantity": self.quantity,
            "price_basis": self.price_type,
            "membership_context": self.membership_context,
            "eligibility_profile_version": self.eligibility_profile_version,
            "coupon_plan_id": self.coupon_plan_id,
            "purchase_channel": self.purchase_channel,
            "payment_method": self.payment_method,
        }

    @property
    def series_key(self) -> str:
        return canonical_digest("history-series", self.series_payload)

    @property
    def payload_fingerprint(self) -> str:
        payload = {
            **self.series_payload,
            "unit_minor": self.unit_minor,
            "observed_at": self.observed_at.isoformat(),
            "source_published_at": None if self.source_published_at is None else self.source_published_at.isoformat(),
            "received_at": None if self.received_at is None else self.received_at.isoformat(),
            "valid": self.valid,
            "parser_version": self.parser_version,
            "source_id": self.source_id,
        }
        return canonical_digest("observation-payload", payload)


@dataclass(frozen=True, slots=True)
class BaselineSnapshot:
    item_minor: int | None
    sample_days_m7: int
    sample_days_m30: int
    sample_days_m90: int
    last_observed_at: datetime | None
    reliable: bool
    reason: str
    calculation_version: str = HISTORY_CALCULATION_VERSION
    event_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    series_key: str | None = None
    scenario_scope: str | None = None
    offer_key: str | None = None
    context_id: str | None = None
    membership_context: str | None = None
    eligibility_profile_version: str | None = None
    coupon_plan_id: str | None = None
    quantity: int | None = None
    price_basis: str | None = None
    contributing_observation_count: int = 0
    last_eligible_history_day: str | None = None

    def __post_init__(self) -> None:
        for name in ("sample_days_m7", "sample_days_m30", "sample_days_m90"):
            strict_int(getattr(self, name), name)
        strict_int(self.contributing_observation_count, "contributing_observation_count")
        if self.item_minor is not None:
            strict_int(self.item_minor, "item_minor")
        if self.quantity is not None:
            strict_int(self.quantity, "quantity", minimum=1)
        if self.last_observed_at is not None:
            require_aware(self.last_observed_at, "last_observed_at")
        require_aware(self.event_time, "event_time")

    def compatibility(self, scenario: PurchaseScenario, now: datetime) -> tuple[bool, str]:
        require_aware(now, "now")
        if not self.reliable or self.item_minor is None:
            return False, self.reason or "BASELINE_UNRELIABLE"
        if self.calculation_version != HISTORY_CALCULATION_VERSION:
            return False, "BASELINE_CALCULATION_VERSION_UNAPPROVED"
        if self.reason != "BASELINE_READY":
            return False, "BASELINE_PROVENANCE_UNAPPROVED"
        if not (
            self.sample_days_m30 >= 7
            and self.sample_days_m7 <= self.sample_days_m30 <= self.sample_days_m90
            and self.contributing_observation_count >= self.sample_days_m30
        ):
            return False, "BASELINE_WINDOW_COVERAGE_INVALID"
        expected = {
            "scenario_scope": scenario.scope_key,
            "offer_key": scenario.offer.key,
            "context_id": scenario.context_id,
            "membership_context": scenario.membership_context,
            "eligibility_profile_version": scenario.eligibility_profile_version,
            "coupon_plan_id": scenario.coupon_plan_id,
            "quantity": scenario.quantity,
            "price_basis": scenario.price_basis,
        }
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                return False, f"BASELINE_{field_name.upper()}_MISMATCH"
        if self.series_key != scenario.history_series_key:
            return False, "BASELINE_SERIES_MISMATCH"
        if self.event_time > now:
            return False, "BASELINE_FROM_FUTURE"
        if self.last_observed_at is None or self.last_observed_at > self.event_time:
            return False, "BASELINE_INVALID_PRE_EVENT_TIME"
        expected_day = self.last_observed_at.astimezone(HISTORY_TIMEZONE).date().isoformat()
        event_day = self.event_time.astimezone(HISTORY_TIMEZONE).date().isoformat()
        if self.last_eligible_history_day != expected_day or expected_day >= event_day:
            return False, "BASELINE_ELIGIBLE_DAY_INVALID"
        if now - self.last_observed_at > timedelta(days=7):
            return False, "BASELINE_STALE"
        return True, "BASELINE_COMPATIBLE"


@dataclass(frozen=True, slots=True)
class CostResult:
    complete: bool
    total_minor: int | None
    unit_minor: Fraction | None
    subtotal_minor: int | None
    discount_minor: int | None
    shipping_minor: int | None
    fees_minor: int | None
    tax_minor: int | None
    reason_codes: tuple[str, ...]
    applied_adjustment_ids: frozenset[str] = frozenset()
    scenario_scope: str | None = None
    quote_fingerprint: str | None = None
    price_basis: str | None = None
    calculated_at: datetime | None = None
    evidence_expires_at: datetime | None = None
    quote_evidence_id: str | None = None
    rule_version: str | None = None
    semantic_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    notify: bool
    primary_reason: str
    labels: tuple[str, ...]
    total_minor: int | None
    baseline_total_minor: int | None
    savings_minor: int | None
    drop_basis_points: int | None
    policy_version: str = POLICY_VERSION
    scenario_scope: str | None = None
    cost_fingerprint: str | None = None
    decision_fingerprint: str | None = None
    evaluated_at: datetime | None = None
    valid_until: datetime | None = None
    policy_evidence_json: str | None = None
    policy_evidence_fingerprint: str | None = None
    approval_seal: str | None = None

    @property
    def computed_fingerprint(self) -> str:
        return canonical_digest(
            "decision",
            {
                "policy_version": self.policy_version,
                "scenario_scope": self.scenario_scope,
                "cost_fingerprint": self.cost_fingerprint,
                "notify": self.notify,
                "reason": self.primary_reason,
                "labels": self.labels,
                "total_minor": self.total_minor,
                "baseline_total_minor": self.baseline_total_minor,
                "savings_minor": self.savings_minor,
                "drop_basis_points": self.drop_basis_points,
                "evaluated_at": None if self.evaluated_at is None else self.evaluated_at.isoformat(),
                "valid_until": None if self.valid_until is None else self.valid_until.isoformat(),
                "policy_evidence_fingerprint": self.policy_evidence_fingerprint,
            },
        )

