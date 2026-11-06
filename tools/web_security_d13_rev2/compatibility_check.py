from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REV1 = ROOT / "review" / "D13" / "001" / "input" / "CDH_B_R12_001_REVIEW"
REV2 = ROOT / "review" / "D13" / "002" / "input" / "CDH_B_R12_002_REVIEW"
A15_ZIP = ROOT / "review" / "releases" / "CDH_A_R12_001_REVIEW.zip"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    openapi1 = json.loads((REV1 / "services/private_batch_import_b16/openapi/b16.openapi.json").read_text(encoding="utf-8"))
    openapi2 = json.loads((REV2 / "services/private_batch_import_b16/openapi/b16.openapi.json").read_text(encoding="utf-8"))
    schemas1 = openapi1["components"]["schemas"]
    schemas2 = openapi2["components"]["schemas"]
    route_gate = set(openapi1["paths"]) == set(openapi2["paths"])
    preview_gate = schemas1["PreviewRequest"] == schemas2["PreviewRequest"]
    confirm_gate = schemas1["ConfirmRequest"] == schemas2["ConfirmRequest"]
    b15_root1 = REV1 / "services/private_observation_b15"
    b15_root2 = REV2 / "services/private_observation_b15"
    b15_files1 = {path.relative_to(b15_root1).as_posix(): sha(path) for path in b15_root1.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}
    b15_files2 = {path.relative_to(b15_root2).as_posix(): sha(path) for path in b15_root2.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}
    b15_gate = b15_files1 == b15_files2
    batch_root1 = REV1 / "services/private_batch_import_b16/private_batch_import_b16"
    batch_root2 = REV2 / "services/private_batch_import_b16/private_batch_import_b16"
    names = sorted({path.name for path in batch_root1.glob("*.py")} | {path.name for path in batch_root2.glob("*.py")})
    changed = [name for name in names if sha(batch_root1 / name) != sha(batch_root2 / name)]
    with zipfile.ZipFile(A15_ZIP) as archive:
        source = archive.read("CDH_A_R12_001_REVIEW/apps/price-web/frontend/src/batchImportClient.ts").decode("utf-8")
        test = archive.read("CDH_A_R12_001_REVIEW/apps/price-web/frontend/tests/a15_b16_integration.test.tsx").decode("utf-8")
    a15_409_gate = "this.raise(result.payload, result.status)" in source and "it.each([400, 403, 409])" in test
    result = {
        "schema_version": "CDH-D13-B16-REV2-A15-COMPATIBILITY-1",
        "route_set_gate": "PASS" if route_gate else "FAIL",
        "preview_request_schema_gate": "PASS" if preview_gate else "FAIL",
        "confirm_request_schema_gate": "PASS" if confirm_gate else "FAIL",
        "b15_service_byte_identity_gate": "PASS" if b15_gate else "FAIL",
        "b16_python_changed_files": changed,
        "a15_http_409_handling_gate": "PASS" if a15_409_gate else "FAIL",
        "a15_reaudit_required": False if all((route_gate, preview_gate, confirm_gate, b15_gate, a15_409_gate)) else True,
    }
    result["gate"] = "PASS" if not result["a15_reaudit_required"] else "FAIL"
    evidence = ROOT / "review" / "D13" / "002" / "evidence" / "A15_B16_REV2_COMPATIBILITY.json"
    evidence.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
