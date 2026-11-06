from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
B01 = ROOT / "experiments" / "B01"
sys.path.insert(0, str(B01 / "registry"))
sys.path.insert(0, str(B01 / "native_host"))

from protocol import encode_frame, read_frame  # noqa: E402
from registry_model import (  # noqa: E402
    KeyState,
    RegistryTransactionError,
    install_absent_key,
    rollback_owned_key,
)
from runtime_identity import (  # noqa: E402
    RuntimeIdentityError,
    select_runtime,
    sha256_file,
    validate_pinned_runtime,
)


MANIFEST = str((B01 / "native_host" / "com.coupang_deal_hunter.b01_poc.json").resolve())
HASH = "a" * 64
NONCE = "0123456789abcdef0123456789abcdef"


def install() -> tuple[KeyState, object]:
    return install_absent_key(
        None,
        manifest_path=MANIFEST,
        manifest_sha256=HASH,
        ownership_nonce=NONCE,
    )


class RegistryTransactionModelTests(unittest.TestCase):
    def test_38_absent_key_installs_owned_exact_state(self) -> None:
        state, receipt = install()
        self.assertEqual(state.default_value, MANIFEST)
        self.assertEqual(state.named_values, {"_CDH_B01_OWNERSHIP": NONCE})
        self.assertEqual(receipt.install_state, "INSTALLED")

    def test_39_preexisting_key_is_refused_without_mutation(self) -> None:
        existing = KeyState(default_value="other.json", named_values={"other": "keep"})
        with self.assertRaisesRegex(RegistryTransactionError, "HOST_ALREADY_EXISTS_REFUSE_OVERWRITE"):
            install_absent_key(existing, manifest_path=MANIFEST, manifest_sha256=HASH, ownership_nonce=NONCE)
        self.assertEqual(existing.named_values, {"other": "keep"})

    def test_40_preexisting_empty_key_is_also_refused(self) -> None:
        with self.assertRaisesRegex(RegistryTransactionError, "HOST_ALREADY_EXISTS_REFUSE_OVERWRITE"):
            install_absent_key(KeyState(), manifest_path=MANIFEST, manifest_sha256=HASH, ownership_nonce=NONCE)

    def test_41_exact_owned_state_can_rollback_to_absent(self) -> None:
        state, receipt = install()
        self.assertIsNone(rollback_owned_key(state, receipt, current_manifest_sha256=HASH))

    def test_42_extra_value_or_subkey_causes_rollback_conflict(self) -> None:
        state, receipt = install()
        extra_value = replace(state, named_values={**state.named_values, "external": "keep"})
        extra_subkey = replace(state, subkeys=("external",))
        for changed in (extra_value, extra_subkey):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(RegistryTransactionError, "ROLLBACK_CONFLICT"):
                    rollback_owned_key(changed, receipt, current_manifest_sha256=HASH)

    def test_43_changed_default_or_nonce_causes_rollback_conflict(self) -> None:
        state, receipt = install()
        changed_default = replace(state, default_value="external.json")
        changed_nonce = replace(state, named_values={"_CDH_B01_OWNERSHIP": "external"})
        for changed in (changed_default, changed_nonce):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(RegistryTransactionError, "ROLLBACK_CONFLICT"):
                    rollback_owned_key(changed, receipt, current_manifest_sha256=HASH)

    def test_44_duplicate_rollback_is_not_treated_as_success(self) -> None:
        _, receipt = install()
        with self.assertRaisesRegex(RegistryTransactionError, "ROLLBACK_ALREADY_APPLIED"):
            rollback_owned_key(None, receipt, current_manifest_sha256=HASH)

    def test_45_forged_snapshot_identity_is_rejected(self) -> None:
        state, receipt = install()
        forged = replace(receipt, registry_subkey=r"SOFTWARE\Unrelated", ownership_nonce="forged")
        with self.assertRaisesRegex(RegistryTransactionError, "SNAPSHOT_IDENTITY_REJECTED"):
            rollback_owned_key(state, forged, current_manifest_sha256=HASH)

    def test_46_manifest_hash_change_causes_rollback_conflict(self) -> None:
        state, receipt = install()
        with self.assertRaisesRegex(RegistryTransactionError, "ROLLBACK_CONFLICT"):
            rollback_owned_key(state, receipt, current_manifest_sha256="b" * 64)


class PinnedRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.python_path = Path(sys.executable).resolve()
        cls.python_hash = sha256_file(cls.python_path)

    def test_47_valid_absolute_pinned_runtime_is_accepted(self) -> None:
        self.assertEqual(validate_pinned_runtime(str(self.python_path), self.python_hash), self.python_path)

    def test_48_path_precedence_cannot_change_selected_runtime(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": str(ROOT / "malicious-path")}, clear=False):
            self.assertEqual(select_runtime(str(self.python_path), self.python_hash), self.python_path)

    def test_49_missing_or_relative_runtime_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeIdentityError, "PINNED_RUNTIME_MISSING"):
            validate_pinned_runtime(str(ROOT / "missing-python.exe"), self.python_hash)
        with self.assertRaisesRegex(RuntimeIdentityError, "PINNED_RUNTIME_PATH_NOT_ABSOLUTE"):
            validate_pinned_runtime("python.exe", self.python_hash)

    def test_50_hash_or_version_mismatch_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeIdentityError, "PINNED_RUNTIME_HASH_MISMATCH"):
            validate_pinned_runtime(str(self.python_path), "0" * 64)
        with self.assertRaisesRegex(RuntimeIdentityError, "PINNED_RUNTIME_VERSION_UNSUPPORTED"):
            validate_pinned_runtime(str(self.python_path), self.python_hash, observed_version=(3, 10))

    def test_51_compiled_launcher_ignores_malicious_path_python(self) -> None:
        launcher = B01 / "native_host" / "native_host_launcher.exe"
        self.assertTrue(launcher.is_file())
        temp_parent = ROOT / "review" / "B01" / "R01" / "tmp"
        temp_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_parent) as directory:
            fake = Path(directory) / "python.exe"
            fake.write_bytes(b"not an executable")
            request = {
                "protocol_version": "1.0",
                "message_id": "pinned-path-test",
                "type": "PING",
                "payload": {},
            }
            completed = subprocess.run(
                [str(launcher)],
                input=encode_frame(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "PATH": directory},
                timeout=10,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", "replace"))
        self.assertEqual(read_frame(io.BytesIO(completed.stdout))["payload"]["reply"], "PONG")


class StaticBoundaryTests(unittest.TestCase):
    def test_52_registry_scripts_use_exact_non_tree_rollback(self) -> None:
        install_text = (B01 / "registry" / "Install-NativeHost.ps1").read_text(encoding="utf-8")
        restore_text = (B01 / "registry" / "Restore-RegistrySnapshot.ps1").read_text(encoding="utf-8")
        self.assertIn("CreateExclusiveAndSetValues", install_text)
        self.assertIn("HOST_ALREADY_EXISTS_REFUSE_OVERWRITE", install_text)
        self.assertIn("GetValueNames", restore_text)
        self.assertIn("GetSubKeyNames", restore_text)
        self.assertIn("DeleteValue('', $true)", restore_text)
        self.assertNotIn("DeleteSubKey(", restore_text)
        self.assertNotIn("DeleteSubKeyTree", restore_text)

    def test_53_launcher_contains_no_path_or_shell_fallback(self) -> None:
        source = (B01 / "native_host" / "native_host_launcher.c").read_text(encoding="utf-8")
        self.assertNotIn("SearchPathW", source)
        self.assertNotIn("cmd.exe", source)
        self.assertIn("CDH_PYTHON_SHA256", source)
        self.assertIn("constant_time_equal", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
