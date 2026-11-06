from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def digest(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], cwd: Path, env: dict[str, str]) -> tuple[int, dict, str]:
    result = subprocess.run(command, cwd=cwd, env={**os.environ, **env}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", shell=False, check=False)
    return result.returncode, json.loads(result.stdout), result.stderr


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--b12-root", type=Path, required=True); parser.add_argument("--c09-zip", type=Path, required=True); parser.add_argument("--b11-zip", type=Path, required=True); parser.add_argument("--b11-root", type=Path, required=True); parser.add_argument("--output", type=Path, required=True); args = parser.parse_args()
    b12 = args.b12_root.resolve(); output = args.output.resolve(); temp = output / "bounded_tmp"; temp.mkdir(parents=True, exist_ok=True)
    service = b12 / "services" / "import_staging_b12"; fixtures = service / "fixtures"; env = {"PYTHONPATH": str(service), "CDH_OFFLINE": "1", "NO_PROXY": "*", "HTTP_PROXY": "", "HTTPS_PROXY": "", "TEMP": str(temp), "TMP": str(temp)}
    valid = temp / "synthetic_valid.json"; bridge = temp / "synthetic_c09_bridge.json"; bundle = temp / "synthetic_c09_request_bundle.json"; c09 = temp / args.c09_zip.name
    shutil.copy2(fixtures / "synthetic_valid.json", valid); shutil.copy2(fixtures / "synthetic_c09_bridge.json", bridge); shutil.copy2(fixtures / "synthetic_c09_request_bundle.json", bundle); shutil.copy2(args.c09_zip, c09)
    b11_files = sorted((args.b11_root / "services" / "price_coupon_v4" / "fixtures" / "b11_suite").rglob("coupon.sqlite3")); before = {str(path.relative_to(args.b11_root)): digest(path) for path in b11_files}; release_before = digest(args.b11_zip)
    default_cmd = [sys.executable, "-m", "import_staging_b12", "--input", str(valid), "--allowed-root", str(temp), "--as-of", "2026-11-05T04:00:00Z"]
    exact_cmd = [sys.executable, "-m", "import_staging_b12", "--input", str(bridge), "--allowed-root", str(temp), "--as-of", "2026-11-05T06:00:00Z", "--c09-request-bundle", str(bundle), "--c09-release", str(c09), "--require-all-accepted"]
    default_rc, default, default_err = run(default_cmd, b12, env); exact_rc, exact, exact_err = run(exact_cmd, b12, env)
    after = {str(path.relative_to(args.b11_root)): digest(path) for path in b11_files}; release_after = digest(args.b11_zip)
    assertions = {
        "default_deny_exit_0": default_rc == 0,
        "default_source_denied": default.get("counts", {}).get("DENIED_PROVENANCE") == default.get("record_count") == 2,
        "exact_c09_exit_0": exact_rc == 0,
        "synthetic_preview_accepted": exact.get("counts", {}).get("ACCEPTED_FOR_STAGING_PREVIEW") == exact.get("record_count") == 1,
        "database_write_zero": default.get("database_write_count") == exact.get("database_write_count") == 0,
        "collection_not_authorized": default.get("collection_authorized") is False and exact.get("collection_authorized") is False,
        "c09_identity_bound": exact.get("outcomes", [{}])[0].get("verifier_id") == "C09@a8367fed73efce99e93941a6475f386def7dfa25de27b0e2889d4fe00b1ed0d7",
        "b11_sqlite_unchanged": before == after,
        "b11_release_unchanged": release_before == release_after,
    }
    result = {"schema": "CDH-G08-B12-C09-STAGING-1", "assertions": assertions, "default_deny": default, "exact_synthetic_preview": exact, "stderr": {"default": default_err, "exact": exact_err}, "b11_hashes": {"before": before, "after": after, "release_before": release_before, "release_after": release_after}, "passed": all(assertions.values())}
    output.mkdir(parents=True, exist_ok=True); (output / "import_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(temp, ignore_errors=True); print(json.dumps({"passed": result["passed"], "assertions": assertions}, sort_keys=True)); return 0 if result["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
