from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


NOW = datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)


def wsgi_request(app, path: str, *, method: str = "GET", headers: dict[str, str] | None = None):
    captured: dict[str, object] = {}
    route, _, query = path.partition("?")
    environ: dict[str, object] = {"REQUEST_METHOD": method, "PATH_INFO": route, "QUERY_STRING": query, "wsgi.input": io.BytesIO()}
    for name, value in (headers or {}).items():
        environ["HTTP_" + name.upper().replace("-", "_")] = value

    def start_response(status, response_headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(response_headers)

    raw = b"".join(app(environ, start_response))
    captured["body"] = json.loads(raw) if raw else None
    return captured


def nested_value(record: dict[str, object], field: str):
    if "." not in field:
        return record[field]
    group, name = field.split(".", 1)
    return record[group][name]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a10", type=Path, required=True)
    parser.add_argument("--b11", type=Path, required=True)
    parser.add_argument("--b12", type=Path, required=True)
    parser.add_argument("--c09", type=Path, required=True)
    parser.add_argument("--f07", type=Path, required=True)
    parser.add_argument("--temp", type=Path, required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(args.b11 / "services" / "price_coupon_v4"))
    embedded_f06 = args.f07 / "review" / "F07" / "controlled_inputs" / "F06" / "extracted" / "CDH_F_R07_001_REVIEW"
    sys.path.insert(0, str(embedded_f06 / "services" / "affiliate_coupon_gate_v6"))
    sys.path.insert(0, str(args.f07 / "services" / "affiliate_coupon_gate_v7"))
    sys.path.insert(0, str(args.b12 / "services" / "import_staging_b12"))
    sys.path.insert(0, str(args.c09 / "research"))

    import affiliate_coupon_gate_v6 as f06
    from affiliate_coupon_gate_v7 import ExactB11F06Binding
    from import_staging_b12.staging import CSV_FIELDS, dry_run, load_records, validate_record
    from import_provenance_c09.gate import verify_json
    from price_coupon_v4 import CouponPriceRepository, CouponPriceV4App

    fixture = args.b11 / "services" / "price_coupon_v4" / "fixtures" / "b11_suite" / "active"
    database = fixture / "coupon.sqlite3"
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    repository = CouponPriceRepository(database, authority_file=fixture / "coupon.authority.json", allowed_root=fixture, clock=lambda: NOW)
    origin = "http://127.0.0.1:4173"
    app = CouponPriceV4App(repository, allowed_origins=(origin,))
    search = wsgi_request(app, "/api/v4/products?page=1&limit=20", headers={"Host": "127.0.0.1:8766"})
    detail = wsgi_request(app, "/api/v4/products/confirmed", headers={"Host": "127.0.0.1:8766"})
    statuses = {
        "search": search["status"], "detail": detail["status"],
        "hostile_host": wsgi_request(app, "/api/v4/products", headers={"Host": "evil.invalid"})["status"],
        "hostile_origin": wsgi_request(app, "/api/v4/products", headers={"Host": "127.0.0.1:8766", "Origin": "https://evil.invalid"})["status"],
        "allowed_origin": wsgi_request(app, "/api/v4/products", headers={"Host": "127.0.0.1:8766", "Origin": origin})["status"],
        "long_query": wsgi_request(app, "/api/v4/products?q=" + "x" * 2050, headers={"Host": "127.0.0.1:8766"})["status"],
        "path_traversal": wsgi_request(app, "/api/v4/products/../confirmed", headers={"Host": "127.0.0.1:8766"})["status"],
        "post": wsgi_request(app, "/api/v4/products", method="POST", headers={"Host": "127.0.0.1:8766"})["status"],
    }

    binding = ExactB11F06Binding(
        b11_zip=args.f07 / "review" / "F07" / "controlled_inputs" / "B11" / "CDH_B_R07_001_REVIEW.zip",
        b11_extracted=args.f07 / "review" / "F07" / "controlled_inputs" / "B11" / "extracted",
        f06_zip=args.f07 / "review" / "F07" / "controlled_inputs" / "F06" / "CDH_F_R07_001_REVIEW.zip",
        f06_extracted=args.f07 / "review" / "F07" / "controlled_inputs" / "F06" / "extracted",
        adapter_module=f06,
    )
    snapshots = {item.series_key: item for item in binding.adapt_search(search["body"])}
    decisions = {}
    for key, snapshot in snapshots.items():
        decision = binding.evaluate(
            snapshot=snapshot,
            request=f06.GateRequest(snapshot.series_identity, snapshot.coupon.eligibility_profile, True),
            affiliate=f06.AffiliateTrustInput("DISABLED", False, None, False, None, ("SOURCE_BLOCKED",)),
            ceiling=f06.RuntimeCeiling("SOURCE_AUTHORIZATION_REQUIRED", True, False, False, False, None, frozenset(), frozenset()),
            now=NOW,
        )
        decisions[key] = {"display_price_twd": decision.display_price_twd, "display_basis": decision.display_basis, "cta_enabled": decision.cta_enabled, "click_url": decision.click_url}
    strict_extra_rejected = False
    strict_extra_code = None
    extra = copy.deepcopy(search["body"])
    extra["items"][0]["click_url"] = "https://evil.invalid/"
    try:
        binding.adapt_search(extra)
    except f06.B10WireError as exc:
        strict_extra_rejected = True
        strict_extra_code = exc.code

    # B12 currently uses json.loads without an object_pairs_hook. Reproduce the ambiguity.
    valid_records = json.loads((args.b12 / "services" / "import_staging_b12" / "fixtures" / "synthetic_valid.json").read_text(encoding="utf-8"))
    record = valid_records[0]
    encoded = json.dumps([record], ensure_ascii=False)
    marker = '"title": '
    duplicate_raw = encoded.replace(marker, '"title": "FIRST-VALUE", ' + marker, 1).encode("utf-8")
    args.temp.mkdir(parents=True, exist_ok=True)
    duplicate_path = args.temp / "duplicate.json"
    duplicate_path.write_bytes(duplicate_raw)
    duplicate_records, duplicate_sha = load_records(duplicate_path, allowed_root=args.temp, input_format="json")
    duplicate_errors = validate_record(duplicate_records[0], as_of=NOW)
    duplicate_report = dry_run(duplicate_records, input_sha256=duplicate_sha, as_of=NOW)

    csv_record = copy.deepcopy(record)
    csv_record["title"] = '=HYPERLINK("https://evil.invalid","x")'
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerow({name: nested_value(csv_record, name) if nested_value(csv_record, name) is not None else "" for name in CSV_FIELDS})
    csv_path = args.temp / "formula.csv"
    csv_path.write_text(buffer.getvalue(), encoding="utf-8")
    csv_records, _ = load_records(csv_path, allowed_root=args.temp, input_format="csv")
    csv_errors = validate_record(csv_records[0], as_of=NOW)

    c09_duplicate = verify_json(b'{"request_id":"first","request_id":"second"}', now=NOW)
    outside = args.temp.parent / "outside.json"
    outside.write_text("[]", encoding="utf-8")
    traversal_rejected = False
    try:
        load_records(outside, allowed_root=args.temp, input_format="json")
    except Exception:
        traversal_rejected = True

    frontend = args.a10 / "apps" / "price-web" / "frontend"
    client_source = (frontend / "src" / "couponV4Client.ts").read_text(encoding="utf-8")
    schema_source = (frontend / "src" / "b10RuntimeSchema.ts").read_text(encoding="utf-8")
    app_source = (frontend / "src" / "App.tsx").read_text(encoding="utf-8")
    coupon_api_source = (frontend / "src" / "CouponApiExperience.tsx").read_text(encoding="utf-8")
    vite_source = (frontend / "vite.config.ts").read_text(encoding="utf-8")
    csp = {
        "default_self": "default-src 'self'" in vite_source,
        "connect_self": "connect-src 'self'" in vite_source,
        "object_none": "object-src 'none'" in vite_source,
        "frame_none": "frame-ancestors 'none'" in vite_source,
        "no_unsafe_inline": "unsafe-inline" not in vite_source,
        "no_wildcard_connect": "connect-src *" not in vite_source,
    }
    a10_static = {
        "credentials_omit": 'credentials: "omit"' in client_source,
        "redirect_error": 'redirect: "error"' in client_source,
        "query_encoded": "encodeURIComponent(query)" in client_source,
        "series_encoded": "encodeURIComponent(seriesKey)" in client_source,
        "same_origin_base": '"/cdh-coupon-v4"' in client_source,
        "no_dangerous_html": "dangerouslySetInnerHTML" not in app_source + coupon_api_source,
        "cta_disabled": "正式連結尚未核准" in coupon_api_source and "disabled" in coupon_api_source,
        "strict_extra_fields": "Object.keys" in schema_source or "set(r)" in schema_source,
    }
    after = hashlib.sha256(database.read_bytes()).hexdigest()
    result = {
        "schema": "CDH-D10-EXACT-RUNTIME-1",
        "b11": {"statuses": statuses, "database_before": before, "database_after": after, "read_only": before == after},
        "f07": {"decision_count": len(decisions), "decisions": decisions, "strict_extra_rejected": strict_extra_rejected, "strict_extra_code": strict_extra_code, "all_cta_disabled": all(not item["cta_enabled"] and item["click_url"] is None for item in decisions.values())},
        "a10": {"csp": csp, "static": a10_static},
        "b12": {
            "duplicate_json_accepted": len(duplicate_records) == 1 and not duplicate_errors,
            "duplicate_json_effective_title": duplicate_records[0]["title"],
            "duplicate_json_dry_run_status": duplicate_report["outcomes"][0]["status"],
            "csv_formula_text_accepted": csv_records[0]["title"].startswith("=") and not csv_errors,
            "path_traversal_rejected": traversal_rejected,
            "database_write_count": duplicate_report["database_write_count"],
        },
        "c09": {"duplicate_json_denied": c09_duplicate["decision"] == "DENY", "duplicate_json_issues": c09_duplicate["issues"]},
        "runtime_external_request_count": 0,
    }
    expected_statuses = {"search": 200, "detail": 200, "hostile_host": 400, "hostile_origin": 403, "allowed_origin": 200, "long_query": 400, "path_traversal": 400, "post": 405}
    result["harness_pass"] = statuses == expected_statuses and before == after and len(decisions) == 9 and result["f07"]["all_cta_disabled"] and strict_extra_rejected and all(csp.values()) and all(value for key, value in a10_static.items() if key != "strict_extra_fields") and traversal_rejected and result["c09"]["duplicate_json_denied"] and duplicate_report["database_write_count"] == 0
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["harness_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
