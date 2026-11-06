from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

from tools.web_security_d06.targets import safe_member_name, sha256_file


R07_SHA256 = "76b1332c3e2cd82a05e5f26e6d3e0c01cdf65e828f82d5b586902bdfacda2827"
R07_MANIFEST_SHA256 = "121bb4485deed86b7e8b32868219421002e3a2da604f67e47c58a57d46035767"
SEARCH_SHA256 = "10f05f11ca90a6ae60208399e787a5ad0ab9440a06280049df415462cae08968"
DETAIL_SHA256 = "cc6d318301414909f8ec854eb23c40c9d90f512abcb8f934def5365fc5100c68"


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_r07_evidence(bundle: str | Path) -> dict[str, object]:
    path = Path(bundle)
    if sha256_file(path) != R07_SHA256:
        raise ValueError("R07_BUNDLE_SHA256_MISMATCH")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if archive.testzip() is not None:
            raise ValueError("R07_BUNDLE_CRC_FAILURE")
        if any(not safe_member_name(name) for name in names):
            raise ValueError("R07_BUNDLE_UNSAFE_PATH")
        if len(names) != len({name.casefold() for name in names}):
            raise ValueError("R07_BUNDLE_CASEFOLD_DUPLICATE")
        if any(stat.S_ISLNK(item.external_attr >> 16) for item in infos):
            raise ValueError("R07_BUNDLE_SYMLINK")
        manifest_raw = archive.read("MANIFEST.json")
        if _digest(manifest_raw) != R07_MANIFEST_SHA256:
            raise ValueError("R07_MANIFEST_SHA256_MISMATCH")
        manifest = json.loads(manifest_raw)
        records = manifest.get("files")
        if not isinstance(records, list):
            raise ValueError("R07_MANIFEST_FORMAT_INVALID")
        declared: set[str] = set()
        for record in records:
            name = record["path"]
            raw = archive.read(name)
            declared.add(name)
            if len(raw) != record["bytes"] or _digest(raw) != record["sha256"]:
                raise ValueError(f"R07_MANIFEST_PAYLOAD_FAILURE:{name}")
        if declared | {"MANIFEST.json"} != set(names):
            raise ValueError("R07_MANIFEST_COVERAGE_FAILURE")
        search_raw = archive.read("EVIDENCE/B10_REAL_SEARCH.json")
        detail_raw = archive.read("EVIDENCE/B10_REAL_DETAIL.json")
        if _digest(search_raw) != SEARCH_SHA256 or _digest(detail_raw) != DETAIL_SHA256:
            raise ValueError("R07_EVIDENCE_SHA256_MISMATCH")
        return {
            "identity": {
                "bundle_sha256": R07_SHA256,
                "manifest_sha256": R07_MANIFEST_SHA256,
                "entries": len(names),
                "payloads": len(records),
                "crc_pass": True,
            },
            "search_sha256": SEARCH_SHA256,
            "detail_sha256": DETAIL_SHA256,
            "search": json.loads(search_raw),
            "detail": json.loads(detail_raw),
            "central_reproduction": archive.read("EVIDENCE/A09_B10_PARSER_ACTUAL.txt").decode("utf-8-sig"),
        }
