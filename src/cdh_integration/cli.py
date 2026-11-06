from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from cdh_core.persistence import MockSink

from .pipeline import SyntheticIntegrationPipeline


def _clock(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--now must be timezone-aware")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="CDH I01 synthetic-only integration demo")
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--candidate-db", required=True, type=Path)
    parser.add_argument("--event-db", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--now", required=True)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    now = _clock(args.now)
    pipeline = SyntheticIntegrationPipeline(
        candidate_database=args.candidate_db,
        event_database=args.event_db,
        clock=lambda: now,
    )
    results: list[dict[str, object]] = []
    for case in cases:
        result = pipeline.process(case["observation"], case.get("qualification_fixture"))
        rendered = {"case_id": case["case_id"], **result.as_dict()}
        if result.event_id is not None and case.get("deliver", False):
            sink = MockSink()
            status = pipeline.deliver(result.event_id, sink, now=now)
            rendered["delivery_status"] = status
            rendered["mock_sink_delivery_count"] = len(sink.deliveries)
        results.append(rendered)
    output = {
        "task_id": "CDH-I01-SYNTHETIC-INTEGRATION-001",
        "scope": "SYNTHETIC_ONLY",
        "now": now.isoformat(),
        "candidate_count": pipeline.ledger.count(),
        "event_store_counts": pipeline.events.counts(),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
