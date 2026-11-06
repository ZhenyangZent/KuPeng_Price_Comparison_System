from __future__ import annotations

import socket


def probe_loopback() -> dict[str, object]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.settimeout(1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(1)
    try:
        client.connect(("127.0.0.1", port))
        connection, _ = listener.accept()
        connection.close()
        return {"status": "AVAILABLE", "port": port, "error": None}
    except OSError as exc:
        return {"status": "NOT_RUN_ENV_BLOCKED", "port": port, "error": f"{type(exc).__name__}:{getattr(exc, 'winerror', None) or exc.errno}:{exc}"}
    finally:
        client.close()
        listener.close()
