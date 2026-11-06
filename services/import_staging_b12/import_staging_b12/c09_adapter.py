from __future__ import annotations

import hashlib
import importlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

from .provenance import ProvenanceContractError, ProvenanceResult

BUNDLE_SCHEMA = "CDH-B12-C09-REQUEST-BUNDLE-1"
C09_REQUEST_SCHEMA = "CDH-B12-C09-GATE-REQUEST-1"
C09_DECISION_SCHEMA = "CDH-C09-PROVENANCE-DECISION-1"
BINDING_KEYS = {"record_id", "record_sha256", "request"}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ProvenanceContractError("C09 bundle evaluation_time must use UTC Z form")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ProvenanceContractError("C09 bundle evaluation_time is invalid") from exc
    return parsed.astimezone(timezone.utc)


def _safe_member(name: str) -> bool:
    value = PurePosixPath(name)
    return bool(name) and not value.is_absolute() and ".." not in value.parts and "\\" not in name and "\x00" not in name


def verify_c09_release_source(release: Path, *, expected_sha256: str, project_root: Path) -> dict[str, object]:
    """Bind the importable workspace C09 gate to an exact immutable release."""
    if not release.is_file() or _sha256(release) != expected_sha256:
        raise ProvenanceContractError("C09 release SHA-256 mismatch")
    with zipfile.ZipFile(release) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if any(not _safe_member(name) for name in names):
            raise ProvenanceContractError("C09 release contains unsafe path")
        if len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}):
            raise ProvenanceContractError("C09 release contains duplicate path")
        if any(((item.external_attr >> 16) & 0o170000) == 0o120000 for item in infos):
            raise ProvenanceContractError("C09 release contains symlink member")
        if archive.testzip() is not None:
            raise ProvenanceContractError("C09 release CRC failed")
        manifest_names = [name for name in names if name.endswith("/MANIFEST.json")]
        if len(manifest_names) != 1:
            raise ProvenanceContractError("C09 release manifest is ambiguous")
        manifest = json.loads(archive.read(manifest_names[0]))
        package_prefix = manifest_names[0][:-len("MANIFEST.json")]
        declared = {package_prefix + item["path"]: item for item in manifest["payloads"]}
        mismatches = []
        for name, item in declared.items():
            data = archive.read(name)
            if len(data) != item["bytes"] or _sha256_bytes(data) != item["sha256"]:
                mismatches.append(name)
        if mismatches:
            raise ProvenanceContractError("C09 release manifest payload mismatch")
        suffixes = (
            "/research/import_provenance_c09/gate.py",
            "/research/import_provenance_c09/__init__.py",
        )
        source_members = {}
        for suffix in suffixes:
            matches = [name for name in names if name.endswith(suffix)]
            if len(matches) != 1:
                raise ProvenanceContractError("C09 release source member is missing or ambiguous")
            source_members[suffix] = matches[0]
        workspace_files = {
            suffixes[0]: project_root / "research" / "import_provenance_c09" / "gate.py",
            suffixes[1]: project_root / "research" / "import_provenance_c09" / "__init__.py",
        }
        for suffix, path in workspace_files.items():
            if not path.is_file() or path.read_bytes() != archive.read(source_members[suffix]):
                raise ProvenanceContractError("workspace C09 verifier does not match exact release")
    return {"release_sha256": expected_sha256, "source_gate": "PASS", "crc": "PASS", "manifest_gate": "PASS"}


def _cross_binding_issues(record: dict[str, object], request: object) -> list[str]:
    if not isinstance(request, dict) or request.get("schema_version") != C09_REQUEST_SCHEMA:
        return ["C09_REQUEST_SCHEMA_MISMATCH"]
    staged = request.get("staged_record")
    provenance = request.get("provenance")
    if not isinstance(staged, dict) or not isinstance(provenance, dict):
        return ["C09_REQUEST_SHAPE_INVALID"]
    identity = record.get("identity")
    coupon = record.get("coupon")
    source = record.get("source")
    staged_identity = staged.get("identity")
    staged_coupon = staged.get("coupon")
    c09_source = provenance.get("source")
    if not all(isinstance(value, dict) for value in (identity, coupon, source, staged_identity, staged_coupon, c09_source)):
        return ["C09_CROSS_BINDING_SHAPE_INVALID"]
    assert isinstance(identity, dict) and isinstance(coupon, dict) and isinstance(source, dict)
    assert isinstance(staged_identity, dict) and isinstance(staged_coupon, dict) and isinstance(c09_source, dict)
    checks = {
        "RECORD_ID": (record.get("record_id"), staged.get("record_id")),
        "PLATFORM": (identity.get("platform"), staged_identity.get("platform")),
        "PRODUCT_ID": (identity.get("product_id"), staged_identity.get("product_id")),
        "SKU_ID": (identity.get("sku_id"), staged_identity.get("sku_id")),
        "SELLER_ID": (identity.get("seller_id"), staged_identity.get("seller_id")),
        "CONDITION": (identity.get("condition"), staged_identity.get("condition")),
        "PACKAGE": (identity.get("package_signature"), staged_identity.get("package_identity")),
        "QUANTITY": (record.get("minimum_purchase_quantity"), staged_identity.get("quantity")),
        "OBSERVATION_TIME": (record.get("observed_at"), staged.get("observation_time_utc")),
        "COUPON_ID": (coupon.get("coupon_id"), staged_coupon.get("coupon_id")),
        "VALID_FROM": (coupon.get("valid_from"), staged_coupon.get("valid_from")),
        "VALID_UNTIL": (coupon.get("valid_until"), staged_coupon.get("valid_until")),
        "ELIGIBILITY_PROFILE": (coupon.get("eligibility_profile"), staged_coupon.get("eligibility_profile")),
        "TARGET_PRODUCT": (coupon.get("target_product_id"), staged_coupon.get("eligible_product_id")),
        "TARGET_SKU": (coupon.get("target_sku_id"), staged_coupon.get("eligible_sku_id")),
        "TARGET_SELLER": (coupon.get("target_seller_id"), staged_coupon.get("eligible_seller_id")),
        "EVIDENCE_ID": (source.get("evidence_id"), c09_source.get("evidence_id")),
        "SOURCE_ID": (source.get("source_candidate_id"), c09_source.get("source_id")),
    }
    issues = [f"C09_BINDING_{name}_MISMATCH" for name, pair in checks.items() if pair[0] != pair[1]]
    if coupon.get("status") != "CONFIRMED_APPLICABLE" or staged_coupon.get("status") != "CONFIRMED_APPLICABLE_SYNTHETIC":
        issues.append("C09_BINDING_COUPON_STATUS_MISMATCH")
    if source.get("data_classification") != "SYNTHETIC_FIXTURE":
        issues.append("C09_BINDING_CLASSIFICATION_NOT_SYNTHETIC")
    if staged.get("link_url") is not None:
        issues.append("C09_BINDING_LINK_NOT_NULL")
    return sorted(set(issues))


class C09ModuleVerifier:
    """Consumes the exact C09 Python interface and cross-binds it to B12 records."""

    def __init__(
        self,
        bundle_path: Path,
        *,
        expected_input_sha256: str,
        expected_c09_release_sha256: str,
        verify_request: Callable[..., dict[str, object]],
    ) -> None:
        try:
            value = json.loads(bundle_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProvenanceContractError("invalid C09 request bundle") from exc
        keys = {"schema_version", "input_sha256", "c09_release_sha256", "evaluation_time", "bindings"}
        if not isinstance(value, dict) or set(value) != keys:
            raise ProvenanceContractError("C09 request bundle fields must match exact contract")
        if value["schema_version"] != BUNDLE_SCHEMA or value["input_sha256"] != expected_input_sha256:
            raise ProvenanceContractError("C09 request bundle schema or input hash mismatch")
        if value["c09_release_sha256"] != expected_c09_release_sha256:
            raise ProvenanceContractError("C09 request bundle release hash mismatch")
        if not isinstance(value["bindings"], list):
            raise ProvenanceContractError("C09 bindings must be an array")
        bindings: dict[str, dict[str, object]] = {}
        for item in value["bindings"]:
            if not isinstance(item, dict) or set(item) != BINDING_KEYS:
                raise ProvenanceContractError("C09 binding fields must match exact contract")
            record_id = item["record_id"]
            if not isinstance(record_id, str) or not record_id or record_id in bindings:
                raise ProvenanceContractError("C09 binding record_id must be unique")
            bindings[record_id] = item
        self._input_sha256 = expected_input_sha256
        self._release_sha256 = expected_c09_release_sha256
        self._evaluation_time = _parse_utc(value["evaluation_time"])
        self._bindings = bindings
        self._verify_request = verify_request

    def verify(self, record: dict[str, object], *, input_sha256: str, record_sha256: str) -> ProvenanceResult:
        if input_sha256 != self._input_sha256:
            return ProvenanceResult(False, f"C09@{self._release_sha256}", "DENY", ("INPUT_SHA256_MISMATCH",))
        item = self._bindings.get(str(record.get("record_id", "")))
        if item is None:
            return ProvenanceResult(False, f"C09@{self._release_sha256}", "DENY", ("C09_REQUEST_MISSING",))
        if item["record_sha256"] != record_sha256:
            return ProvenanceResult(False, f"C09@{self._release_sha256}", "DENY", ("RECORD_SHA256_MISMATCH",))
        issues = _cross_binding_issues(record, item["request"])
        if issues:
            return ProvenanceResult(False, f"C09@{self._release_sha256}", "DENY", tuple(issues))
        try:
            decision = self._verify_request(item["request"], now=self._evaluation_time)
        except Exception:
            return ProvenanceResult(False, f"C09@{self._release_sha256}", "DENY", ("C09_VERIFIER_EXCEPTION",))
        invariants = (
            decision.get("schema_version") == C09_DECISION_SCHEMA,
            decision.get("decision") == "ALLOW_SYNTHETIC_PREFLIGHT",
            decision.get("fixture_only") is True,
            decision.get("canonical_write_authorized") is False,
            decision.get("b11_mutation_authorized") is False,
            decision.get("runtime_authorized") is False,
            decision.get("cta_enabled") is False,
            decision.get("click_url") is None,
            decision.get("source_state") == "SOURCE_BLOCKED",
        )
        if not all(invariants):
            reasons = decision.get("reason_codes")
            if not isinstance(reasons, list) or not all(isinstance(reason, str) for reason in reasons):
                reasons = ["C09_DECISION_INVARIANT_FAILED"]
            return ProvenanceResult(False, f"C09@{self._release_sha256}", "DENY", tuple(sorted(set(reasons + ["C09_NOT_ALLOWED"]))))
        return ProvenanceResult(True, f"C09@{self._release_sha256}", "ALLOW_STAGING_PREVIEW", ("C09_ALLOW_SYNTHETIC_PREFLIGHT",))


def load_verified_c09_verifier(
    bundle_path: Path,
    *,
    expected_input_sha256: str,
    c09_release: Path,
    project_root: Path,
) -> C09ModuleVerifier:
    """Verify the exact C09 release and load only its byte-identical workspace module."""
    try:
        envelope = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProvenanceContractError("invalid C09 request bundle") from exc
    release_sha = envelope.get("c09_release_sha256") if isinstance(envelope, dict) else None
    if not isinstance(release_sha, str) or len(release_sha) != 64 or any(character not in "0123456789abcdef" for character in release_sha):
        raise ProvenanceContractError("C09 request bundle release SHA-256 is invalid")
    verify_c09_release_source(c09_release, expected_sha256=release_sha, project_root=project_root)
    root_text = str(project_root)
    while root_text in sys.path:
        sys.path.remove(root_text)
    sys.path.insert(0, root_text)
    try:
        importlib.invalidate_caches()
        gate = importlib.import_module("research.import_provenance_c09.gate")
        expected_gate = (project_root / "research" / "import_provenance_c09" / "gate.py").resolve()
        if Path(gate.__file__).resolve() != expected_gate:
            raise ProvenanceContractError("imported C09 verifier path is not the verified workspace path")
        gate = importlib.reload(gate)
        verify_request = gate.verify_request
    except (ImportError, AttributeError) as exc:
        raise ProvenanceContractError("exact C09 verifier cannot be imported") from exc
    return C09ModuleVerifier(
        bundle_path,
        expected_input_sha256=expected_input_sha256,
        expected_c09_release_sha256=release_sha,
        verify_request=verify_request,
    )
