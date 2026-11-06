from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from wsgiref.simple_server import make_server


ROOT = Path(__file__).resolve().parents[2]
B11_ROOT = ROOT / "review" / "H07" / "baselines" / "B11" / "CDH_B_R07_001_REVIEW"
SERVICE_ROOT = B11_ROOT / "services" / "price_coupon_v4"
FIXTURE_ROOT = SERVICE_ROOT / "fixtures" / "b11_suite"
EXPECTED_RELEASE_SHA256 = "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"
sys.path.insert(0, str(SERVICE_ROOT))
from price_coupon_v4.server import create_app  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_hashes(fixture: str) -> tuple[str, str]:
    manifest = json.loads((FIXTURE_ROOT / "FIXTURE_MANIFEST.json").read_text(encoding="utf-8"))
    record = next(item for item in manifest["snapshots"] if item["directory"] == fixture)
    return record["database_sha256"], record["authority_sha256"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", choices=("active", "expired-source", "revoked-source", "empty-history"), default="active")
    parser.add_argument("--port", type=int, default=8796)
    parser.add_argument("--runtime-root", type=Path, required=True)
    args = parser.parse_args()
    release = ROOT / "review" / "releases" / "CDH_B_R07_001_REVIEW.zip"
    if sha256(release) != EXPECTED_RELEASE_SHA256:
        raise RuntimeError("exact B11 release SHA-256 gate failed")
    source = FIXTURE_ROOT / args.fixture
    database_source, authority_source = source / "coupon.sqlite3", source / "coupon.authority.json"
    database_sha, authority_sha = expected_hashes(args.fixture)
    if sha256(database_source) != database_sha or sha256(authority_source) != authority_sha:
        raise RuntimeError("B11 fixture hash gate failed")
    args.runtime_root.mkdir(parents=True, exist_ok=True)
    runtime = Path(tempfile.mkdtemp(prefix=f"b11-{args.fixture}-", dir=args.runtime_root))
    database, authority = runtime / "coupon.sqlite3", runtime / "coupon.authority.json"
    shutil.copyfile(database_source, database); shutil.copyfile(authority_source, authority)
    app = create_app(database, authority, runtime)
    print(json.dumps({"status":"B11_EXACT_READY","release_sha256":EXPECTED_RELEASE_SHA256,"fixture":args.fixture,"database_sha256":sha256(database),"authority_sha256":sha256(authority),"data_version":app.repository.data_version,"url":f"http://127.0.0.1:{args.port}","runtime":str(runtime)}, ensure_ascii=False), flush=True)
    with make_server("127.0.0.1", args.port, app) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
