from __future__ import annotations

import json
import re

from .models import Check, Finding


def assess_quality_integration(*, b07_schema: str, b07_compatibility: str, frontend_types: str) -> tuple[list[Check], list[Finding]]:
    adapter_required = "READONLY_ADAPTER_REQUIRED_FOR_B08" in b07_compatibility or "future B08 adapter" in b07_schema
    frontend_quality = "source_freshness" in frontend_types and "exact_match_claim_allowed" in frontend_types
    integrated = not adapter_required and frontend_quality
    checks = [Check("B07_QUALITY_TO_B06_A06_INTEGRATED", integrated, f"adapter_required={adapter_required}; frontend_quality_fields={frontend_quality}")]
    findings: list[Finding] = []
    if not integrated:
        findings.append(Finding(
            "D05-P1-002", "P1", "B/A", "B07 reliability output is not integrated into B06/A06",
            "B07 B06_V2_COMPATIBILITY.md and A06 src/types.ts",
            "B07 explicitly reports READONLY_ADAPTER_REQUIRED_FOR_B08 and rejects the older B06 fixture schema. A06 does not consume source_freshness or exact_match_claim_allowed, so the current website cannot claim the stricter B07 reliability semantics.",
            "Read the exact B07 compatibility status and search the exact A06 type surface for B07 quality fields.",
            "Add a separately authorized B adapter, freeze its DTO, then test stale, zero, unknown, missing-day, and incomplete-identity rendering in A.",
        ))
    return checks, findings


def assess_affiliate_bridge(*, c04_readiness_raw: bytes, f02_binding: str, f02_contract: str) -> tuple[list[Check], list[Finding]]:
    readiness = json.loads(c04_readiness_raw)
    runtime = readiness.get("runtime") if isinstance(readiness, dict) else {}
    current_disabled = (
        readiness.get("provider_state") == "SOURCE_AUTHORIZATION_REQUIRED"
        and isinstance(runtime, dict)
        and runtime.get("cta_enabled") is False
        and runtime.get("click_url") is None
        and runtime.get("output_host_allowlist") == []
    )
    checks = [Check("C04_CURRENT_AUTHORITY_FAIL_CLOSED", current_disabled, f"provider_state={readiness.get('provider_state')}; cta={runtime.get('cta_enabled') if isinstance(runtime, dict) else None}")]
    findings: list[Finding] = []
    if not current_disabled:
        findings.append(Finding(
            "D05-P0-005", "P0", "C/F", "C04 authority state is not fail-closed",
            "C04 CAPABILITY_READINESS.json",
            "The current evidence state must not provide a click URL, output host, or enabled CTA.",
            "Parse the exact C04 readiness artifact and inspect provider/runtime fields.",
            "Keep runtime disabled until independently reviewed Taiwan official evidence is hash-bound.",
        ))

    f02_required_match = re.search(r"REQUIRED_RUNTIME_CAPABILITIES\s*=\s*frozenset\((.*?)\)\s*ABSORBING", f02_binding, re.S)
    f02_required = set(re.findall(r'"([a-z_]+)"', f02_required_match.group(1))) if f02_required_match else set()
    c04_capabilities = set(readiness.get("capabilities", {})) if isinstance(readiness.get("capabilities"), dict) else set()
    directly_compatible = bool(f02_required) and f02_required.issubset(c04_capabilities) and "C04" in f02_contract
    checks.append(Check("C04_TO_F02_AUTHORITY_BRIDGE_FROZEN", directly_compatible, f"f02_required={sorted(f02_required)}; missing_from_c04={sorted(f02_required-c04_capabilities)}"))
    if not directly_compatible:
        findings.append(Finding(
            "D05-P1-003", "P1", "C/F", "No frozen C04-to-F02 runtime authority bridge exists",
            "C04 CAPABILITY_READINESS.json and F02 binding.py/F02_V2_BINDING_CONTRACT.md",
            "F02 was built against C03 terminology and requires link_generation, while C04 exposes manual_link_generation and api_link_generation and remains candidate-only. This is safely disabled today but has no reviewed promotion path after future official evidence.",
            "Compare F02 REQUIRED_RUNTIME_CAPABILITIES and controlled-input contract with the exact C04 capability keys.",
            "Freeze a C04-to-F adapter mapping with exact semantic equivalence, authority expiry, evidence hashes, and a regression that refuses unknown capability names.",
        ))
    return checks, findings
