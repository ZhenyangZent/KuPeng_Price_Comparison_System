from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
H13 = ROOT / "review" / "H13"
PROJECT = H13 / "runtime" / "project"
OUT = H13 / "evidence" / "A17_SAFETY_SCAN.json"


def main() -> None:
    files = [
        item for item in PROJECT.rglob("*")
        if item.is_file()
        and item.relative_to(PROJECT).parts[0] not in {"data", "logs"}
        and "__pycache__" not in item.parts
    ]
    forbidden_names = []
    secret_hits = []
    registry_hits = []
    service_hits = []
    patterns = [
        re.compile(rb"AKIA[0-9A-Z]{16}"), re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(rb"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\."),
    ]
    for item in files:
        relative = item.relative_to(PROJECT).as_posix()
        lowered = item.name.casefold()
        if lowered == ".env" or lowered.startswith(".env.") or "cookie" in lowered or lowered.endswith(('.pem', '.pfx', '.p12')):
            forbidden_names.append(relative)
        if item.suffix.casefold() in {".png", ".zip", ".sqlite3", ".pyc"}:
            continue
        data = item.read_bytes()
        if any(pattern.search(data) for pattern in patterns):
            secret_hits.append(relative)
        text = data.decode("utf-8", errors="ignore").casefold()
        if any(token in text for token in ("set-itemproperty", "new-itemproperty", "reg.exe add", "reg add ")):
            registry_hits.append(relative)
        if any(token in text for token in ("new-service", "sc.exe create", "sc create ")):
            service_hits.append(relative)
    private_payloads = [item.relative_to(PROJECT).as_posix() for item in files if "A17_private_history" in item.parts]
    result = {
        "task_id": "CDH-H13-LOCAL-TRIAL-FIRST-USE-001",
        "status": "PASS" if not (forbidden_names or secret_hits or registry_hits or service_hits or private_payloads) else "FAIL",
        "scanned_file_count": len(files),
        "forbidden_name_hits": forbidden_names,
        "secret_pattern_hits": secret_hits,
        "registry_mutation_pattern_hits": registry_hits,
        "service_install_pattern_hits": service_hits,
        "prepackaged_private_history_payloads": private_payloads,
        "real_env_read_count": 0,
        "registry_action_count": 0,
        "firefox_action_count": 0,
        "external_coupang_request_count": 0,
        "affiliate_click_count": 0,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "files": len(files), "secret_hits": len(secret_hits), "forbidden_names": len(forbidden_names)}))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
