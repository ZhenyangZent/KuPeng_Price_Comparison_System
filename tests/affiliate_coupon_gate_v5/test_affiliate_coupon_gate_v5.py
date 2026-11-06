from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "services" / "affiliate_coupon_gate_v5"
F04_SERVICE_CANDIDATES = (
    ROOT / "services" / "affiliate_gateway_v4",
    ROOT / "evidence" / "controlled_inputs" / "F04_GATEWAY" / "services" / "affiliate_gateway_v4",
)
sys.path.insert(0, str(SERVICE))
for candidate in F04_SERVICE_CANDIDATES:
    if candidate.is_dir():
        sys.path.insert(0, str(candidate))
        break

from affiliate_coupon_gate_v5 import (  # noqa: E402
    AffiliateCouponGateV5,
    AffiliateTrustInput,
    CeilingError,
    CouponContractError,
    GateRequest,
    MockSink,
    load_c06_ceiling,
    parse_coupon_snapshot,
)
from affiliate_coupon_gate_v5.models import SeriesIdentity  # noqa: E402
from affiliate_gateway_v4 import (  # noqa: E402
    AffiliateTrustGatewayV4,
    AuthoritySnapshot as F04Authority,
    EnvelopeKey,
    ExactIdentity as F04Identity,
    LinkRequest as F04Request,
    TrustClaims as F04Claims,
    TrustEnvelopeCodec,
)


NOW = datetime(2026, 11, 5, 6, 0, tzinfo=timezone.utc)


def controlled_file(packaged_name: str, workspace_parts: tuple[str, ...]) -> Path:
    candidates = [ROOT / "evidence" / "controlled_inputs" / packaged_name, ROOT.joinpath(*workspace_parts)]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise AssertionError(f"controlled input missing: {packaged_name}")


def c06_path() -> Path:
    return controlled_file(
        "C06_BASELINE_DECISION.json",
        (
            "review", "F05", "controlled_inputs", "C06", "CDH_C06_001_REVIEW", "research",
            "affiliate_readiness_c06", "BASELINE_DECISION.json",
        ),
    )


def series(**changes: str) -> SeriesIdentity:
    values = {
        "platform": "COUPANG_TW",
        "product_id": "SYN-P-1",
        "sku_id": "SYN-SKU-1",
        "seller_id": "SYN-SELLER-1",
        "condition": "NEW",
        "package_signature": "1x100ml",
    }
    values.update(changes)
    return SeriesIdentity(**values)


def payload(**changes) -> dict:
    value = {
        "schema_version": "CDH-COUPON-PRICE-V4",
        "series_identity": {
            "platform": "COUPANG_TW",
            "product_id": "SYN-P-1",
            "sku_id": "SYN-SKU-1",
            "seller_id": "SYN-SELLER-1",
            "condition": "NEW",
            "package_signature": "1x100ml",
        },
        "data_classification": "SYNTHETIC_FIXTURE",
        "source_id": "SYN-SOURCE-1",
        "observed_at": "2026-11-05T00:00:00Z",
        "base_price_twd": 99,
        "coupon": {
            "coupon_id": "SYN-COUPON-1",
            "status": "CONFIRMED_APPLICABLE",
            "discount_twd": 50,
            "already_included_in_base": False,
            "eligibility_profile": "SYN-ELIGIBLE-PROFILE",
            "valid_from": "2026-11-01T00:00:00Z",
            "valid_until": "2026-11-30T23:59:59Z",
            "scope_evidence": "SYN-TEST-EVIDENCE",
        },
        "confirmed_coupon_price_twd": 49,
        "possible_coupon_price_twd": None,
        "display_price_twd": 49,
        "display_basis": "CONFIRMED_COUPON",
        "shipping_status": "UNKNOWN",
        "required_total_twd": None,
        "history": {"before_coupon": [], "confirmed_after_coupon": []},
    }
    for key, item in changes.items():
        if key.startswith("coupon__"):
            value["coupon"][key.removeprefix("coupon__")] = item
        elif key.startswith("identity__"):
            value["series_identity"][key.removeprefix("identity__")] = item
        else:
            value[key] = item
    return value


def affiliate(**changes) -> AffiliateTrustInput:
    values = {
        "state": "CONTRACT_FIXTURE_VERIFIED_NONCLICKABLE",
        "cta_enabled": False,
        "click_url": None,
        "metadata_verified": True,
        "envelope_id": "a" * 64,
        "reason_codes": ("CONTRACT_FIXTURE_NEVER_ENABLES_EXTERNAL_CTA",),
    }
    values.update(changes)
    return AffiliateTrustInput(**values)


def request(**changes) -> GateRequest:
    values = {"identity": series(), "eligibility_profile": "SYN-ELIGIBLE-PROFILE", "user_initiated": True}
    values.update(changes)
    return GateRequest(**values)


def evaluate(value: dict | None = None, *, gate=None, gate_request=None, trust=None):
    snapshot = parse_coupon_snapshot(value or payload())
    return (gate or AffiliateCouponGateV5()).evaluate(
        snapshot=snapshot,
        request=gate_request or request(),
        affiliate=trust or affiliate(),
        ceiling=load_c06_ceiling(c06_path()),
        now=NOW,
    )


def f04_identity(**changes: str) -> F04Identity:
    values = {
        "platform": "COUPANG_TW",
        "canonical_product_id": "SYN-P-1",
        "provider_product_id": "SYN-PROVIDER-P-1",
        "sku_id": "SYN-SKU-1",
        "seller_id": "SYN-SELLER-1",
        "original_url": "https://product.coupang.invalid/vp/products/SYN-PROVIDER-P-1",
    }
    values.update(changes)
    return F04Identity(**values)


def f04_authority(**changes) -> F04Authority:
    values = {
        "state": "CONTRACT_FIXTURE_ONLY",
        "provider_id": "coupang_tw_partners",
        "market": "TW",
        "account_state": "TEST_ONLY",
        "credential_state": "TEST_ONLY",
        "capabilities": {},
        "input_hosts": frozenset({"product.coupang.invalid"}),
        "input_paths": ("/vp/products",),
        "output_hosts": frozenset({"affiliate.coupang.invalid"}),
        "output_paths": ("/click",),
        "disclosure_text": "此為合成契約測試，不是正式分潤連結。",
        "authority_expires_at": NOW + timedelta(days=1),
        "max_ttl_seconds": 3600,
        "max_revocation_age_seconds": 600,
        "revoked": False,
    }
    values.update(changes)
    return F04Authority(**values)


def f04_claims(item: F04Identity | None = None, **changes) -> F04Claims:
    chosen = item or f04_identity()
    values = {
        "issuer": "affiliate_gateway_v4",
        "audience": "cdh_trusted_backend",
        "fixture_class": "CONTRACT_FIXTURE_TEST_ONLY",
        "provider_id": "coupang_tw_partners",
        "market": "TW",
        "canonical_product_id": chosen.canonical_product_id,
        "provider_product_id": chosen.provider_product_id,
        "sku_id": chosen.sku_id,
        "seller_id": chosen.seller_id,
        "original_url_sha256": chosen.original_url_sha256,
        "verified_destination": "https://affiliate.coupang.invalid/click/opaque?token=synthetic",
        "issued_at": NOW - timedelta(minutes=1),
        "expires_at": NOW + timedelta(minutes=30),
        "official_evidence_ids": (),
        "revocation_event_id": "synthetic-revocation-event-1",
        "revocation_status": "ACTIVE",
        "revocation_checked_at": NOW - timedelta(seconds=30),
        "disclosure_text": "此為合成契約測試，不是正式分潤連結。",
        "nonce": "synthetic-f05-nonce",
    }
    values.update(changes)
    return F04Claims(**values)


def f04_codec() -> TrustEnvelopeCodec:
    return TrustEnvelopeCodec(
        {"synthetic-f05-key": EnvelopeKey(bytes(range(32)), frozenset({"CONTRACT_FIXTURE_TEST_ONLY"}))}
    )


def f04_decision(*, claims=None, item=None, user_initiated=True, gateway=None, envelope_mutator=None):
    chosen = item or f04_identity()
    chosen_claims = claims or f04_claims(chosen)
    envelope = f04_codec().sign(chosen_claims, key_id="synthetic-f05-key")
    if envelope_mutator:
        envelope_mutator(envelope)
    resolver = gateway or AffiliateTrustGatewayV4(f04_codec())
    decision = resolver.resolve(
        envelope=envelope,
        request=F04Request(chosen, user_initiated),
        authority=f04_authority(),
        now=NOW,
    )
    return AffiliateTrustInput(
        state=decision.state,
        cta_enabled=decision.cta_enabled,
        click_url=decision.click_url,
        metadata_verified=decision.metadata_verified,
        envelope_id=decision.envelope_id,
        reason_codes=decision.reason_codes,
    )


class ParserTests(unittest.TestCase):
    def test_frozen_v4_example_parses(self):
        snapshot = parse_coupon_snapshot(payload())
        self.assertEqual(snapshot.base_price_twd, 99)
        self.assertEqual(snapshot.confirmed_coupon_price_twd, 49)
        self.assertEqual(snapshot.series_identity, series())

    def test_exact_top_identity_coupon_and_history_fields_are_required(self):
        mutations = []
        for section in ("top", "identity", "coupon", "history"):
            value = payload()
            target = value if section == "top" else value[{"identity": "series_identity", "coupon": "coupon", "history": "history"}[section]]
            target["extra"] = "x"
            mutations.append(value)
        for value in mutations:
            with self.subTest(keys=list(value)):
                with self.assertRaises(CouponContractError):
                    parse_coupon_snapshot(value)

    def test_secret_or_url_smuggling_is_denied_even_inside_history(self):
        for key in ("click_url", "token", "cookie", "authorization"):
            with self.subTest(key=key):
                value = payload()
                value["history"]["before_coupon"] = [{key: "synthetic"}]
                with self.assertRaises(CouponContractError) as caught:
                    parse_coupon_snapshot(value)
                self.assertEqual(caught.exception.code, "FORBIDDEN_SECRET_OR_URL_FIELD")

    def test_scope_evidence_cannot_be_a_url(self):
        with self.assertRaises(CouponContractError):
            parse_coupon_snapshot(payload(coupon__scope_evidence="https://evidence.invalid/x"))

    def test_negative_bool_and_float_prices_are_denied(self):
        for price in (-1, True, 1.5):
            with self.subTest(price=price):
                with self.assertRaises(CouponContractError):
                    parse_coupon_snapshot(payload(base_price_twd=price))

    def test_timestamp_requires_timezone(self):
        with self.assertRaises(CouponContractError) as caught:
            parse_coupon_snapshot(payload(observed_at="2026-11-05T00:00:00"))
        self.assertEqual(caught.exception.code, "OBSERVED_AT_INVALID")

    def test_non_synthetic_classification_is_not_authorized_in_f05(self):
        with self.assertRaises(CouponContractError) as caught:
            parse_coupon_snapshot(payload(data_classification="USER_RECORDED"))
        self.assertEqual(caught.exception.code, "CLASSIFICATION_NOT_AUTHORIZED")


class CurrentCeilingTests(unittest.TestCase):
    def test_c06_ceiling_is_source_blocked_and_empty(self):
        ceiling = load_c06_ceiling(c06_path())
        self.assertEqual(ceiling.state, "SOURCE_AUTHORIZATION_REQUIRED")
        self.assertFalse(ceiling.runtime_authorized)
        self.assertFalse(ceiling.endpoint_hosts)
        self.assertFalse(ceiling.redirect_hosts)

    def test_secret_bearing_c06_key_is_denied(self):
        value = json.loads(c06_path().read_text(encoding="utf-8"))
        value["token"] = "synthetic-but-forbidden"
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            path = Path(folder) / "decision.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(CeilingError) as caught:
                load_c06_ceiling(path)
        self.assertEqual(caught.exception.code, "C06_SECRET_KEY_DENIED")

    def test_forged_positive_affiliate_input_is_suppressed_by_c06(self):
        decision = evaluate(
            trust=affiliate(
                state="VERIFIED", cta_enabled=True, click_url="https://affiliate.coupang.invalid/click/forged", metadata_verified=True
            )
        )
        self.assertFalse(decision.cta_enabled)
        self.assertIsNone(decision.click_url)
        self.assertIn("UNTRUSTED_CLICK_URL_SUPPRESSED", decision.reason_codes)

    def test_internally_inconsistent_affiliate_trust_input_is_denied(self):
        decision = evaluate(
            trust=affiliate(
                state="DISABLED", cta_enabled=True, click_url="https://affiliate.coupang.invalid/click/forged",
                metadata_verified=True, envelope_id="not-a-valid-envelope-id",
            )
        )
        self.assertIn("AFFILIATE_TRUST_INPUT_INVALID", decision.reason_codes)
        self.assertFalse(decision.cta_enabled)
        self.assertIsNone(decision.click_url)


class CouponPriceTests(unittest.TestCase):
    def test_t01_confirmed_coupon_is_primary_price_but_cta_stays_disabled(self):
        decision = evaluate()
        self.assertEqual(decision.base_price_twd, 99)
        self.assertEqual(decision.confirmed_coupon_price_twd, 49)
        self.assertEqual(decision.display_price_twd, 49)
        self.assertEqual(decision.display_basis, "CONFIRMED_COUPON")
        self.assertTrue(decision.coupon_applied)
        self.assertFalse(decision.cta_enabled)

    def test_t02_unconfirmed_statuses_never_become_primary_price(self):
        for status in ("CLAIM_REQUIRED", "UNVERIFIED", "INELIGIBLE", "EXPIRED", "UNKNOWN", "NONE"):
            with self.subTest(status=status):
                value = payload(
                    coupon__status=status,
                    confirmed_coupon_price_twd=None,
                    possible_coupon_price_twd=49,
                    display_price_twd=99,
                    display_basis="BASE",
                )
                decision = evaluate(value)
                self.assertEqual(decision.display_price_twd, 99)
                self.assertIsNone(decision.confirmed_coupon_price_twd)
                self.assertFalse(decision.coupon_applied)
                self.assertFalse(decision.cta_enabled)

    def test_t03_already_included_price_is_not_discounted_twice(self):
        value = payload(
            base_price_twd=49,
            coupon__already_included_in_base=True,
            confirmed_coupon_price_twd=49,
            display_price_twd=49,
            display_basis="CONFIRMED_ALREADY_INCLUDED",
        )
        decision = evaluate(value)
        self.assertEqual(decision.display_price_twd, 49)
        self.assertFalse(decision.coupon_applied)
        self.assertNotIn("ALREADY_INCLUDED_DOUBLE_DISCOUNT_RISK", decision.reason_codes)

    def test_t04_unit_display_and_required_total_remain_separate(self):
        value = payload(
            base_price_twd=100,
            coupon__discount_twd=25,
            confirmed_coupon_price_twd=75,
            display_price_twd=75,
            shipping_status="PAID",
            required_total_twd=150,
        )
        decision = evaluate(value)
        self.assertEqual(decision.display_price_twd, 75)
        self.assertEqual(decision.required_total_twd, 150)
        self.assertNotEqual(decision.display_price_twd, decision.required_total_twd)

    def test_t05_each_identity_dimension_mismatch_rejects_coupon(self):
        for field in ("product_id", "sku_id", "seller_id", "condition", "package_signature"):
            with self.subTest(field=field):
                changed = series(**{field: "OTHER"})
                decision = evaluate(gate_request=request(identity=changed))
                self.assertEqual(decision.display_price_twd, 99)
                self.assertIsNone(decision.confirmed_coupon_price_twd)
                self.assertIn("COUPON_SERIES_IDENTITY_MISMATCH", decision.reason_codes)
                self.assertFalse(decision.cta_enabled)

    def test_t06_coupon_must_be_valid_at_observation_and_now(self):
        cases = (
            (payload(coupon__valid_until="2026-11-05T01:00:00Z"), "COUPON_NOT_CURRENTLY_VALID"),
            (payload(observed_at="2026-10-01T00:00:00Z"), "COUPON_NOT_VALID_AT_OBSERVATION"),
        )
        for value, reason in cases:
            with self.subTest(reason=reason):
                decision = evaluate(value)
                self.assertEqual(decision.display_price_twd, 99)
                self.assertIn(reason, decision.reason_codes)

    def test_future_observation_cannot_form_current_confirmed_price(self):
        decision = evaluate(payload(observed_at="2026-11-06T00:00:00Z", display_price_twd=99, display_basis="BASE"))
        self.assertEqual(decision.display_price_twd, 99)
        self.assertIsNone(decision.confirmed_coupon_price_twd)
        self.assertIn("OBSERVATION_IN_FUTURE", decision.reason_codes)

    def test_confirmed_and_possible_prices_cannot_coexist(self):
        decision = evaluate(payload(possible_coupon_price_twd=45, display_price_twd=99, display_basis="BASE"))
        self.assertEqual(decision.display_price_twd, 99)
        self.assertIn("POSSIBLE_PRICE_PRESENT_WITH_CONFIRMED", decision.reason_codes)

    def test_t07_unknown_shipping_forces_required_total_null(self):
        decision = evaluate(payload(required_total_twd=49))
        self.assertEqual(decision.display_price_twd, 49)
        self.assertIsNone(decision.required_total_twd)
        self.assertIn("UNKNOWN_SHIPPING_REQUIRED_TOTAL_MUST_BE_NULL", decision.reason_codes)

    def test_t08_eligibility_profile_is_exact_and_not_public(self):
        for profile in (None, "PUBLIC", "WOW-OTHER"):
            with self.subTest(profile=profile):
                decision = evaluate(gate_request=request(eligibility_profile=profile))
                self.assertEqual(decision.display_price_twd, 99)
                self.assertIn("COUPON_ELIGIBILITY_PROFILE_MISMATCH", decision.reason_codes)

    def test_t10_zero_is_valid_but_null_remains_unknown(self):
        zero = evaluate(payload(base_price_twd=50, coupon__discount_twd=50, confirmed_coupon_price_twd=0, display_price_twd=0))
        self.assertEqual(zero.display_price_twd, 0)
        self.assertEqual(zero.confirmed_coupon_price_twd, 0)
        unknown = evaluate(
            payload(
                base_price_twd=None, coupon__status="UNKNOWN", coupon__discount_twd=None,
                confirmed_coupon_price_twd=None, display_price_twd=None, display_basis="PRICE_UNKNOWN",
            )
        )
        self.assertIsNone(unknown.display_price_twd)
        self.assertNotEqual(unknown.display_price_twd, 0)

    def test_discount_exceeding_base_does_not_clamp_to_zero(self):
        decision = evaluate(payload(base_price_twd=40, coupon__discount_twd=50, confirmed_coupon_price_twd=0, display_price_twd=40, display_basis="BASE"))
        self.assertEqual(decision.display_price_twd, 40)
        self.assertIsNone(decision.confirmed_coupon_price_twd)
        self.assertIn("COUPON_DISCOUNT_EXCEEDS_BASE", decision.reason_codes)

    def test_math_mismatch_falls_back_to_base(self):
        decision = evaluate(payload(confirmed_coupon_price_twd=48, display_price_twd=99, display_basis="BASE"))
        self.assertEqual(decision.display_price_twd, 99)
        self.assertIn("CONFIRMED_COUPON_PRICE_MATH_MISMATCH", decision.reason_codes)

    def test_upstream_display_mismatch_is_reported_but_safe_value_is_used(self):
        decision = evaluate(payload(display_price_twd=1))
        self.assertEqual(decision.display_price_twd, 49)
        self.assertIn("UPSTREAM_DISPLAY_MISMATCH", decision.reason_codes)

    def test_before_and_confirmed_after_history_counts_stay_separate(self):
        value = payload()
        value["history"] = {"before_coupon": [{"price_twd": 99}], "confirmed_after_coupon": [{"price_twd": 49}, {"price_twd": 48}]}
        snapshot = parse_coupon_snapshot(value)
        self.assertEqual(snapshot.before_coupon_history_count, 1)
        self.assertEqual(snapshot.confirmed_after_coupon_history_count, 2)


class F04EnvelopeIntegrationTests(unittest.TestCase):
    def test_valid_f04_fixture_and_confirmed_coupon_remain_nonclickable(self):
        trust = f04_decision()
        self.assertTrue(trust.metadata_verified)
        decision = evaluate(trust=trust)
        self.assertEqual(decision.display_price_twd, 49)
        self.assertFalse(decision.cta_enabled)
        self.assertIsNone(decision.click_url)

    def test_signature_expiry_host_identity_intent_disclosure_and_revocation_failures_never_enable(self):
        item = f04_identity()
        cases = (
            ("signature", lambda: f04_decision(envelope_mutator=lambda envelope: envelope.__setitem__("signature", "A" + envelope["signature"][1:]))),
            ("expiry", lambda: f04_decision(claims=replace(f04_claims(item), expires_at=NOW))),
            ("host", lambda: f04_decision(claims=replace(f04_claims(item), verified_destination="https://evil.invalid/click/x"))),
            ("identity", lambda: f04_decision(claims=replace(f04_claims(item), sku_id="OTHER-SKU"))),
            ("intent", lambda: f04_decision(user_initiated=False)),
            ("disclosure", lambda: f04_decision(claims=replace(f04_claims(item), disclosure_text="wrong"))),
            ("revocation", lambda: f04_decision(claims=replace(f04_claims(item), revocation_status="REVOKED"))),
        )
        for name, factory in cases:
            with self.subTest(name=name):
                decision = evaluate(trust=factory())
                self.assertEqual(decision.display_price_twd, 49)
                self.assertFalse(decision.cta_enabled)
                self.assertIsNone(decision.click_url)

    def test_f04_replay_is_detected_and_remains_nonclickable(self):
        resolver = AffiliateTrustGatewayV4(f04_codec())
        first = f04_decision(gateway=resolver)
        second = f04_decision(gateway=resolver)
        self.assertTrue(first.metadata_verified)
        self.assertIn("REPLAY_DETECTED", second.reason_codes)
        self.assertFalse(evaluate(trust=second).cta_enabled)

    def test_coupon_state_never_changes_affiliate_trust_state(self):
        for status in ("CONFIRMED_APPLICABLE", "EXPIRED", "UNKNOWN", "INELIGIBLE"):
            with self.subTest(status=status):
                value = payload(coupon__status=status)
                if status != "CONFIRMED_APPLICABLE":
                    value.update({"confirmed_coupon_price_twd": None, "display_price_twd": 99, "display_basis": "BASE"})
                decision = evaluate(value, trust=affiliate(state="DISABLED", metadata_verified=False))
                self.assertEqual(decision.affiliate_trust_state, "DISABLED")
                self.assertFalse(decision.cta_enabled)


class AuditAndStaticTests(unittest.TestCase):
    def test_audit_hashes_raw_source_coupon_and_profile(self):
        sink = MockSink()
        decision = evaluate(gate=AffiliateCouponGateV5(sink=sink))
        encoded = json.dumps(sink.events, ensure_ascii=False)
        for raw in ("SYN-SOURCE-1", "SYN-COUPON-1", "SYN-ELIGIBLE-PROFILE", "SYN-SKU-1", "SYN-SELLER-1"):
            self.assertNotIn(raw, encoded)
        self.assertEqual(decision.audit_event, sink.events[0])

    def test_service_has_no_network_env_browser_or_real_host(self):
        source = "\n".join(path.read_text(encoding="utf-8") for path in SERVICE.rglob("*") if path.is_file())
        for forbidden in ("requests", "httpx", "urllib.request", "socket", "selenium", "playwright", "os.environ", "dotenv", "coupang.com"):
            self.assertNotIn(forbidden, source.casefold())

    def test_env_example_is_disabled_and_inert(self):
        source = (SERVICE / ".env.example").read_text(encoding="utf-8")
        self.assertIn("GATE_MODE=disabled", source)
        self.assertNotIn("http", source.casefold())
        self.assertNotIn("secret=", source.casefold())

    def test_frozen_f04_contract_keeps_fixture_nonclickable(self):
        path = controlled_file(
            "F04_CANDIDATE_TRUST_CONTRACT.md",
            (
                "review", "F05", "controlled_inputs", "F04", "CDH_F04_001_REVIEW", "services",
                "affiliate_gateway_v4", "CANDIDATE_TRUST_CONTRACT.md",
            ),
        )
        source = path.read_text(encoding="utf-8")
        self.assertIn("CONTRACT_FIXTURE_TEST_ONLY", source)
        self.assertIn("always returns null click URL and disabled CTA", source)

    def test_frozen_a08_and_b09_have_no_coupon_v4_silent_mutation(self):
        a08 = controlled_file(
            "A08_TYPES.ts",
            ("review", "F05", "controlled_inputs", "A08", "CDH_A08_001_REVIEW", "apps", "price-web", "frontend", "src", "types.ts"),
        ).read_text(encoding="utf-8")
        b09 = controlled_file(
            "B09_CONTRACT_RECONCILIATION.md",
            ("review", "F05", "controlled_inputs", "B09_002", "CDH_B09_002_REVIEW", "reports", "B09", "CONTRACT_RECONCILIATION.md"),
        ).read_text(encoding="utf-8")
        self.assertNotIn("CDH-COUPON-PRICE-V4", a08)
        self.assertIn("DTO_CHANGE_COUNT: `0`", b09)


if __name__ == "__main__":
    unittest.main()
