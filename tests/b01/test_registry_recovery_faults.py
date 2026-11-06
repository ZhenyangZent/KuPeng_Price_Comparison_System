from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
B01 = ROOT / "experiments" / "B01"
sys.path.insert(0, str(B01 / "registry"))

from registry_model import (  # noqa: E402
    OWNERSHIP_VALUE,
    InstallPoint,
    KeyState,
    RegistryTransactionError,
    recover_or_disable_owned_key,
    simulate_install,
)


MANIFEST = str((B01 / "native_host" / "com.coupang_deal_hunter.b01_poc.json").resolve())
HASH = "a" * 64
NONCE = "0123456789abcdef0123456789abcdef"


def simulate(point: InstallPoint):
    return simulate_install(
        None,
        manifest_path=MANIFEST,
        manifest_sha256=HASH,
        ownership_nonce=NONCE,
        stop_after=point,
    )


class RegistryFaultInjectionTests(unittest.TestCase):
    def test_54_every_install_transition_has_deterministic_fault_state(self) -> None:
        expected = {
            InstallPoint.RECEIPT_PENDING: None,
            InstallPoint.KEY_CREATED: KeyState(),
            InstallPoint.OWNER_WRITTEN: KeyState(named_values={OWNERSHIP_VALUE: NONCE}),
            InstallPoint.DEFAULT_WRITTEN: KeyState(
                default_value=MANIFEST,
                named_values={OWNERSHIP_VALUE: NONCE},
            ),
            InstallPoint.RECEIPT_INSTALLED: KeyState(
                default_value=MANIFEST,
                named_values={OWNERSHIP_VALUE: NONCE},
            ),
        }
        for point, state in expected.items():
            with self.subTest(point=point):
                result = simulate(point)
                self.assertEqual(result.current, state)
                self.assertEqual(result.interrupted, point != InstallPoint.RECEIPT_INSTALLED)

    def test_55_existing_foreign_key_is_never_modified(self) -> None:
        existing = KeyState(default_value="foreign.json", named_values={"keep": "yes"}, subkeys=("child",))
        with self.assertRaisesRegex(RegistryTransactionError, "HOST_ALREADY_EXISTS_REFUSE_OVERWRITE"):
            simulate_install(
                existing,
                manifest_path=MANIFEST,
                manifest_sha256=HASH,
                ownership_nonce=NONCE,
                stop_after=InstallPoint.RECEIPT_INSTALLED,
            )
        self.assertEqual(existing.named_values, {"keep": "yes"})

    def test_56_empty_partial_key_requires_manual_review_without_delete(self) -> None:
        partial = simulate(InstallPoint.KEY_CREATED)
        recovered = recover_or_disable_owned_key(partial.current, partial.receipt, current_manifest_sha256=HASH)
        self.assertEqual(recovered.status, "PARTIAL_STATE_MANUAL_REVIEW")
        self.assertEqual(recovered.current, KeyState())
        self.assertEqual(recovered.automatic_key_delete_count, 0)

    def test_57_owner_only_partial_install_is_retryable_and_retained(self) -> None:
        partial = simulate(InstallPoint.OWNER_WRITTEN)
        recovered = recover_or_disable_owned_key(partial.current, partial.receipt, current_manifest_sha256=HASH)
        self.assertEqual(recovered.status, "ROLLBACK_DEFAULT_REMOVED_MANUAL_KEY_CLEANUP")
        self.assertEqual(recovered.current, partial.current)
        self.assertEqual(recovered.automatic_owner_delete_count, 0)
        self.assertEqual(recovered.automatic_key_delete_count, 0)

    def test_58_pending_exact_install_removes_only_owned_default(self) -> None:
        partial = simulate(InstallPoint.DEFAULT_WRITTEN)
        recovered = recover_or_disable_owned_key(partial.current, partial.receipt, current_manifest_sha256=HASH)
        self.assertEqual(recovered.automatic_default_delete_count, 1)
        self.assertIsNone(recovered.current.default_value)
        self.assertEqual(recovered.current.named_values, {OWNERSHIP_VALUE: NONCE})
        self.assertTrue(recovered.manual_review_required)

    def test_59_interruption_after_default_delete_keeps_retry_proof(self) -> None:
        installed = simulate(InstallPoint.RECEIPT_INSTALLED)
        interrupted = recover_or_disable_owned_key(
            installed.current,
            installed.receipt,
            current_manifest_sha256=HASH,
            inject_after_default_delete=True,
        )
        self.assertEqual(interrupted.status, "INTERRUPTED_AFTER_DEFAULT_DELETE")
        self.assertEqual(interrupted.current.named_values, {OWNERSHIP_VALUE: NONCE})
        retried = recover_or_disable_owned_key(
            interrupted.current,
            interrupted.receipt,
            current_manifest_sha256=HASH,
        )
        self.assertEqual(retried.status, "ROLLBACK_DEFAULT_REMOVED_MANUAL_KEY_CLEANUP")
        self.assertEqual(retried.automatic_default_delete_count, 0)

    def test_60_default_without_owner_is_preserved_for_manual_review(self) -> None:
        receipt = simulate(InstallPoint.RECEIPT_PENDING).receipt
        foreign = KeyState(default_value=MANIFEST)
        recovered = recover_or_disable_owned_key(foreign, receipt, current_manifest_sha256=HASH)
        self.assertEqual(recovered.status, "PARTIAL_STATE_MANUAL_REVIEW")
        self.assertEqual(recovered.current.default_value, MANIFEST)
        self.assertEqual(recovered.automatic_default_delete_count, 0)

    def test_61_foreign_value_or_subkey_is_never_deleted(self) -> None:
        installed = simulate(InstallPoint.RECEIPT_INSTALLED)
        cases = (
            replace(installed.current, named_values={OWNERSHIP_VALUE: NONCE, "foreign": "keep"}),
            replace(installed.current, subkeys=("foreign-child",)),
        )
        for state in cases:
            with self.subTest(state=state):
                recovered = recover_or_disable_owned_key(state, installed.receipt, current_manifest_sha256=HASH)
                self.assertEqual(recovered.status, "PARTIAL_STATE_MANUAL_REVIEW")
                self.assertEqual(recovered.current, state)
                self.assertEqual(recovered.automatic_key_delete_count, 0)

    def test_62_changed_ownership_nonce_is_preserved_for_review(self) -> None:
        installed = simulate(InstallPoint.RECEIPT_INSTALLED)
        changed = replace(installed.current, named_values={OWNERSHIP_VALUE: "foreign"})
        recovered = recover_or_disable_owned_key(changed, installed.receipt, current_manifest_sha256=HASH)
        self.assertEqual(recovered.status, "PARTIAL_STATE_MANUAL_REVIEW")
        self.assertEqual(recovered.current, changed)

    def test_63_manifest_hash_mismatch_performs_no_delete(self) -> None:
        installed = simulate(InstallPoint.RECEIPT_INSTALLED)
        recovered = recover_or_disable_owned_key(installed.current, installed.receipt, current_manifest_sha256="b" * 64)
        self.assertEqual(recovered.status, "PARTIAL_STATE_MANUAL_REVIEW")
        self.assertEqual(recovered.current, installed.current)
        self.assertEqual(recovered.automatic_default_delete_count, 0)

    def test_64_absent_key_recovery_is_idempotent_no_action(self) -> None:
        receipt = simulate(InstallPoint.RECEIPT_PENDING).receipt
        first = recover_or_disable_owned_key(None, receipt, current_manifest_sha256=HASH)
        second = recover_or_disable_owned_key(None, first.receipt, current_manifest_sha256=HASH)
        self.assertEqual(first.status, "ROLLBACK_KEY_ABSENT_NO_ACTION")
        self.assertEqual(first, second)

    def test_65_terminal_absent_receipt_rejects_reappeared_key_without_delete(self) -> None:
        installed = simulate(InstallPoint.RECEIPT_INSTALLED)
        absent = recover_or_disable_owned_key(None, installed.receipt, current_manifest_sha256=HASH)
        reappeared = recover_or_disable_owned_key(
            installed.current,
            absent.receipt,
            current_manifest_sha256=HASH,
        )
        self.assertEqual(reappeared.status, "PARTIAL_STATE_MANUAL_REVIEW")
        self.assertEqual(reappeared.current, installed.current)
        self.assertEqual(reappeared.automatic_default_delete_count, 0)
        self.assertEqual(reappeared.automatic_owner_delete_count, 0)
        self.assertEqual(reappeared.automatic_key_delete_count, 0)

    def test_66_restore_accepts_absent_terminal_state_and_never_automatic_key_delete(self) -> None:
        restore = (B01 / "registry" / "Restore-RegistrySnapshot.ps1").read_text(encoding="utf-8")
        self.assertIn("'ROLLBACK_KEY_ABSENT_NO_ACTION'", restore)
        self.assertIn("Terminal absent-key receipt conflicts with a reappeared target key", restore)
        self.assertIn("DeleteValue('', $true)", restore)
        self.assertNotIn("DeleteValue($null", restore)
        self.assertNotIn("DeleteSubKey(", restore)
        self.assertNotIn("DeleteSubKeyTree", restore)
        self.assertIn("PARTIAL_STATE_MANUAL_REVIEW", restore)

    def test_67_install_persists_interruption_diagnostic_without_cleanup(self) -> None:
        install = (B01 / "registry" / "Install-NativeHost.ps1").read_text(encoding="utf-8")
        common = (B01 / "registry" / "Common.ps1").read_text(encoding="utf-8")
        self.assertIn("INSTALL_INTERRUPTED_RECOVERY_REQUIRED", install)
        self.assertIn("Write-B01Receipt", install)
        self.assertIn("Preserve partial state", common)
        self.assertNotIn("DeleteSubKey", common.split("CreateExclusiveAndSetValues", 1)[1])

    def test_68_phase_b_receipt_is_task_bound_and_does_not_write_r02(self) -> None:
        install = (B01 / "registry" / "Install-NativeHost.ps1").read_text(encoding="utf-8")
        restore = (B01 / "registry" / "Restore-RegistrySnapshot.ps1").read_text(encoding="utf-8")
        model = (B01 / "registry" / "registry_model.py").read_text(encoding="utf-8")
        task_id = "CDH-B01-PHASE-B-WINDOWS-E2E-001"
        self.assertIn(r"review\B01\PHASE_B_001\registry_snapshots", install)
        self.assertNotIn(r"review\B01\R02\registry_snapshots", install)
        self.assertIn(task_id, install)
        self.assertIn(task_id, restore)
        self.assertIn(task_id, model)


if __name__ == "__main__":
    unittest.main(verbosity=2)
