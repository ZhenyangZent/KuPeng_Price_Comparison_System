from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


N01_CONTRACT_VERSION = "CDH-N01-OFFLINE-ALERT-1"
N01_POLICY_VERSION = "n01-free-shipping-gate-v1"
SYNTHETIC_SOURCE_STATUS = "SOURCE_BLOCKED"


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    RETRY = "RETRY"
    DELIVERED = "DELIVERED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    DEAD = "DEAD"


class StateConflict(ValueError):
    pass


class StaleState(ValueError):
    pass


class RequestConflict(ValueError):
    pass


def require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def parse_time(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(kind: str, value: Any) -> str:
    raw = canonical_json({"kind": kind, "version": N01_CONTRACT_VERSION, "value": value})
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _non_negative(value: int | None, field_name: str) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise ValueError(f"{field_name} must be a non-negative integer or null")


@dataclass(frozen=True, slots=True)
class NotificationCandidate:
    request_id: str
    scenario_scope: str
    user_policy_scope: str
    offer_key: str
    sku_id: str
    quantity: int
    minimum_quantity: int
    membership_context: str
    eligibility_profile_version: str
    policy_epoch: int
    source_revision: int
    source_kind: str
    source_status: str
    observed_at: datetime
    expires_at: datetime
    decision_fingerprint: str
    policy_evidence_fingerprint: str
    decision_reason: str
    decision_labels: tuple[str, ...]
    decision_notify: bool
    total_minor: int | None
    subtotal_minor: int | None
    shipping_minor: int | None
    fees_minor: int | None
    tax_minor: int | None
    coupon_discount_minor: int | None
    coupon_expires_at: datetime | None
    stock: str
    notifications_enabled: bool
    user_enabled: bool
    target_total_minor: int | None
    baseline_total_minor: int | None
    baseline_reliable: bool
    cost_semantic_fingerprint: str
    zero_total_provenance: str

    def __post_init__(self) -> None:
        for field_name in (
            "request_id",
            "scenario_scope",
            "user_policy_scope",
            "offer_key",
            "sku_id",
            "membership_context",
            "eligibility_profile_version",
            "source_kind",
            "source_status",
            "decision_fingerprint",
            "policy_evidence_fingerprint",
            "decision_reason",
            "cost_semantic_fingerprint",
            "zero_total_provenance",
        ):
            if not isinstance(getattr(self, field_name), str) or not getattr(self, field_name):
                raise ValueError(f"{field_name} is required")
        for field_name in ("quantity", "minimum_quantity"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        for field_name in ("policy_epoch", "source_revision"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        for field_name in (
            "total_minor",
            "subtotal_minor",
            "shipping_minor",
            "fees_minor",
            "tax_minor",
            "coupon_discount_minor",
            "target_total_minor",
            "baseline_total_minor",
        ):
            _non_negative(getattr(self, field_name), field_name)
        require_aware(self.observed_at, "observed_at")
        require_aware(self.expires_at, "expires_at")
        if self.coupon_expires_at is not None:
            require_aware(self.coupon_expires_at, "coupon_expires_at")
        if self.expires_at <= self.observed_at:
            raise ValueError("expires_at must be after observed_at")

    @property
    def semantic_key(self) -> str:
        return digest(
            "notification-semantic",
            {
                "scenario_scope": self.scenario_scope,
                "offer_key": self.offer_key,
                "sku_id": self.sku_id,
                "quantity": self.quantity,
                "membership_context": self.membership_context,
                "policy_epoch": self.policy_epoch,
                "source_revision": self.source_revision,
                "decision_reason": self.decision_reason,
                "total_minor": self.total_minor,
                "cost_semantic_fingerprint": self.cost_semantic_fingerprint,
            },
        )

    @property
    def payload_fingerprint(self) -> str:
        return digest("notification-candidate", self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["observed_at"] = iso(self.observed_at)
        value["expires_at"] = iso(self.expires_at)
        value["coupon_expires_at"] = iso(self.coupon_expires_at)
        value["decision_labels"] = list(self.decision_labels)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "NotificationCandidate":
        data = dict(value)
        data["observed_at"] = parse_time(data["observed_at"])
        data["expires_at"] = parse_time(data["expires_at"])
        data["coupon_expires_at"] = parse_time(data.get("coupon_expires_at"))
        data["decision_labels"] = tuple(data.get("decision_labels", ()))
        return cls(**data)


@dataclass(frozen=True, slots=True)
class LatestState:
    scenario_scope: str
    offer_key: str
    sku_id: str
    quantity: int
    membership_context: str
    eligibility_profile_version: str
    policy_epoch: int
    source_revision: int
    source_kind: str
    source_status: str
    source_available: bool
    notifications_enabled: bool
    user_enabled: bool
    stock: str
    total_minor: int | None
    subtotal_minor: int | None
    shipping_minor: int | None
    fees_minor: int | None
    tax_minor: int | None
    coupon_discount_minor: int | None
    coupon_expires_at: datetime | None
    observed_at: datetime
    expires_at: datetime
    revision_id: str

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        require_aware(self.expires_at, "expires_at")
        if self.coupon_expires_at is not None:
            require_aware(self.coupon_expires_at, "coupon_expires_at")
        if self.expires_at <= self.observed_at:
            raise ValueError("expires_at must be after observed_at")
        for field_name in ("quantity", "policy_epoch", "source_revision"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < (1 if field_name == "quantity" else 0):
                raise ValueError(f"invalid {field_name}")
        for field_name in (
            "total_minor",
            "subtotal_minor",
            "shipping_minor",
            "fees_minor",
            "tax_minor",
            "coupon_discount_minor",
        ):
            _non_negative(getattr(self, field_name), field_name)

    @classmethod
    def from_candidate(cls, candidate: NotificationCandidate, **changes: Any) -> "LatestState":
        data: dict[str, Any] = {
            "scenario_scope": candidate.scenario_scope,
            "offer_key": candidate.offer_key,
            "sku_id": candidate.sku_id,
            "quantity": candidate.quantity,
            "membership_context": candidate.membership_context,
            "eligibility_profile_version": candidate.eligibility_profile_version,
            "policy_epoch": candidate.policy_epoch,
            "source_revision": candidate.source_revision,
            "source_kind": candidate.source_kind,
            "source_status": candidate.source_status,
            "source_available": True,
            "notifications_enabled": candidate.notifications_enabled,
            "user_enabled": candidate.user_enabled,
            "stock": candidate.stock,
            "total_minor": candidate.total_minor,
            "subtotal_minor": candidate.subtotal_minor,
            "shipping_minor": candidate.shipping_minor,
            "fees_minor": candidate.fees_minor,
            "tax_minor": candidate.tax_minor,
            "coupon_discount_minor": candidate.coupon_discount_minor,
            "coupon_expires_at": candidate.coupon_expires_at,
            "observed_at": candidate.observed_at,
            "expires_at": candidate.expires_at,
            "revision_id": f"synthetic-{candidate.source_revision}-{candidate.policy_epoch}",
        }
        data.update(changes)
        return cls(**data)

    @property
    def fingerprint(self) -> str:
        return digest("latest-state", self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["observed_at"] = iso(self.observed_at)
        value["expires_at"] = iso(self.expires_at)
        value["coupon_expires_at"] = iso(self.coupon_expires_at)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "LatestState":
        data = dict(value)
        data["observed_at"] = parse_time(data["observed_at"])
        data["expires_at"] = parse_time(data["expires_at"])
        data["coupon_expires_at"] = parse_time(data.get("coupon_expires_at"))
        return cls(**data)


@dataclass(frozen=True, slots=True)
class GateResult:
    allowed: bool
    reasons: tuple[str, ...]
    display_category: str
    free_shipping: bool
    policy_version: str = N01_POLICY_VERSION


def free_shipping_gate(candidate: NotificationCandidate, state: LatestState, now: datetime) -> GateResult:
    """Shared fail-closed gate for immediate alerts and daily digest."""
    require_aware(now, "now")
    reasons: list[str] = []
    bindings = (
        (state.scenario_scope == candidate.scenario_scope, "SCENARIO_SCOPE_CHANGED"),
        (state.offer_key == candidate.offer_key, "OFFER_CHANGED"),
        (state.sku_id == candidate.sku_id, "SKU_CHANGED"),
        (state.quantity == candidate.quantity, "QUANTITY_CHANGED"),
        (state.membership_context == candidate.membership_context, "MEMBERSHIP_CHANGED"),
        (
            state.eligibility_profile_version == candidate.eligibility_profile_version,
            "ELIGIBILITY_PROFILE_CHANGED",
        ),
        (state.policy_epoch == candidate.policy_epoch, "POLICY_EPOCH_CHANGED"),
        (state.source_revision == candidate.source_revision, "SOURCE_REVISION_CHANGED"),
    )
    reasons.extend(reason for passed, reason in bindings if not passed)
    if candidate.source_kind != "SYNTHETIC" or state.source_kind != "SYNTHETIC":
        reasons.append("REAL_SOURCE_NOT_AUTHORIZED")
    if candidate.source_status != SYNTHETIC_SOURCE_STATUS or state.source_status != SYNTHETIC_SOURCE_STATUS:
        reasons.append("SOURCE_STATUS_MUST_REMAIN_BLOCKED")
    if not state.source_available:
        reasons.append("SOURCE_OFFLINE")
    if not candidate.decision_notify:
        reasons.append("UPSTREAM_DECISION_SILENT")
    if not state.notifications_enabled or not candidate.notifications_enabled:
        reasons.append("NOTIFICATIONS_DISABLED")
    if not state.user_enabled or not candidate.user_enabled:
        reasons.append("USER_DISABLED")
    if state.stock != "IN_STOCK" or candidate.stock != "IN_STOCK":
        reasons.append("NOT_IN_STOCK")
    if candidate.quantity < candidate.minimum_quantity:
        reasons.append("MINIMUM_QUANTITY_NOT_MET")
    if now < candidate.observed_at or now < state.observed_at:
        reasons.append("DATA_FROM_FUTURE")
    if now >= candidate.expires_at:
        reasons.append("MESSAGE_EXPIRED")
    if now >= state.expires_at:
        reasons.append("LATEST_STATE_EXPIRED")

    component_names = (
        "total_minor",
        "subtotal_minor",
        "shipping_minor",
        "fees_minor",
        "tax_minor",
        "coupon_discount_minor",
    )
    for name in component_names:
        if getattr(candidate, name) is None or getattr(state, name) is None:
            reasons.append(f"{name.upper()}_UNKNOWN")
        elif getattr(candidate, name) != getattr(state, name):
            reasons.append(f"{name.upper()}_CHANGED")

    if not any(reason.endswith("_UNKNOWN") for reason in reasons):
        assert candidate.subtotal_minor is not None
        assert candidate.coupon_discount_minor is not None
        assert candidate.shipping_minor is not None
        assert candidate.fees_minor is not None
        assert candidate.tax_minor is not None
        assert candidate.total_minor is not None
        calculated = (
            candidate.subtotal_minor
            - candidate.coupon_discount_minor
            + candidate.shipping_minor
            + candidate.fees_minor
            + candidate.tax_minor
        )
        if calculated != candidate.total_minor:
            reasons.append("TOTAL_FORMULA_MISMATCH")

    if (candidate.coupon_discount_minor or 0) > 0:
        if candidate.coupon_expires_at is None or state.coupon_expires_at is None:
            reasons.append("COUPON_EXPIRY_UNKNOWN")
        elif now >= candidate.coupon_expires_at or now >= state.coupon_expires_at:
            reasons.append("COUPON_EXPIRED")

    free_shipping = candidate.shipping_minor == 0 and state.shipping_minor == 0
    if not free_shipping:
        paid_exception = (
            candidate.decision_reason in {"O1", "O2"}
            and candidate.baseline_reliable
            and candidate.baseline_total_minor is not None
            and candidate.total_minor is not None
            and candidate.baseline_total_minor > candidate.total_minor
        )
        if not paid_exception:
            reasons.append("NO_FREE_SHIPPING_POLICY_MATCH")

    if candidate.total_minor == 0 and candidate.zero_total_provenance != "VERIFIED_PURCHASE_TOTAL":
        reasons.append("ZERO_TOTAL_PROVENANCE_INVALID")

    if candidate.decision_reason == "TARGET_REACHED":
        category = "TARGET_PRICE_REACHED"
    elif (
        candidate.baseline_reliable
        and candidate.baseline_total_minor is not None
        and candidate.total_minor is not None
        and candidate.baseline_total_minor > candidate.total_minor
    ):
        category = "VERIFIED_DISCOUNT"
    else:
        category = "LOW_ABSOLUTE_PRICE"
    return GateResult(not reasons, tuple(dict.fromkeys(reasons)), category, free_shipping)
