from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from statistics import median
from zoneinfo import ZoneInfo

from .models import BaselineSnapshot, Observation, PurchaseScenario, require_aware

TAIPEI = ZoneInfo("Asia/Taipei")


def _floor_fraction(value: int | float | Fraction) -> int:
    if isinstance(value, Fraction):
        return value.numerator // value.denominator
    return int(value // 1)


def _daily_medians(
    observations: list[Observation], as_of: datetime
) -> tuple[dict[object, int], dict[object, datetime], dict[object, int]]:
    """Return completed-day inputs without laundering recency from excluded samples.

    The caller selects its strict historical window.  Per-day latest timestamps and
    sample counts let freshness/provenance be derived only from days that actually
    contribute to that window.
    """
    require_aware(as_of, "as_of")
    valid = [observation for observation in observations if observation.valid and observation.observed_at < as_of]
    valid.sort(key=lambda observation: observation.observed_at)
    hourly_first: dict[datetime, Observation] = {}
    for observation in valid:
        utc = observation.observed_at.astimezone(timezone.utc)
        hour = utc.replace(minute=0, second=0, microsecond=0)
        hourly_first.setdefault(hour, observation)

    by_day: dict[object, list[int]] = defaultdict(list)
    latest_by_day: dict[object, datetime] = {}
    for observation in hourly_first.values():
        day = observation.observed_at.astimezone(TAIPEI).date()
        by_day[day].append(observation.unit_minor)
        latest_by_day[day] = max(latest_by_day.get(day, observation.observed_at), observation.observed_at)
    daily = {day: _floor_fraction(median(values)) for day, values in by_day.items()}
    sample_counts = {day: len(values) for day, values in by_day.items()}
    return daily, latest_by_day, sample_counts


def _bound_snapshot(
    scenario: PurchaseScenario,
    *,
    as_of: datetime,
    item_minor: int | None,
    counts: tuple[int, int, int],
    latest: datetime | None,
    reliable: bool,
    reason: str,
    series_key: str | None,
    contributing_observation_count: int = 0,
    last_eligible_history_day: str | None = None,
) -> BaselineSnapshot:
    return BaselineSnapshot(
        item_minor=item_minor,
        sample_days_m7=counts[0],
        sample_days_m30=counts[1],
        sample_days_m90=counts[2],
        last_observed_at=latest,
        reliable=reliable,
        reason=reason,
        event_time=as_of,
        series_key=series_key,
        scenario_scope=scenario.scope_key,
        offer_key=scenario.offer.key,
        context_id=scenario.context_id,
        membership_context=scenario.membership_context,
        eligibility_profile_version=scenario.eligibility_profile_version,
        coupon_plan_id=scenario.coupon_plan_id,
        quantity=scenario.quantity,
        price_basis=scenario.price_basis,
        contributing_observation_count=contributing_observation_count,
        last_eligible_history_day=last_eligible_history_day,
    )


def _matches_scenario(observation: Observation, scenario: PurchaseScenario) -> bool:
    return observation.series_payload == scenario.history_series_payload


def build_baseline(
    observations: list[Observation],
    as_of: datetime,
    scenario: PurchaseScenario | None = None,
) -> BaselineSnapshot:
    """Build history only when every sample is bound to the exact purchase scenario.

    An omitted scenario is intentionally fail-closed.  A history series cannot be
    safely reused across SKUs, membership states, coupon plans, or price bases.
    """
    require_aware(as_of, "as_of")
    if scenario is None:
        return BaselineSnapshot(
            item_minor=None,
            sample_days_m7=0,
            sample_days_m30=0,
            sample_days_m90=0,
            last_observed_at=None,
            reliable=False,
            reason="UNBOUND_HISTORY_SCENARIO",
            event_time=as_of,
        )
    if not observations:
        return _bound_snapshot(
            scenario,
            as_of=as_of,
            item_minor=None,
            counts=(0, 0, 0),
            latest=None,
            reliable=False,
            reason="INSUFFICIENT_HISTORY",
            series_key=None,
        )

    series = {observation.series_key for observation in observations}
    if len(series) != 1:
        return _bound_snapshot(
            scenario,
            as_of=as_of,
            item_minor=None,
            counts=(0, 0, 0),
            latest=None,
            reliable=False,
            reason="MIXED_HISTORY_SERIES",
            series_key=None,
        )
    series_key = next(iter(series))
    if any(not _matches_scenario(observation, scenario) for observation in observations):
        return _bound_snapshot(
            scenario,
            as_of=as_of,
            item_minor=None,
            counts=(0, 0, 0),
            latest=None,
            reliable=False,
            reason="HISTORY_SCENARIO_MISMATCH",
            series_key=series_key,
        )

    daily, latest_by_day, sample_counts = _daily_medians(observations, as_of)
    event_day = as_of.astimezone(TAIPEI).date()

    def window(days: int) -> list[tuple[object, int]]:
        start = event_day - timedelta(days=days)
        return sorted((day, value) for day, value in daily.items() if start <= day < event_day)

    w7, w30, w90 = window(7), window(30), window(90)
    counts = (len(w7), len(w30), len(w90))
    contributing_days = [day for day, _ in w30]
    latest = max((latest_by_day[day] for day in contributing_days), default=None)
    contributing_count = sum(sample_counts[day] for day in contributing_days)
    last_eligible_day = None if latest is None else latest.astimezone(TAIPEI).date().isoformat()
    if len(w30) < 7:
        return _bound_snapshot(
            scenario,
            as_of=as_of,
            item_minor=None,
            counts=counts,
            latest=latest,
            reliable=False,
            reason="INSUFFICIENT_HISTORY",
            series_key=series_key,
            contributing_observation_count=contributing_count,
            last_eligible_history_day=last_eligible_day,
        )
    if latest is None or as_of - latest > timedelta(days=7):
        return _bound_snapshot(
            scenario,
            as_of=as_of,
            item_minor=None,
            counts=counts,
            latest=latest,
            reliable=False,
            reason="STALE_HISTORY",
            series_key=series_key,
            contributing_observation_count=contributing_count,
            last_eligible_history_day=last_eligible_day,
        )

    candidates: list[int] = []
    if len(w7) >= 3:
        candidates.append(_floor_fraction(median(value for _, value in w7)))
    candidates.append(_floor_fraction(median(value for _, value in w30)))
    if len(w90) >= 21:
        candidates.append(_floor_fraction(median(value for _, value in w90)))
    return _bound_snapshot(
        scenario,
        as_of=as_of,
        item_minor=min(candidates),
        counts=counts,
        latest=latest,
        reliable=True,
        reason="BASELINE_READY",
        series_key=series_key,
        contributing_observation_count=contributing_count,
        last_eligible_history_day=last_eligible_day,
    )


def is_historical_new_low(
    current_unit_minor: int,
    observations: list[Observation],
    as_of: datetime,
    scenario: PurchaseScenario | None = None,
) -> bool:
    baseline = build_baseline(observations, as_of, scenario)
    if not baseline.reliable:
        return False
    prior = [observation.unit_minor for observation in observations if observation.valid and observation.observed_at < as_of]
    return bool(prior) and current_unit_minor < min(prior)
