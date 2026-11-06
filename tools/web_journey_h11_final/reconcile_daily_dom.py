from __future__ import annotations

import html
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "review" / "H11_FINAL" / "evidence"
OUT = EVIDENCE / "DAILY_DOM_RECONCILIATION.json"
FILES = {
    "CSV": EVIDENCE / "dom" / "11-csv-history.html",
    "JSON": EVIDENCE / "dom" / "12-json-history.html",
}
EXPECTED = {
    "before_coupon": [("2026-11-03", 1, 1000), ("2026-11-04", 1, 950)],
    "confirmed_after_coupon": [],
    "user_reported_after_coupon": [("2026-11-03", 1, 900)],
}
SECTION = r'<section[^>]*data-private-history-basis="{basis}"[^>]*>(.*?)</section>'
ROW = re.compile(r'<div class="history-row" data-taipei-date="([^"]+)" data-sample-count="([0-9]+)">.*?<strong>(.*?)</strong>', re.S)
TWD = re.compile(r"^NT\$\s*(0|[1-9]\d*|[1-9]\d{0,2}(?:,\d{3})+)$")


def parse_twd(value: str) -> int | None:
    clean = html.unescape(re.sub(r"<[^>]+>", "", value)).strip()
    match = TWD.fullmatch(clean)
    return int(match.group(1).replace(",", "")) if match else None


def extract(document: str, basis: str) -> list[tuple[str, int, int | None]]:
    match = re.search(SECTION.format(basis=re.escape(basis)), document, re.S)
    if not match:
        raise RuntimeError(f"missing private history basis: {basis}")
    return [(date, int(samples), parse_twd(price)) for date, samples, price in ROW.findall(match.group(1))]


def main() -> None:
    documents = {label: path.read_text(encoding="utf-8") for label, path in FILES.items()}
    parsed = {label: {basis: extract(document, basis) for basis in EXPECTED} for label, document in documents.items()}
    gates = {
        f"{label.lower()}_{basis}": values == EXPECTED[basis]
        for label, tracks in parsed.items()
        for basis, values in tracks.items()
    }
    result = {
        "task_id": "H11",
        "revision": "FINAL_OFFICIAL_LAUNCHER",
        "source": "ACTUAL_CHROME_CAPTURED_DOM",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "parser": "STRICT_ANCHORED_TWD_FULLMATCH",
        "parsed": {label: {basis: [list(item) for item in values] for basis, values in tracks.items()} for label, tracks in parsed.items()},
        "gates": gates,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
