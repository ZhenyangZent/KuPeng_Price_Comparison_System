"""Coupang Deal Hunter R01 additional independent, fail-safe regressions.

Run from the root of the R01 handoff:
    PYTHONPATH=source/src python -m unittest -v /absolute/path/to/this/file.py

The original R01 source is EXPECTED TO FAIL these newly discovered checks.
The repair must make the tests pass without removing original 96 product tests.
This file does not use network, Firefox, or real notifications.
"""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cdh_core.history import build_baseline
from cdh_core.models import (
    BaselineSnapshot, EventStatus, MoneyValue, Observation, OfferIdentity, PurchaseScenario,
)
from cdh_core.persistence import CurrentState, EventStore, MockSink
from cdh_core.policy import PolicyContext, decide
from cdh_core.pricing import CouponTerms, PricingInput, calculate_total

NOW = datetime(2026, 11, 1, 15, 0, tzinfo=timezone.utc)
OFFER = OfferIdentity('SYNTHETIC', 'p1', 'sku1', 'seller1', 'NEW', '1x', 'ROCKET_LOCAL')


def scenario(*, coupon: str | None = None) -> PurchaseScenario:
    return PurchaseScenario(
        OFFER, 'context-1', 1, 'WOW', coupon_plan_id=coupon,
        eligibility_profile_version='profile-v1', price_basis='CURRENT_TOTAL',
        purchase_channel='WEB', payment_method='NONE',
    )


def cost_for(target: PurchaseScenario, subtotal: int, *, shipping: int = 0,
             minute: int = 0, evidence_id: str = 'quote-id', coupon_terms=None,
             included_adjustments=frozenset()):
    when = NOW + timedelta(minutes=minute)
    return calculate_total(target, PricingInput(
        subtotal=MoneyValue.known(subtotal), shipping=MoneyValue.known(shipping),
        fees=(), tax=MoneyValue.known(0), minimum_quantity=1,
        independently_purchasable=True, coupon=coupon_terms,
        included_adjustment_ids=included_adjustments,
        evaluated_at=when, evidence_expires_at=when + timedelta(minutes=10),
        quote_evidence_id=evidence_id,
    ))


def ctx(target: PurchaseScenario, minute=0):
    now=NOW+timedelta(minutes=minute)
    return PolicyContext.synthetic_verified(now, target, expires_at=now+timedelta(minutes=8))


def state(target: PurchaseScenario, cost, minute=0, availability='epoch-1'):
    now=NOW+timedelta(minutes=minute)
    return CurrentState.verified_from(
        target, cost, now=now, expires_at=now+timedelta(minutes=8),
        availability_version=availability,
    )


def obs(target: PurchaseScenario, age_days: float, price: int):
    return Observation(
        target.offer.key, target.context_id, target.quantity, target.price_basis,
        price, NOW-timedelta(days=age_days), membership_context=target.membership_context,
        eligibility_profile_version=target.eligibility_profile_version,
        coupon_plan_id=target.coupon_plan_id, purchase_channel=target.purchase_channel,
        payment_method=target.payment_method,
    )


class IndependentR01Regressions(unittest.TestCase):
    def test_R02_01_stale_baseline_not_refreshed_by_today_cheap_observation(self):
        target=scenario()
        old=[obs(target, day, 100_000) for day in range(9,16)]
        self.assertFalse(build_baseline(old,NOW,target).reliable)
        revived=build_baseline(old+[obs(target,0.001,500)], NOW, target)
        self.assertFalse(revived.reliable, 'current-day sample is not part of M30 history; cannot refresh an old baseline')

    def test_R02_02_older_state_must_not_overwrite_newer_price_and_deliver_old_alert(self):
        target=scenario()
        oldcost=cost_for(target,500)
        olddecision=decide(target,oldcost,None,ctx(target))
        oldstate=state(target,oldcost)
        with tempfile.TemporaryDirectory() as tmp:
            db=EventStore(Path(tmp)/'db.sqlite3')
            db.set_current_state(oldstate,now=NOW)
            event,_=db.enqueue(target,olddecision,request_id='old-alert',dedupe_key='old',expected_fingerprint=oldcost.quote_fingerprint,expires_at=NOW+timedelta(minutes=5),now=NOW)
            newcost=cost_for(target,50_000,minute=1,evidence_id='new-price-evidence')
            db.set_current_state(state(target,newcost,minute=1,availability='epoch-2'),now=NOW+timedelta(minutes=1))
            try:
                db.set_current_state(oldstate,now=NOW+timedelta(minutes=2))
            except (ValueError, RuntimeError):
                pass  # Rejecting stale writes is an acceptable fix.
            sink=MockSink()
            result=db.deliver(event,sink,now=NOW+timedelta(minutes=2))
            self.assertNotEqual(result,EventStatus.DELIVERED,'stale quote was already superseded by a higher price')
            self.assertEqual(sink.deliveries,[])

    def test_R02_03_new_availability_epoch_invalidates_old_queued_alert(self):
        target=scenario()
        cost=cost_for(target,500)
        decision=decide(target,cost,None,ctx(target))
        original=state(target,cost,availability='stock-before')
        with tempfile.TemporaryDirectory() as tmp:
            db=EventStore(Path(tmp)/'db.sqlite3')
            db.set_current_state(original,now=NOW)
            event,_=db.enqueue(target,decision,request_id='before-restock',dedupe_key='x',expected_fingerprint=cost.quote_fingerprint,expires_at=NOW+timedelta(minutes=5),now=NOW)
            newer=replace(original, observed_at=NOW+timedelta(seconds=30), received_at=NOW+timedelta(seconds=30), availability_version='stock-after')
            db.set_current_state(newer,now=NOW+timedelta(seconds=30))
            sink=MockSink()
            result=db.deliver(event,sink,now=NOW+timedelta(minutes=1))
            self.assertNotEqual(result,EventStatus.DELIVERED,'old stock epoch cannot be valid in new availability epoch')
            self.assertEqual(sink.deliveries,[])

    def test_R02_04_repeated_same_price_new_observation_id_is_not_new_alert(self):
        target=scenario()
        with tempfile.TemporaryDirectory() as tmp:
            db=EventStore(Path(tmp)/'db.sqlite3')
            ids=[];created=[]
            for minute, evidence in ((0,'observed-load-1'),(1,'observed-load-2')):
                cost=cost_for(target,500,minute=minute,evidence_id=evidence)
                decision=decide(target,cost,None,ctx(target,minute))
                db.set_current_state(state(target,cost,minute),now=NOW+timedelta(minutes=minute))
                eid,created_flag=db.enqueue(target,decision,request_id=f'request-{minute}',dedupe_key='same-price',expected_fingerprint=cost.quote_fingerprint,expires_at=NOW+timedelta(minutes=minute+5),now=NOW+timedelta(minutes=minute))
                ids.append(eid);created.append(created_flag)
            self.assertEqual(created,[True,False],'new evidence ID and timestamp alone should not generate a new offer notification')
            self.assertEqual(ids[0],ids[1])
            self.assertEqual(db.counts(),{'events':1,'outbox':1})

    def test_R02_05_zero_sample_self_asserted_baseline_is_not_authoritative(self):
        target=scenario()
        cost=cost_for(target,5000,shipping=6000)
        fake=BaselineSnapshot(
            100_000,0,0,0,NOW-timedelta(days=1),True,'BASELINE_READY',event_time=NOW,
            series_key=target.history_series_key,scenario_scope=target.scope_key,
            offer_key=target.offer.key,context_id=target.context_id,
            membership_context=target.membership_context,
            eligibility_profile_version=target.eligibility_profile_version,
            coupon_plan_id=target.coupon_plan_id,quantity=target.quantity,
            price_basis=target.price_basis,
        )
        decision=decide(target,cost,fake,ctx(target))
        self.assertFalse(decision.notify,'a snapshot with zero observed days must not authorize paid-shipping O2')

    def test_R02_06_included_expired_unclaimed_coupon_is_not_authorized_zero(self):
        target=scenario(coupon='coupon-1')
        expired=CouponTerms(
            coupon_id='coupon-1',discount=MoneyValue.known(500),minimum_subtotal_minor=0,
            eligibility=False, restrictions_satisfied=False, claimed=False,
            remaining_uses=0, expires_at=NOW-timedelta(minutes=1),
            rule_version='validated-coupon-rule-v1',
        )
        cost=cost_for(target,0,coupon_terms=expired,included_adjustments=frozenset({'coupon-1'}))
        decision=decide(target,cost,None,ctx(target))
        self.assertFalse(decision.notify, 'already-included coupon must still prove eligibility/expiry/claim')

    def test_R02_07_included_unselected_coupon_without_proof_is_not_zero(self):
        target=scenario(coupon=None)
        cost=cost_for(target,0,included_adjustments=frozenset({'unverified-coupon'}))
        decision=decide(target,cost,None,ctx(target))
        self.assertFalse(decision.notify, 'pre-discounted zero must have a bound selected validated adjustment plan')

    def test_R02_08_disabled_source_cannot_be_reenabled_by_older_price_state(self):
        target=scenario()
        cost=cost_for(target,500)
        decision=decide(target,cost,None,ctx(target))
        original=state(target,cost)
        with tempfile.TemporaryDirectory() as tmp:
            db=EventStore(Path(tmp)/'db.sqlite3')
            db.set_current_state(original,now=NOW)
            event,_=db.enqueue(target,decision,request_id='disabled-test',dedupe_key='x',expected_fingerprint=cost.quote_fingerprint,expires_at=NOW+timedelta(minutes=5),now=NOW)
            disabled=replace(original,source_enabled=False,observed_at=NOW+timedelta(minutes=1),received_at=NOW+timedelta(minutes=1))
            db.set_current_state(disabled,now=NOW+timedelta(minutes=1))
            try:
                db.set_current_state(original,now=NOW+timedelta(minutes=2))
            except (ValueError,RuntimeError):
                pass
            sink=MockSink()
            result=db.deliver(event,sink,now=NOW+timedelta(minutes=2))
            self.assertNotEqual(result,EventStatus.DELIVERED)
            self.assertEqual(sink.deliveries,[])

    def test_R02_09_policy_rule_epoch_change_invalidates_queued_old_alert(self):
        target=scenario()
        cost=cost_for(target,500)
        decision=decide(target,cost,None,ctx(target))
        original=state(target,cost)
        with tempfile.TemporaryDirectory() as tmp:
            db=EventStore(Path(tmp)/'db.sqlite3')
            db.set_current_state(original,now=NOW)
            event,_=db.enqueue(target,decision,request_id='policy-epoch-test',dedupe_key='x',expected_fingerprint=cost.quote_fingerprint,expires_at=NOW+timedelta(minutes=5),now=NOW)
            changed=replace(original,rule_version='current-state-rules-v3',observed_at=NOW+timedelta(minutes=1),received_at=NOW+timedelta(minutes=1))
            db.set_current_state(changed,now=NOW+timedelta(minutes=1))
            sink=MockSink()
            result=db.deliver(event,sink,now=NOW+timedelta(minutes=2))
            self.assertNotEqual(result,EventStatus.DELIVERED)
            self.assertEqual(sink.deliveries,[])

if __name__=='__main__':
    unittest.main(verbosity=2)
