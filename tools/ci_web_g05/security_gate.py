from __future__ import annotations

import re
from pathlib import Path


SECRET = re.compile(r"AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
TOKEN_URL = re.compile(r"https?://[^\s'\"]+[?&](?:token|api_key|secret|password)=[^\s'\"]+", re.I)
REQUIRED_HEADERS = ("Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy")


def inspect(frontend: Path, backend: Path) -> dict:
    index = (frontend / "index.html").read_text(encoding="utf-8")
    csp = "content-security-policy" in index.casefold()
    api_candidates = sorted(backend.rglob("api.py"))
    api_text = "\n".join(path.read_text(encoding="utf-8") for path in api_candidates)
    headers = {name: name.casefold() in api_text.casefold() for name in REQUIRED_HEADERS}
    secret_findings, token_urls = [], []
    for root in (frontend / "src", backend / "services"):
        if not root.exists(): continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.casefold() not in {".ts", ".tsx", ".js", ".mjs", ".py"}: continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if SECRET.search(text): secret_findings.append(path.name)
            if TOKEN_URL.search(text): token_urls.append(path.name)
    return {
        "csp_present": csp, "backend_headers": headers,
        "url_token_leak_count": len(token_urls), "secret_finding_count": len(secret_findings),
        "csp_gate": "PASS" if csp else "FAIL",
        "backend_header_gate": "PASS" if all(headers.values()) else "FAIL",
        "url_leak_gate": "PASS" if not token_urls and not secret_findings else "FAIL",
    }
