from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server


class RecordingHandler(WSGIRequestHandler):
    records: list[dict] = []

    def log_message(self, fmt: str, *args: object) -> None:
        self.records.append({"client": self.client_address[0], "request": self.requestline, "message": fmt % args})


def _load_test_module(backend_root: Path):
    path = backend_root / "tests" / "web" / "price_coupon_v4" / "test_coupon_v4.py"
    spec = importlib.util.spec_from_file_location("g06_b10_fixture", path)
    if spec is None or spec.loader is None: raise RuntimeError("B10 fixture module unavailable")
    module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
    return module


def _http_probe(app, paths: tuple[tuple[str, str], ...]) -> dict:
    server = make_server("127.0.0.1", 0, app, handler_class=RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    base = f"http://127.0.0.1:{server.server_port}"; responses = {}
    try:
        for name, path in paths:
            request = urllib.request.Request(base + path, headers={"Origin": base})
            with urllib.request.urlopen(request, timeout=5) as response:
                responses[name] = {"url": path, "status": response.status, "headers": dict(response.headers.items()), "body": json.loads(response.read())}
    finally:
        server.shutdown(); thread.join(timeout=5); server.server_close()
    return responses


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--backend-root", type=Path, required=True); parser.add_argument("--output", type=Path, required=True); args = parser.parse_args()
    root = args.backend_root.resolve(); output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    module = _load_test_module(root)
    fixture_root = Path(tempfile.mkdtemp(prefix="g06-b10-", dir=output))
    RecordingHandler.records = []
    responses = _http_probe(module.CouponPriceV4App(module.repository(fixture_root)), (("search", "/api/v4/products?q=coupon&page=1&limit=20"), ("detail", "/api/v4/products/series-1")))
    scenario_roots = {name: fixture_root / name for name in ("unknown", "zero", "quantity", "expired", "revoked")}
    for root_path in scenario_roots.values(): root_path.mkdir()
    scenarios = {
        "price_unknown": _http_probe(module.CouponPriceV4App(module.repository(scenario_roots["unknown"], observations=[module.base_observation(base_price_twd=None, stored_confirmed_coupon_price_twd=None)])), (("search", "/api/v4/products"),)),
        "zero_unknown_shipping": _http_probe(module.CouponPriceV4App(module.repository(scenario_roots["zero"], observations=[module.base_observation(base_price_twd=50, discount_twd=50, stored_confirmed_coupon_price_twd=0)])), (("search", "/api/v4/products"),)),
        "quantity_over_one": _http_probe(module.CouponPriceV4App(module.repository(scenario_roots["quantity"], series=[module.base_series(minimum_purchase_quantity=2)], observations=[module.base_observation(base_price_twd=100, discount_twd=50, discount_scope="ORDER_TOTAL", stored_confirmed_coupon_price_twd=75)])), (("search", "/api/v4/products"),)),
        "expired_coupon": _http_probe(module.CouponPriceV4App(module.repository(scenario_roots["expired"], observations=[module.base_observation(valid_until_utc="2026-11-04T23:59:59Z")])), (("detail", "/api/v4/products/series-1"),)),
        "revoked_source": _http_probe(module.CouponPriceV4App(module.repository(scenario_roots["revoked"], revoked="2026-11-05T03:00:00Z")), (("detail", "/api/v4/products/series-1"),)),
    }
    (output / "api_responses.json").write_text(json.dumps(responses, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "api_request_log.json").write_text(json.dumps(RecordingHandler.records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "scenario_responses.json").write_text(json.dumps(scenarios, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    product = responses["detail"]["body"]["product"]; history = responses["detail"]["body"]["history"]
    unknown = scenarios["price_unknown"]["search"]["body"]["items"][0]
    zero = scenarios["zero_unknown_shipping"]["search"]["body"]["items"][0]
    quantity = scenarios["quantity_over_one"]["search"]["body"]["items"][0]
    expired = scenarios["expired_coupon"]["detail"]["body"]
    revoked = scenarios["revoked_source"]["detail"]["body"]
    assertions = {
        "real_wsgi_http_search_200": responses["search"]["status"] == 200,
        "real_wsgi_http_detail_200": responses["detail"]["status"] == 200,
        "coupon_primary_49": product.get("display_price_twd") == 49 and product.get("display_basis") == "CONFIRMED_COUPON",
        "base_preserved_99": product.get("base_price_twd") == 99,
        "dual_history": len(history.get("before_coupon", [])) == 1 and len(history.get("confirmed_after_coupon", [])) == 1,
        "unknown_shipping_not_free_total": product.get("shipping_status") == "UNKNOWN" and product.get("required_total_twd") is None,
        "price_unknown": unknown.get("display_price_twd") is None and unknown.get("display_basis") == "PRICE_UNAVAILABLE",
        "zero_with_unknown_shipping_not_zero_total": zero.get("display_price_twd") == 0 and zero.get("shipping_status") == "UNKNOWN" and zero.get("required_total_twd") is None,
        "quantity_over_one_preserved": quantity.get("minimum_purchase_quantity") == 2 and quantity.get("minimum_item_spend_twd") == 150,
        "expired_coupon_not_current_but_historical": expired["product"].get("display_basis") == "BASE_PRICE" and len(expired["history"].get("confirmed_after_coupon", [])) == 1,
        "revoked_source_suppresses_price_and_history": revoked["product"].get("display_basis") == "PRICE_UNAVAILABLE" and revoked.get("history") == {"before_coupon": [], "confirmed_after_coupon": []},
        "no_wildcard_cors": "Access-Control-Allow-Origin" not in responses["search"]["headers"],
        "loopback_only": all(record["client"] == "127.0.0.1" for record in RecordingHandler.records),
    }
    shutil.rmtree(fixture_root, ignore_errors=True)
    result = {"schema": "CDH-G06-B10-REAL-WSGI-PROBE-1", "base_url_redacted": "http://127.0.0.1:<EPHEMERAL>", "assertions": assertions, "passed": all(assertions.values())}
    (output / "wsgi_probe.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True)); return 0 if result["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
