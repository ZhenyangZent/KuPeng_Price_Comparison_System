from __future__ import annotations

import stat
import zipfile
from pathlib import Path, PurePosixPath

from tools.web_security_d06.targets import normalize_member_name, verify_target


def verify_review_target(path: str | Path, expected_sha256: str):
    """Verify an immutable review ZIP and reject every undeclared regular file."""
    return verify_target(path, expected_sha256=expected_sha256, reject_undeclared=True)


def extract_portable(path: str | Path, destination: str | Path) -> Path:
    """Extract through a virtual portable-name map; never trust host ZIP normalization."""
    destination = Path(destination)
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("PORTABLE_ZIP_CRC_FAILURE")
        seen: dict[str, str] = {}
        members: list[tuple[zipfile.ZipInfo, str]] = []
        for info in archive.infolist():
            raw = info.orig_filename
            normalized = normalize_member_name(raw)
            folded = normalized.casefold()
            if folded in seen:
                raise ValueError(f"PORTABLE_ZIP_CASEFOLD_DUPLICATE:{seen[folded]}:{raw}")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError(f"PORTABLE_ZIP_SYMLINK:{raw}")
            seen[folded] = raw
            members.append((info, normalized))
        destination.mkdir(parents=True, exist_ok=False)
        for info, normalized in members:
            relative = PurePosixPath(normalized.rstrip("/"))
            target = destination.joinpath(*relative.parts)
            if normalized.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))
    return destination
