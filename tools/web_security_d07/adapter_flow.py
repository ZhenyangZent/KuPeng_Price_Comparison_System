from __future__ import annotations

from pathlib import Path

from tools.web_security_d06.backend_fixture import build_backend_evidence, parser_cases
from tools.web_security_d06.runtime import run_frontend_parser

from .temp_scope import scoped_temp


def run_exact_a08_b09_002_flow(frontend_zip: str | Path, backend_zip: str | Path) -> dict[str, object]:
    with scoped_temp("adapter") as root:
        backend = build_backend_evidence(root, backend_zip)
        parser = run_frontend_parser(frontend_zip, parser_cases(backend))
    daily = backend["bundles"]["daily_median"]
    history = daily["detail"]["history"]
    raw_prices = [item["price_twd"] for item in history]
    return {
        "parser_call_count": len(parser),
        "parser_success_count": sum(bool(item["success"]) for item in parser),
        "parser_failure_count": sum(not bool(item["success"]) for item in parser),
        "parser_results": parser,
        "v2_raw_history_prices": raw_prices,
        "v2_raw_min_twd": min(raw_prices) if raw_prices else None,
        "v2_reported_min_twd": daily["detail"]["observation_period_min_twd"],
        "v3_daily_representative_low_twd": daily["quality"]["period_low_twd"],
        "synthetic_v2_detail": backend["bundles"]["valid"]["detail"],
    }
