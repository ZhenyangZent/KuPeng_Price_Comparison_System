from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REV2 = ROOT / "review/D13/002/input/CDH_B_R12_002_REVIEW"
REV3 = ROOT / "review/D13/003/input/CDH_B_R12_003_REVIEW"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    one = json.loads((REV2 / "services/private_batch_import_b16/openapi/b16.openapi.json").read_text(encoding="utf-8"))
    two = json.loads((REV3 / "services/private_batch_import_b16/openapi/b16.openapi.json").read_text(encoding="utf-8"))
    routes = set(one["paths"]) == set(two["paths"])
    preview = one["components"]["schemas"]["PreviewRequest"] == two["components"]["schemas"]["PreviewRequest"]
    confirm = one["components"]["schemas"]["ConfirmRequest"] == two["components"]["schemas"]["ConfirmRequest"]
    b15_one = REV2 / "services/private_observation_b15"; b15_two = REV3 / "services/private_observation_b15"
    b15_files_one = {path.relative_to(b15_one).as_posix(): sha(path) for path in b15_one.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}
    b15_files_two = {path.relative_to(b15_two).as_posix(): sha(path) for path in b15_two.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}
    root_one = REV2 / "services/private_batch_import_b16/private_batch_import_b16"; root_two = REV3 / "services/private_batch_import_b16/private_batch_import_b16"
    names = sorted({path.name for path in root_one.glob("*.py")} | {path.name for path in root_two.glob("*.py")})
    changed = [name for name in names if sha(root_one / name) != sha(root_two / name)]
    gate = routes and preview and confirm and b15_files_one == b15_files_two and changed == ["store.py"]
    result = {"schema_version": "CDH-D13-B16-REV3-COMPATIBILITY-1", "route_set_gate": "PASS" if routes else "FAIL", "preview_request_schema_gate": "PASS" if preview else "FAIL", "confirm_request_schema_gate": "PASS" if confirm else "FAIL", "b15_service_byte_identity_gate": "PASS" if b15_files_one == b15_files_two else "FAIL", "b16_python_changed_files": changed, "a15_interface_change_required": not (routes and preview and confirm), "gate": "PASS" if gate else "FAIL"}
    output = ROOT / "review/D13/003/evidence/COMPATIBILITY.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
