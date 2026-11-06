from __future__ import annotations

import importlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Callable

from .constants import EXCHANGE_VERSION, RECEIPT_VERSION, SOURCE_AUTHORITY_STATUS, project_root
from .exchange import DuplicateSubmissionError, build_submission, safe_write_submission
from .receipt import SyncStatus, receipt_status
from .schema import ValidationError, validate_submission


SAMPLE_IDS = (
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
)
SAMPLE_PRICES = (0, 7)


class PreviewError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class D02Bindings:
    sync_module: ModuleType
    database_module: ModuleType

    @property
    def SyncPaths(self):
        return self.sync_module.SyncPaths

    def run_sync(self, paths, *, dry_run: bool):
        return self.sync_module.run_sync(paths, dry_run=dry_run)

    def initialize_database(self, path: Path) -> None:
        connection = self.database_module.connect(path)
        try:
            self.database_module.migrate(connection)
        finally:
            connection.close()


@dataclass(frozen=True)
class PreviewResult:
    state: str
    detail: str
    mode: str
    workspace: str
    imported_count: int | None
    pending_count: int | None
    quarantined_count: int | None
    retry_count: int | None
    scanned_count: int
    receipt_published: bool


def default_i02_workspace() -> Path:
    return project_root() / "experiments" / "I02" / "synthetic_preview"


def _module_under(module: ModuleType, expected: Path) -> bool:
    origin = Path(str(getattr(module, "__file__", ""))).resolve()
    try:
        origin.relative_to(expected.resolve())
        return True
    except ValueError:
        return False


def load_frozen_d02(root: Path) -> D02Bindings:
    d02_root = (root / "apps" / "d01").resolve()
    if not (d02_root / "cdh_d01" / "sync.py").is_file():
        raise PreviewError("D02_UNAVAILABLE", "找不到專案內已驗收的 D02 sync 模組")
    root_text = str(d02_root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    try:
        sync_module = importlib.import_module("cdh_d01.sync")
        database_module = importlib.import_module("cdh_d01.database")
    except (ImportError, ModuleNotFoundError) as exc:
        raise PreviewError("D02_DEPENDENCY_MISSING", str(exc)) from exc
    if not _module_under(sync_module, d02_root) or not _module_under(database_module, d02_root):
        raise PreviewError("D02_IDENTITY_MISMATCH", "載入的 D02 模組不位於固定專案路徑")
    expected = {
        "RECEIPT_VERSION": RECEIPT_VERSION,
        "EXCHANGE_VERSION": EXCHANGE_VERSION,
        "SOURCE_STATUS": SOURCE_AUTHORITY_STATUS,
    }
    for name, value in expected.items():
        if getattr(sync_module, name, None) != value:
            raise PreviewError("D02_VERSION_MISMATCH", f"{name} 不相容")
    if not hasattr(sync_module, "run_sync") or not hasattr(sync_module, "SyncPaths"):
        raise PreviewError("D02_INTERFACE_MISMATCH", "缺少 run_sync 或 SyncPaths")
    return D02Bindings(sync_module, database_module)


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


class SyntheticSyncPreview:
    def __init__(
        self,
        *,
        root: Path | None = None,
        workspace: Path | None = None,
        binding_loader: Callable[[Path], D02Bindings] = load_frozen_d02,
    ) -> None:
        self.root = (root or project_root()).resolve()
        self.allowed_root = (self.root / "experiments" / "I02").resolve()
        self.workspace = (workspace or self.allowed_root / "synthetic_preview").resolve()
        if not _inside(self.workspace, self.allowed_root) or self.workspace == self.allowed_root:
            raise PreviewError("WORKSPACE_NOT_ISOLATED", "I02 workspace 必須位於 experiments/I02 的專用子目錄")
        production_paths = {
            (self.root / "data").resolve(),
            (self.root / "data" / "d01").resolve(),
            (self.root / "data" / "exchange").resolve(),
        }
        if self.workspace in production_paths:
            raise PreviewError("PRODUCTION_PATH_REJECTED", "禁止使用正式資料路徑")
        self.binding_loader = binding_loader

    def _bindings_and_paths(self):
        bindings = self.binding_loader(self.root)
        paths = bindings.SyncPaths.for_root(self.workspace)
        expected_database = self.workspace / "data" / "d01" / "observations.sqlite3"
        if Path(paths.database).resolve() != expected_database.resolve():
            raise PreviewError("D02_PATH_MISMATCH", "D02 database 未綁定隔離 workspace")
        return bindings, paths

    def initialize(self):
        bindings, paths = self._bindings_and_paths()
        self.workspace.mkdir(parents=True, exist_ok=True)
        bindings.initialize_database(paths.database)
        return bindings, paths

    def _sample(self, index: int) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        return build_submission(
            product_title=f"I02 合成同步預覽商品 {index + 1}",
            displayed_price_twd=SAMPLE_PRICES[index],
            observed_at=now,
            created_at=now,
            submission_id=SAMPLE_IDS[index],
            is_synthetic=True,
            notes="I02 isolated synthetic preview; not a real offer",
        )

    def ensure_sample(self, index: int) -> Path:
        if index not in (0, 1):
            raise PreviewError("SAMPLE_INDEX_INVALID", str(index))
        _, paths = self.initialize()
        value = self._sample(index)
        target = paths.inbox / f"submission_{SAMPLE_IDS[index]}.json"
        if target.exists():
            try:
                existing = validate_submission(json.loads(target.read_text(encoding="utf-8")))
            except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
                raise PreviewError("SAMPLE_CONFLICT", f"{target.name} 不是有效固定合成樣本") from exc
            offer = existing["offer"]
            if (
                target.is_symlink()
                or not target.is_file()
                or existing["submission_id"] != SAMPLE_IDS[index]
                or existing["is_synthetic"] is not True
                or existing["source"]["source_kind"] != "SYNTHETIC_TEST"
                or offer["displayed_price_twd"] != SAMPLE_PRICES[index]
                or offer["product_title"] != f"I02 合成同步預覽商品 {index + 1}"
            ):
                raise PreviewError("SAMPLE_CONFLICT", f"{target.name} 內容與固定合成樣本不符")
            return target
        try:
            path, _ = safe_write_submission(paths.inbox, value)
        except DuplicateSubmissionError as exc:
            raise PreviewError("SAMPLE_CONCURRENT_CONFLICT", str(exc)) from exc
        return path

    def add_second_sample(self) -> str:
        return self.ensure_sample(1).name

    def read_status(self) -> SyncStatus:
        _, paths = self.initialize()
        return receipt_status(paths.receipts / "latest.json", paths.snapshots / "latest.json", paths.inbox)

    def run_cycle(self, *, dry_run: bool = False, seed_first: bool = True) -> PreviewResult:
        bindings, paths = self.initialize()
        if seed_first:
            self.ensure_sample(0)
        try:
            result = bindings.run_sync(paths, dry_run=dry_run)
        except PreviewError:
            raise
        except Exception as exc:
            raise PreviewError("D02_SYNC_FAILED", str(exc)) from exc
        if bool(result.dry_run) != dry_run:
            raise PreviewError("D02_MODE_MISMATCH", "D02 回報模式與請求不一致")
        if dry_run:
            if result.receipt_path is not None or result.receipt_sha256 is not None or result.snapshot_written:
                raise PreviewError("DRY_RUN_PUBLISHED_OUTPUT", "dry-run 不可發布 receipt 或 snapshot")
            return PreviewResult(
                "DRY_RUN",
                "Dry-run 僅完成隔離檢查；未發布回執，不能視為同步成功",
                "DRY_RUN",
                str(self.workspace),
                None,
                None,
                None,
                None,
                int(result.cutoff_file_count),
                False,
            )
        sync = receipt_status(paths.receipts / "latest.json", paths.snapshots / "latest.json", paths.inbox)
        return PreviewResult(
            sync.state,
            sync.detail,
            "ISOLATED_WRITE",
            str(self.workspace),
            sync.imported_count,
            sync.pending_count,
            sync.quarantined_count,
            sync.retry_count,
            int(result.cutoff_file_count),
            result.receipt_path is not None,
        )

    def export_workspace_summary(self, destination: Path) -> None:
        if not _inside(destination.resolve(), self.allowed_root):
            raise PreviewError("EXPORT_PATH_REJECTED", "summary 必須留在 experiments/I02")
        status = self.read_status()
        payload = {
            "task_id": "CDH-I02-LOCAL-SYNC-PREVIEW-001",
            "workspace": str(self.workspace),
            "source_status": SOURCE_AUTHORITY_STATUS,
            "status": {
                "state": status.state,
                "imported_count": status.imported_count,
                "pending_count": status.pending_count,
                "quarantined_count": status.quarantined_count,
                "retry_count": status.retry_count,
            },
            "notice": "SYNTHETIC_ONLY; UNVERIFIED; not a real offer",
        }
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
