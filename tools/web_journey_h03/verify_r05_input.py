from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve().parents[2]
ARCHIVE = PROJECT / "input" / "orchestrator_bundles" / "UNIFIED_CONTINUOUS_20261105_R05" / "CDH_UNIFIED_CONTINUOUS_20261105_R05.zip"
OUTPUT = PROJECT / "reports" / "H03" / "INPUT_VERIFICATION.json"
EXPECTED = "d0993915ff725541ca0c5053f32eddca82888082fcd1b9650f35d80c738237cd"


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    archive_sha = digest_bytes(ARCHIVE.read_bytes())
    with zipfile.ZipFile(ARCHIVE) as archive:
        crc_failure = archive.testzip()
        infos = archive.infolist()
        names = [item.filename for item in infos]
        manifest = json.loads(archive.read("MANIFEST.json"))
        mismatches = []
        for item in manifest["files"]:
            try:
                value = archive.read(item["path"])
            except KeyError:
                mismatches.append({"path": item["path"], "reason": "missing"})
                continue
            if len(value) != item["bytes"] or digest_bytes(value) != item["sha256"]:
                mismatches.append({"path": item["path"], "reason": "size_or_sha256"})
        declared = {"MANIFEST.json", *(item["path"] for item in manifest["files"])}
        unsafe = [name for name in names if "\\" in name or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts]
        symlinks = [item.filename for item in infos if stat.S_ISLNK((item.external_attr >> 16) & 0xFFFF)]
        result = {
            "archive": str(ARCHIVE.relative_to(PROJECT)).replace("\\", "/"),
            "expected_sha256": EXPECTED,
            "actual_sha256": archive_sha,
            "sha256_gate": "PASS" if archive_sha == EXPECTED else "FAIL",
            "crc_gate": "PASS" if crc_failure is None else "FAIL",
            "entry_count": len(names),
            "manifest_payload_count": manifest["payload_count"],
            "manifest_mismatch_count": len(mismatches),
            "undeclared_count": len(set(names) - declared),
            "missing_declared_count": len(declared - set(names)),
            "duplicate_count": len(names) - len(set(names)),
            "case_collision_count": len(names) - len({name.casefold() for name in names}),
            "unsafe_path_count": len(unsafe),
            "symlink_count": len(symlinks),
            "status": "PASS" if archive_sha == EXPECTED and crc_failure is None and not mismatches and set(names) == declared and len(names) == len(set(names)) and len(names) == len({name.casefold() for name in names}) and not unsafe and not symlinks else "FAIL",
        }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
