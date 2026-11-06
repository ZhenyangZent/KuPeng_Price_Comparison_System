from __future__ import annotations

import hashlib
import importlib
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath


B13_RELEASE_SHA256 = "aa0c1b5e938ac87d7c9a81206e7a2df1e14ea656e3dcba74f59501a76f6a4638"
B12_RELEASE_SHA256 = "8e04bcec4e7dd82778858043064dd9676597edade17c496ab16a9042e68bc364"
C09_RELEASE_SHA256 = "a8367fed73efce99e93941a6475f386def7dfa25de27b0e2889d4fe00b1ed0d7"
B11_RELEASE_SHA256 = "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"


class DependencyError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name and "\x00" not in name


def _is_reparse(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(path.stat(follow_symlinks=False).st_file_attributes & 0x400)
    except (AttributeError, FileNotFoundError, OSError):
        return path.is_symlink()


def safe_file(path: Path, *, allowed_root: Path) -> Path:
    raw_root = allowed_root.absolute()
    raw_path = path.absolute()
    if _is_reparse(raw_root) or not raw_path.is_relative_to(raw_root):
        raise DependencyError("path must be below a non-reparse allowed root")
    current = raw_root
    for part in raw_path.relative_to(raw_root).parts:
        current /= part
        if _is_reparse(current):
            raise DependencyError("path must not traverse a link or reparse point")
    root = raw_root.resolve()
    target = raw_path.resolve()
    if not root.is_dir() or not target.is_file() or not target.is_relative_to(root):
        raise DependencyError("path must resolve to a regular file below allowed root")
    return target


def load_exact_b13(b13_release: Path, *, project_root: Path):
    """Hash-bind the immutable B13 release and its workspace service before reuse."""
    if not b13_release.is_file() or sha256(b13_release) != B13_RELEASE_SHA256:
        raise DependencyError("B13 release SHA-256 mismatch")
    manifest_name = "CDH_B_R09_001_REVIEW/REVIEW_MANIFEST.json"
    source_prefix = "CDH_B_R09_001_REVIEW/services/import_staging_b13/"
    with zipfile.ZipFile(b13_release) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if any(not _safe_member(name) for name in names):
            raise DependencyError("B13 release contains unsafe path")
        if len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}):
            raise DependencyError("B13 release contains duplicate path")
        if any(((item.external_attr >> 16) & 0o170000) == 0o120000 for item in infos):
            raise DependencyError("B13 release contains symlink")
        if archive.testzip() is not None:
            raise DependencyError("B13 release CRC failed")
        manifest_data = archive.read(manifest_name)
        manifest = json.loads(manifest_data)
        declared = {item["path"]: item for item in manifest["payloads"]}
        if set(declared) != set(names) - {manifest_name}:
            raise DependencyError("B13 release manifest path set mismatch")
        source_count = 0
        for name, item in declared.items():
            data = archive.read(name)
            if len(data) != item["bytes"] or _sha256_bytes(data) != item["sha256"]:
                raise DependencyError("B13 release manifest payload mismatch")
            if name.startswith(source_prefix):
                relative = name[len("CDH_B_R09_001_REVIEW/"):]
                workspace = project_root / relative
                if not workspace.is_file() or workspace.read_bytes() != data:
                    raise DependencyError("workspace B13 source differs from exact release")
                source_count += 1
        if source_count == 0:
            raise DependencyError("B13 release contains no preview source")

    module_root = project_root / "services" / "import_staging_b13"
    root_text = str(module_root)
    while root_text in sys.path:
        sys.path.remove(root_text)
    sys.path.insert(0, root_text)
    importlib.invalidate_caches()
    package = importlib.import_module("import_staging_b13")
    package = importlib.reload(package)
    preview = importlib.import_module("import_staging_b13.preview")
    dependencies = importlib.import_module("import_staging_b13.dependencies")
    expected = (module_root / "import_staging_b13" / "__init__.py").resolve()
    if Path(package.__file__).resolve() != expected:
        raise DependencyError("imported B13 API is not the verified workspace module")
    return preview, dependencies, {
        "b13_release_sha256": B13_RELEASE_SHA256,
        "b13_manifest_sha256": _sha256_bytes(manifest_data),
        "b13_source_payload_count": source_count,
        "b13_source_gate": "PASS",
    }
