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
import handoff_continuity


LOCAL_TEMP = PROJECT_ROOT / "experiments/E05/test_tmp"
LOCAL_TEMP.mkdir(parents=True, exist_ok=True)


def make_release(root: Path, name: str, content: bytes) -> Path:
    release = root / "review/releases" / name
    release.parent.mkdir(parents=True, exist_ok=True)
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


def write_assignments(root: Path) -> Path:
    path = root / "input/ASSIGNMENTS.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "roles": {
                    role: {
                        "task_id": f"TASK-{role}",
                        "expected_review": f"CDH_{role}09_001_REVIEW.zip",
                    }
                    for role in "ABCE"
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def write_flat_assignments(root: Path) -> Path:
    path = root / "input/R05_ASSIGNMENTS.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                role: {
                    "task_id": f"R05-TASK-{role}",
                    "next_review_zip": f"CDH_{role}10_001_REVIEW.zip",
                }
                for role in "ABCDEFGH"
            }
        ),
        encoding="utf-8",
    )
    return path


def write_r06_assignments(root: Path) -> Path:
    path = root / "input/R06_ASSIGNMENTS.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "CDH-R06-ASSIGNMENTS-V1",
                "roles": {
                    role: {
                        "task_id": f"R06-TASK-{role}",
                        "deliverable": f"CDH_{role}_R06_001_REVIEW.zip",
                    }
                    for role in "ABCDEFGH"
                },
            }
        ),
        encoding="utf-8",
    )
    return path


class HandoffContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=LOCAL_TEMP)
        self.root = Path(self.temp.name) / "酷澎比價系統"
        (self.root / "review/releases").mkdir(parents=True)
        (self.root / "docs/HANDOFF").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_protected_inventory_is_allowlisted_and_never_reads_env(self) -> None:
        (self.root / ".env").write_bytes(b"REAL_SECRET_MUST_NOT_BE_READ")
        (self.root / "docs/HANDOFF/MASTER_HANDOFF.md").write_text("master", encoding="utf-8")
        release = make_release(self.root, "CDH_E05_001_REVIEW.zip", b"synthetic")
        inventory = handoff_continuity.build_protected_inventory(self.root)
        paths = {item["path"] for item in inventory["records"]}
        self.assertIn("docs/HANDOFF/MASTER_HANDOFF.md", paths)
        self.assertIn("review/releases/CDH_E05_001_REVIEW.zip", paths)
        self.assertNotIn(".env", paths)
        self.assertFalse(inventory["root_env_content_read"])
        release_record = next(item for item in inventory["records"] if item["path"].endswith(release.name))
        self.assertEqual(release_record["sha256"], hashlib.sha256(release.read_bytes()).hexdigest())

    def test_status_distinguishes_queue_archive_release_and_not_observed(self) -> None:
        assignments = write_assignments(self.root)
        a = make_release(self.root, "CDH_A09_001_REVIEW.zip", b"a")
        b = make_release(self.root, "CDH_B09_001_REVIEW.zip", b"b")
        make_release(self.root, "CDH_C09_001_REVIEW.zip", b"c")
        flat_queue.enqueue_releases(self.root, [a.name, b.name])
        flat_queue.archive_queue_item(
            self.root,
            b.name,
            hashlib.sha256(b.read_bytes()).hexdigest(),
            "ACK_STATUS",
            True,
        )
        status = handoff_continuity.build_status(
            self.root, assignments, {"E": "READY_FOR_REVIEW"}
        )
        self.assertEqual(status["roles"]["A"]["state"], "PENDING_UPLOAD")
        self.assertEqual(status["roles"]["B"]["state"], "ACKNOWLEDGED_ARCHIVED")
        self.assertEqual(status["roles"]["C"]["state"], "RELEASE_EXISTS_NOT_QUEUED")
        self.assertEqual(status["roles"]["E"]["state"], "READY_FOR_REVIEW")
        self.assertEqual(status["queue"]["pending_count"], 1)

    def test_write_creates_three_atomic_handoff_outputs(self) -> None:
        assignments = write_assignments(self.root)
        result = handoff_continuity.main(
            [
                "--project-root",
                str(self.root),
                "--assignments",
                str(assignments),
                "--role-status",
                "E=IN_PROGRESS",
                "--write",
            ]
        )
        self.assertEqual(result, 0)
        for relative in (
            handoff_continuity.STATUS_PATH,
            handoff_continuity.INVENTORY_PATH,
            handoff_continuity.SUMMARY_PATH,
        ):
            self.assertTrue((self.root / relative).is_file())
        self.assertEqual(list((self.root / "docs/HANDOFF").glob("*.partial")), [])
        status = json.loads((self.root / handoff_continuity.STATUS_PATH).read_text(encoding="utf-8"))
        self.assertEqual(status["roles"]["E"]["state"], "IN_PROGRESS")

    def test_r05_flat_assignment_shape_and_next_review_zip_are_supported(self) -> None:
        assignments = write_flat_assignments(self.root)
        release = make_release(self.root, "CDH_A10_001_REVIEW.zip", b"a10")
        flat_queue.enqueue_releases(self.root, [release.name])
        status = handoff_continuity.build_status(self.root, assignments)
        self.assertEqual(status["assignments_input_shape"], "FLAT_ROLE_MAP")
        self.assertEqual(set(status["roles"]), set("ABCDEFGH"))
        self.assertEqual(status["roles"]["A"]["expected_review"], release.name)
        self.assertEqual(status["roles"]["A"]["state"], "PENDING_UPLOAD")
        self.assertEqual(status["roles"]["H"]["state"], "AUTHORIZED_NOT_OBSERVED")

    def test_r06_nested_assignment_deliverable_is_supported(self) -> None:
        assignments = write_r06_assignments(self.root)
        release = make_release(self.root, "CDH_E_R06_001_REVIEW.zip", b"e-r06")
        flat_queue.enqueue_releases(self.root, [release.name])
        status = handoff_continuity.build_status(self.root, assignments)
        self.assertEqual(status["assignments_input_shape"], "NESTED_ROLES")
        self.assertEqual(status["roles"]["E"]["expected_review"], release.name)
        self.assertEqual(status["roles"]["E"]["state"], "PENDING_UPLOAD")

        revised = make_release(self.root, "CDH_E_R06_002_REVIEW.zip", b"e-r06-revised")
        flat_queue.enqueue_releases(self.root, [revised.name])
        revised_status = handoff_continuity.build_status(
            self.root,
            assignments,
            {"E": "REVISION_2_READY_FOR_REVIEW"},
            {"E": revised.name},
        )
        self.assertEqual(revised_status["roles"]["E"]["expected_review"], revised.name)
        self.assertEqual(revised_status["roles"]["E"]["state"], "REVISION_2_READY_FOR_REVIEW")

    def test_r07_assignments_without_deliverables_remain_visible(self) -> None:
        path = self.root / "input/R07_ASSIGNMENTS.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"roles": {role: {"task_id": f"R07-{role}"} for role in "ABCDEFGH"}}),
            encoding="utf-8",
        )
        status = handoff_continuity.build_status(
            self.root,
            path,
            {"E": "READY_FOR_REVIEW"},
            {"E": "CDH_E_R07_001_REVIEW.zip"},
        )
        self.assertEqual(set(status["roles"]), set("ABCDEFGH"))
        self.assertIsNone(status["roles"]["A"]["expected_review"])
        self.assertEqual(status["roles"]["A"]["state"], "ASSIGNED_INPUT_UNAVAILABLE")
        self.assertEqual(status["roles"]["E"]["expected_review"], "CDH_E_R07_001_REVIEW.zip")
        self.assertEqual(status["roles"]["E"]["state"], "READY_FOR_REVIEW")

    def test_r09_nested_worklines_shape_is_supported(self) -> None:
        path = self.root / "input/R09_ASSIGNMENTS.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"worklines": {role: {"task_id": f"R09-{role}"} for role in "ABCDEFGH"}}),
            encoding="utf-8",
        )
        status = handoff_continuity.build_status(
            self.root,
            path,
            {"E": "READY_FOR_REVIEW"},
            {"E": "CDH_E_R09_001_REVIEW.zip"},
        )
        self.assertEqual(status["assignments_input_shape"], "NESTED_WORKLINES")
        self.assertEqual(set(status["roles"]), set("ABCDEFGH"))
        self.assertEqual(status["roles"]["A"]["state"], "ASSIGNED_INPUT_UNAVAILABLE")
        self.assertEqual(status["roles"]["E"]["state"], "READY_FOR_REVIEW")

    def test_status_only_expected_delivery_override_is_supported(self) -> None:
        parsed = handoff_continuity._expected_overrides(
            ["E=CDH_E_R11_001_STATUS_ONLY.zip"]
        )
        self.assertEqual(parsed, {"E": "CDH_E_R11_001_STATUS_ONLY.zip"})


if __name__ == "__main__":
    unittest.main()
