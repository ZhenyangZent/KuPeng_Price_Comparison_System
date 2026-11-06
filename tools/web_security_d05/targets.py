from __future__ import annotations

import hashlib
import stat
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class TargetIdentity:
    filename: str
    sha256: str
    bytes: int
    entries: int
    crc_pass: bool
    safe_paths: bool
    no_symlinks: bool
    no_casefold_duplicates: bool

    def as_dict(self) -> dict[str, str | int | bool]:
        return asdict(self)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_member_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return (
        bool(normalized)
        and "\\" not in name
        and not normalized.startswith("/")
        and not path.is_absolute()
        and ".." not in path.parts
        and not (len(normalized) > 1 and normalized[1] == ":")
    )


def verify_target(path: str | Path, *, expected_sha256: str) -> TargetIdentity:
    target = Path(path)
    digest = sha256_file(target)
    if digest != expected_sha256:
        raise ValueError(f"TARGET_SHA256_MISMATCH:{target.name}:{digest}")
    with zipfile.ZipFile(target) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        result = TargetIdentity(
            filename=target.name,
            sha256=digest,
            bytes=target.stat().st_size,
            entries=len(names),
            crc_pass=archive.testzip() is None,
            safe_paths=all(safe_member_name(name) for name in names),
            no_symlinks=not any(stat.S_ISLNK(item.external_attr >> 16) for item in infos),
            no_casefold_duplicates=len(names) == len({name.casefold() for name in names}),
        )
    if not all((result.crc_pass, result.safe_paths, result.no_symlinks, result.no_casefold_duplicates)):
        raise ValueError(f"TARGET_ZIP_SAFETY_FAILURE:{target.name}")
    return result


def read_unique_member(path: str | Path, suffix: str) -> bytes:
    with zipfile.ZipFile(path) as archive:
        matches = [name for name in archive.namelist() if name.replace("\\", "/").endswith(suffix)]
        if len(matches) != 1:
            raise ValueError(f"TARGET_MEMBER_COUNT:{suffix}:{len(matches)}")
        return archive.read(matches[0])
