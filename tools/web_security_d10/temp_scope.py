from __future__ import annotations

import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def scoped_temp(prefix: str):
    base = Path.cwd() / "review" / "D10" / "001" / "runtime_tmp"
    base.mkdir(parents=True, exist_ok=True)
    target = base / f"{prefix}-{uuid.uuid4().hex}"
    target.mkdir(exist_ok=False)
    try:
        yield target.resolve()
    finally:
        shutil.rmtree(target, ignore_errors=False)
