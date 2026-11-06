from __future__ import annotations

import hashlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class A16FirstUseTests(unittest.TestCase):
    def test_exact_frozen_inputs_exist(self) -> None:
        expected = {
            "CDH_A_R12_002_REVIEW.zip": "be0becbaa384e1a633c5893b266dbbb03c449ca405ef1f0c07bb8dd53456634b",
            "CDH_B_R12_003_REVIEW.zip": "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7",
            "CDH_D_R12_003_REVIEW.zip": "8aef750caa17c894159d13705f9962e4f6e856ef3ced1658ddb951523b241e54",
            "CDH_H_R12_002_REVIEW.zip": "725232938d0f9111b0546b02a9e34a7a86015ebe1205452656e8fd586f365f1e",
        }
        for name, expected_hash in expected.items():
            path = ROOT / "review" / "releases" / name
            self.assertTrue(path.is_file(), name)
            self.assertEqual(sha256(path), expected_hash, name)

    def test_root_entry_points_delegate_to_scoped_powershell(self) -> None:
        for action in ("Start", "Stop", "Status"):
            wrapper = (ROOT / f"{action}-CDH-MVP.cmd").read_text(encoding="utf-8")
            self.assertIn(f"scripts\\windows-mvp\\{action}-CDH-MVP.ps1", wrapper)
        start = (ROOT / "scripts" / "windows-mvp" / "Start-CDH-MVP.ps1").read_text(encoding="utf-8")
        self.assertIn("Test-CDHMvpInputs", start)
        self.assertIn("data\\private_user_observations_b15", start)
        self.assertIn("does not open a browser or contact Coupang", start)

    def test_launcher_has_no_system_mutation_or_browser_auto_open(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((ROOT / "scripts" / "windows-mvp").glob("*.ps1"))
        ).casefold()
        forbidden = (
            "set-itemproperty",
            "new-itemproperty",
            "remove-itemproperty",
            "reg.exe",
            "start-service",
            "new-service",
            "set-netfirewallrule",
            "start-process http",
            "invoke-expression",
        )
        for token in forbidden:
            self.assertNotIn(token, combined)

    def test_guide_covers_first_use_and_safety_boundaries(self) -> None:
        guide = (ROOT / "docs" / "user-guides" / "WINDOWS_LOCAL_MVP_FIRST_USE.md").read_text(encoding="utf-8")
        for required in (
            "Python 3.11",
            "http://127.0.0.1:4174/?mode=synthetic&contract=v4",
            "手動記錄一筆價格",
            "CSV／JSON 批次匯入",
            "查詢已儲存的私人歷史",
            "SYNTHETIC DEMO",
            "PRIVATE USER-REPORTED",
            "PLATFORM CONFIRMED",
            "正式推薦／分潤按鈕仍停用",
            "不會自動安裝套件",
        ):
            self.assertIn(required, guide)

    def test_narrow_layout_collapses_history_and_wraps_prices(self) -> None:
        css = (ROOT / "apps" / "price-web" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".history-row, .coupon-history-row, .daily-history-row", css)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", css)
        self.assertIn(".price-block strong, .product-price", css)
        self.assertIn("overflow-wrap: anywhere", css)


if __name__ == "__main__":
    unittest.main()
