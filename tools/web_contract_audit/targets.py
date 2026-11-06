from __future__ import annotations

import hashlib
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class TargetIdentity:
    filename: str
    sha256: str
    entries: int
    crc_pass: bool
    safe_paths: bool
    no_symlinks: bool
    no_casefold_duplicates: bool


def _safe(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return bool(normalized) and "\\" not in name and not normalized.startswith("/") and not path.is_absolute() and ".." not in path.parts and not (len(normalized) > 1 and normalized[1] == ":")


def verify_target(path: str | Path, *, expected_sha256: str) -> TargetIdentity:
    target = Path(path)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise ValueError(f"TARGET_SHA256_MISMATCH:{target.name}:{digest}")
    with zipfile.ZipFile(target) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        return TargetIdentity(
            target.name,
            digest,
            len(names),
            archive.testzip() is None,
            all(_safe(name) for name in names),
            not any(stat.S_ISLNK(item.external_attr >> 16) for item in infos),
            len(names) == len({name.casefold() for name in names}),
        )


def read_unique_member(path: str | Path, suffix: str) -> bytes:
    with zipfile.ZipFile(path) as archive:
        matches = [name for name in archive.namelist() if name.replace("\\", "/").endswith(suffix)]
        if len(matches) != 1:
            raise ValueError(f"TARGET_MEMBER_COUNT:{suffix}:{len(matches)}")
        return archive.read(matches[0])
