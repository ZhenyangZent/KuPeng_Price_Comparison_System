from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class G09SafetyTests(unittest.TestCase):
    def test_browser_uses_four_exact_visible_dom_selectors(self):
        text = (ROOT / "tools/ci_web_g09/browser_probe.mjs").read_text(encoding="utf-8")
        for value in ("B10 券前商品價歷史", "B10 已確認券後商品價歷史", "B11 券前每日代表價", "B11 已確認券後每日代表價", "exact_daily_dom_selectors_visible"):
            self.assertIn(value, text)

    def test_browser_requires_daily_values_counts_and_empty_state(self):
        text = (ROOT / "tools/ci_web_g09/browser_probe.mjs").read_text(encoding="utf-8")
        for value in ("daily_before_visible_99", "daily_after_visible_49", "dom_counts_match_wire", "empty_history_visible_and_not_filled", "不以券前價補值"):
            self.assertIn(value, text)

    def test_missing_b14_c11_stays_not_run(self):
        text = (ROOT / "tools/ci_web_g09/runner.py").read_text(encoding="utf-8")
        self.assertIn('"b14_c11_safe_import_preview", "status": "NOT_RUN_INPUT_UNAVAILABLE"', text)
        self.assertIn('"database_write_count": 0', text)


if __name__ == "__main__": unittest.main()
