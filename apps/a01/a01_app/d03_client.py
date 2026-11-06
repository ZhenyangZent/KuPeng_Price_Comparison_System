from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .schema import parse_utc


CONTRACT = "CDH-LOCAL-MANUAL-SYNC-1"
COMMANDS = {"status", "preflight", "dry-run", "execute", "verify"}
RESULTS = {"READY", "NEEDS_OPERATOR_CONFIRMATION", "EXECUTED", "DRY_RUN", "NO_CHANGES", "BLOCKED", "FAILED"}
SUCCESS_RESULTS = {"READY", "NEEDS_OPERATOR_CONFIRMATION", "EXECUTED", "DRY_RUN", "NO_CHANGES"}
COUNT_FIELDS = {"scanned", "imported", "duplicate", "quarantined", "pending"}
ROOT_FIELDS = {
    "contract", "command", "result", "source_status", "data_scope", "plan_id", "database_kind",
    "dry_run", "counts", "receipt", "snapshot", "backup", "errors", "generated_at",
}
PLAN_ID = re.compile(r"^[0-9a-f]{64}$")
ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")
MAX_STDOUT_BYTES = 256 * 1024
MAX_STDERR_BYTES = 64 * 1024
PLAN_TTL = timedelta(minutes=10)


class D03Error(RuntimeError):
    pass


class D03Unavailable(D03Error):
    pass


class D03Busy(D03Error):
    pass


class D03Cancelled(D03Error):
    pass


class D03ProtocolError(D03Error):
    pass


class D03CommandError(D03Error):
    def __init__(self, message: str, *, reply: D03Reply | None = None) -> None:
        super().__init__(message)
        self.reply = reply


@dataclass(frozen=True)
class D03Reply:
    command: str
    result: str
    plan_id: str | None
    counts: dict[str, int]
    generated_at: datetime
    data: dict[str, Any]
    expires_at: datetime | None = None
    errors: tuple[dict[str, str], ...] = ()

    @property
    def error_summary(self) -> str:
        return "；".join(f"{item['code']}: {item['detail']}" for item in self.errors)


def _mapping(value: object, fields: set[str], where: str, *, allow_extra: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise D03ProtocolError(f"{where} 必須是 JSON 物件")
    missing = fields - set(value)
    extra = set(value) - fields
    if missing or (extra and not allow_extra):
        raise D03ProtocolError(f"{where} 欄位不符；缺少={sorted(missing)}；多出={sorted(extra)}")
    return value


def _error_rows(value: object) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list):
        raise D03ProtocolError("errors 必須是物件陣列")
    rows: list[dict[str, str]] = []
    for index, raw in enumerate(value):
        item = _mapping(raw, {"code", "detail"}, f"errors[{index}]")
        code, detail = item["code"], item["detail"]
        if not isinstance(code, str) or ERROR_CODE.fullmatch(code) is None:
            raise D03ProtocolError(f"errors[{index}].code 無效")
        if not isinstance(detail, str) or not detail.strip() or len(detail) > 2000:
            raise D03ProtocolError(f"errors[{index}].detail 無效")
        rows.append({"code": code, "detail": detail.strip()})
    return tuple(rows)


def validate_reply(value: object, expected_command: str) -> D03Reply:
    root = _mapping(value, ROOT_FIELDS, "D03 reply", allow_extra=True)
    if root["contract"] != CONTRACT:
        raise D03ProtocolError("D03 contract 不相容")
    if root["command"] != expected_command or expected_command not in COMMANDS:
        raise D03ProtocolError("D03 command 回覆不符")
    if root["result"] not in RESULTS:
        raise D03ProtocolError("D03 result 不在凍結允許清單")
    if root["source_status"] != "SOURCE_BLOCKED":
        raise D03ProtocolError("D03 不得提升來源權限")
    if root["data_scope"] != "USER_PROVIDED_LOCAL_ONLY" or root["database_kind"] != "USER_LOCAL":
        raise D03ProtocolError("D03 資料範圍或資料庫類型不符")
    if not isinstance(root["dry_run"], bool):
        raise D03ProtocolError("dry_run 必須是 boolean")
    if expected_command == "dry-run" and not root["dry_run"]:
        raise D03ProtocolError("dry-run 回覆不得宣稱實際寫入")
    if expected_command in {"status", "preflight", "verify"} and root["dry_run"]:
        raise D03ProtocolError(f"{expected_command} dry_run 語意不符")
    counts = _mapping(root["counts"], COUNT_FIELDS, "counts")
    for name, number in counts.items():
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise D03ProtocolError(f"counts.{name} 必須是非負整數")
    for name in ("receipt", "snapshot"):
        item = _mapping(root[name], {"state", "sha256"}, name, allow_extra=True)
        if not isinstance(item["state"], str) or item["sha256"] is not None and not isinstance(item["sha256"], str):
            raise D03ProtocolError(f"{name} 欄位無效")
    backup = _mapping(root["backup"], {"state", "path", "sha256"}, "backup", allow_extra=True)
    if not isinstance(backup["state"], str):
        raise D03ProtocolError("backup.state 無效")
    errors = _error_rows(root["errors"])
    plan_id = root["plan_id"]
    if plan_id is not None and (not isinstance(plan_id, str) or PLAN_ID.fullmatch(plan_id) is None):
        raise D03ProtocolError("plan_id 格式無效")
    if expected_command in {"status", "preflight"} and plan_id is not None:
        raise D03ProtocolError(f"{expected_command} 不得回覆 plan_id")
    if expected_command == "dry-run" and root["result"] == "NEEDS_OPERATOR_CONFIRMATION" and plan_id is None:
        raise D03ProtocolError("需要確認的 dry-run 必須提供 plan_id")
    if expected_command == "execute" and root["result"] == "EXECUTED" and plan_id is None:
        raise D03ProtocolError("EXECUTED 必須綁定 plan_id")
    if root["result"] in {"BLOCKED", "FAILED"} and not errors:
        raise D03ProtocolError("BLOCKED／FAILED 必須提供錯誤原因")
    generated = parse_utc(root["generated_at"], "generated_at")
    expires = generated + PLAN_TTL if expected_command == "dry-run" and plan_id is not None else None
    return D03Reply(expected_command, root["result"], plan_id, dict(counts), generated, dict(root), expires, errors)


class D03Client:
    _guard_map_lock = threading.Lock()
    _guard_map: dict[str, threading.Lock] = {}

    def __init__(
        self,
        project_root: Path,
        *,
        python_executable: Path | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.cli_path = self.project_root / "scripts/d03/local_operator.py"
        self.python_executable = (python_executable or Path(sys.executable)).resolve()
        self._runner = runner
        self._process_lock = threading.Lock()
        self._active_process: subprocess.Popen[str] | None = None
        self._cancel_requested = threading.Event()
        key = str(self.project_root).casefold()
        with self._guard_map_lock:
            self._run_guard = self._guard_map.setdefault(key, threading.Lock())

    @property
    def available(self) -> bool:
        return self.cli_path.is_file() and not self.cli_path.is_symlink()

    def cancel(self) -> bool:
        self._cancel_requested.set()
        with self._process_lock:
            process = self._active_process
        if process is None or process.poll() is not None:
            return False
        try:
            process.terminate()
        except OSError:
            return False
        return True

    def _default_run(self, arguments: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        self._cancel_requested.clear()
        process = subprocess.Popen(
            arguments,
            cwd=self.project_root,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
        )
        with self._process_lock:
            self._active_process = process
        try:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.communicate()
                raise D03Error(f"D03 {arguments[2]} 逾時，子程序已終止") from exc
            if self._cancel_requested.is_set():
                raise D03Cancelled(f"D03 {arguments[2]} 已由使用者取消")
            return subprocess.CompletedProcess(arguments, process.returncode, stdout, stderr)
        finally:
            with self._process_lock:
                self._active_process = None
            self._cancel_requested.clear()

    def run(self, command: str, *, plan_id: str | None = None, operator_confirmed: bool = False) -> D03Reply:
        if command not in COMMANDS:
            raise D03ProtocolError("不允許的 D03 命令")
        if not self.available:
            raise D03Unavailable("本地同步元件尚未完成")
        if command == "execute":
            if plan_id is None or PLAN_ID.fullmatch(plan_id) is None or not operator_confirmed:
                raise D03ProtocolError("execute 需要有效 plan_id 與操作者明確確認")
        elif plan_id is not None or operator_confirmed:
            raise D03ProtocolError("只有 execute 可帶 plan_id／operator-confirmed")
        if not self._run_guard.acquire(blocking=False):
            raise D03Busy("同一專案已有 D03 操作執行中")
        arguments = [str(self.python_executable), str(self.cli_path), command, "--project-root", str(self.project_root), "--json"]
        if command == "execute":
            arguments.extend(["--plan-id", str(plan_id), "--operator-confirmed"])
        timeout = 120 if command == "execute" else 30
        try:
            try:
                completed = self._default_run(arguments, timeout=timeout) if self._runner is None else self._runner(arguments, cwd=self.project_root, timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                raise D03Error(f"D03 {command} 逾時") from exc
            except (OSError, UnicodeError) as exc:
                raise D03Error(f"D03 {command} 無法啟動：{exc}") from exc
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            if len(stdout.encode("utf-8")) > MAX_STDOUT_BYTES or len(stderr.encode("utf-8")) > MAX_STDERR_BYTES:
                raise D03ProtocolError("D03 輸出超過上限")
            try:
                value = json.loads(stdout)
            except json.JSONDecodeError as exc:
                detail = stderr.strip()[:500]
                raise D03ProtocolError(f"D03 stdout 必須是單一 JSON 物件{f'；stderr={detail}' if detail else ''}") from exc
            reply = validate_reply(value, command)
            if completed.returncode != 0 or reply.result not in SUCCESS_RESULTS:
                reason = reply.error_summary or stderr.strip()[:500] or f"exit={completed.returncode}"
                raise D03CommandError(f"D03 {command} 失敗：{reason}", reply=reply)
            return reply
        finally:
            self._run_guard.release()


def plan_is_current(reply: D03Reply, *, now: datetime | None = None) -> bool:
    if reply.plan_id is None or reply.expires_at is None:
        return False
    check = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return check <= reply.expires_at.astimezone(timezone.utc)
