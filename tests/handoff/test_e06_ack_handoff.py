from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = PROJECT_ROOT / "scripts/orchestrator_handoff"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import flat_queue


LOCAL_TEMP = PROJECT_ROOT / "review/E06/test_tmp"
LOCAL_TEMP.mkdir(parents=True, exist_ok=True)
R05_NAMES = (
    "CDH_A07_001_REVIEW.zip",
    "CDH_B08_001_REVIEW.zip",
    "CDH_C05_001_REVIEW.zip",
    "CDH_D05_WEB_001_REVIEW.zip",
    "CDH_E05_001_REVIEW.zip",
    "CDH_F03_001_REVIEW.zip",
    "CDH_G03_001_REVIEW.zip",
    "CDH_H02_001_REVIEW.zip",
)


def make_release(root: Path, name: str) -> Path:
    release = root / "review/releases" / name
    release.parent.mkdir(parents=True, exist_ok=True)
    content = f"synthetic fixture for {name}\n".encode()
    manifest = {
        "payloads": [
            {
                "path": "payload/result.txt",
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ]
    }
    with zipfile.ZipFile(release, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("payload/result.txt", content)
        archive.writestr("REVIEW_MANIFEST.json", json.dumps(manifest))
    return release


class E06AckHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=LOCAL_TEMP)
        self.root = Path(self.temp.name) / "酷澎比價系統"
        (self.root / "review/releases").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_eight_exact_acks_archive_queue_copies_and_preserve_releases(self) -> None:
        releases = [make_release(self.root, name) for name in R05_NAMES]
        release_hashes = {
            release.name: hashlib.sha256(release.read_bytes()).hexdigest()
            for release in releases
        }
        flat_queue.enqueue_releases(self.root, list(R05_NAMES))
        ack_file = self.root / "review/E06/exact_acks.json"
        ack_file.parent.mkdir(parents=True)
        ack_file.write_text(
            json.dumps(
                {
                    "schema": "CDH-EXACT-ACK-1",
                    "acks": [
                        {"filename": name, "sha256": release_hashes[name]}
                        for name in R05_NAMES
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = flat_queue.archive_ack_file(
            self.root, ack_file, "20261105_R05_ACK", True
        )
        self.assertEqual(result["archived_count"], 8)
        self.assertEqual(result["failure_count"], 0)
        self.assertEqual(result["pending_count"], 0)
        for name in R05_NAMES:
            release = self.root / "review/releases" / name
            archived = self.root / "review/90_UPLOADED_ARCHIVE/20261105_R05_ACK" / name
            self.assertEqual(hashlib.sha256(release.read_bytes()).hexdigest(), release_hashes[name])
            self.assertEqual(hashlib.sha256(archived.read_bytes()).hexdigest(), release_hashes[name])
        ledger = (self.root / "docs/HANDOFF/RECEIPT_LEDGER.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(len(ledger), 8)

        replay = flat_queue.archive_ack_file(
            self.root, ack_file, "20261105_R05_ACK", True
        )
        self.assertEqual(replay["already_archived_count"], 8)
        self.assertEqual(replay["archived_count"], 0)
        ledger_after = (self.root / "docs/HANDOFF/RECEIPT_LEDGER.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(len(ledger_after), 8)

    def test_checked_in_ack_authority_matches_central_r05_values(self) -> None:
        path = PROJECT_ROOT / "review/E06/R05_EXACT_ACKS.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], "CDH-EXACT-ACK-1")
        self.assertEqual(tuple(item["filename"] for item in payload["acks"]), R05_NAMES)
        self.assertEqual(len({item["sha256"] for item in payload["acks"]}), 8)
        self.assertTrue(all(len(item["sha256"]) == 64 for item in payload["acks"]))


if __name__ == "__main__":
    unittest.main()
