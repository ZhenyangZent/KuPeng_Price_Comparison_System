import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BatchImportPanel } from "../src/BatchImportPanel";
import { parseBatchCommit, parseBatchPreview } from "../src/batchImportClient";
import { csvRows } from "./a15_batch_import_preflight.test";

const sha = "a".repeat(64);
const session = { schema_version: "CDH-B15-PRIVATE-OBSERVATION-API-1", csrf_token: "csrf-a15", storage_scope: "PRIVATE_LOCAL_ONLY", baselines: { B13: sha, B14: sha, C11_REV2: sha, B15_REV2: sha, A14: sha } };
const row = {
  row_number: 2, action: "INSERT", submission_id: "SUB-A15-1", title: "測試商品", series_key: sha,
  observed_at: "2026-11-03T04:00:00Z", taipei_date: "2026-11-03", before_coupon_price_twd: 1000,
  user_reported_coupon_price_twd: 900, confirmed_after_coupon_price_twd: null, coupon_status: "USER_REPORTED",
  coupon_evidence_level: "USER_ASSERTED", source_class: "USER_ENTERED", visibility: "PRIVATE_LOCAL", platform_verified: false,
};
const ready = {
  schema_version: "CDH-B16-PRIVATE-BATCH-API-1", status: "PREVIEW_READY_NO_DATABASE_WRITE", can_confirm: true,
  database_write_count: 0, preview_id: "preview-a15", confirm_token: "confirm-a15", expires_in_seconds: 300,
  filename: "two-days.csv", media_type: "text/csv", file_sha256: sha, row_count: 2, unique_record_count: 2,
  duplicate_input_count: 0, database_summary: { new_count: 2, existing_idempotent_count: 0 }, rows: [row],
  warnings: ["USER_REPORTED_COUPON_NOT_PLATFORM_VERIFIED"],
};
const created = {
  schema_version: "CDH-B16-PRIVATE-BATCH-API-1", status: "BATCH_SAVED_PRIVATE_LOCAL", batch_id: "batch-a15",
  inserted_count: 2, existing_idempotent_count: 0, duplicate_input_count: 0, idempotent_replay: false,
  backup_created: false, backup_cleanup_removed_count: 0, observation_ids: ["obs-1", "obs-2"], data_version: "dv-a15",
};
const replayed = { ...created, inserted_count: 0, existing_idempotent_count: 2, idempotent_replay: true, observation_ids: undefined };
const rejected = {
  schema_version: "CDH-B16-PRIVATE-BATCH-API-1", status: "PREVIEW_REJECTED", can_confirm: false,
  database_write_count: 0, filename: "two-days.csv", media_type: "text/csv", file_sha256: sha,
  row_count: 2, valid_row_count: 1, error_count: 1, rows: [row], row_errors: [{ row_number: 3, error: "PRICE_INVALID" }],
};

function response(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json; charset=utf-8" } });
}
function selectFile(source = csvRows) {
  const input = screen.getByLabelText("選擇合成 CSV 或 JSON"), bytes = new TextEncoder().encode(source);
  Object.defineProperty(input, "files", { configurable: true, value: [{ name: "two-days.csv", size: bytes.length, arrayBuffer: async () => bytes.buffer }] });
  fireEvent.change(input);
}
async function openServerPreview() {
  selectFile();
  const local = await screen.findByRole("region", { name: "批次匯入本機預覽表格" });
  fireEvent.click(within(local).getByRole("button", { name: "送往 B16 安全預覽" }));
  return screen.findByRole("region", { name: "B16 伺服器批次預覽" });
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("A15 true B16 batch API integration", () => {
  it("sends exact base64 bytes with session CSRF and requires explicit confirmation before HTTP 201", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(session))
      .mockResolvedValueOnce(response(ready))
      .mockResolvedValueOnce(response(created, 201));
    vi.stubGlobal("fetch", fetchMock); render(<BatchImportPanel/>);
    const server = await openServerPreview();
    expect(server).toHaveTextContent("database_write_count = 0");
    expect(server).toHaveTextContent("—（未升格）");
    const previewCall = fetchMock.mock.calls[1];
    expect(previewCall[0]).toBe("/cdh-private-observations/api/private-observations/v1/batch-preview");
    const previewOptions = previewCall[1] as RequestInit;
    expect((previewOptions.headers as Record<string, string>)["X-CDH-CSRF-Token"]).toBe("csrf-a15");
    const envelope = JSON.parse(String(previewOptions.body));
    expect(envelope).toEqual(expect.objectContaining({ schema_version: "CDH-B16-BATCH-PREVIEW-REQUEST-1", filename: "two-days.csv", media_type: "text/csv" }));
    expect(new TextDecoder().decode(Uint8Array.from(atob(envelope.content_base64), (character) => character.charCodeAt(0)))).toBe(csvRows);
    expect(JSON.stringify(envelope)).not.toContain("path");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const confirmButton = within(server).getByRole("button", { name: "明確確認並保存" });
    expect(confirmButton).toBeDisabled();
    fireEvent.click(within(server).getByRole("checkbox"));
    fireEvent.click(confirmButton);
    const result = await screen.findByRole("region", { name: "B16 批次保存結果" });
    expect(result).toHaveTextContent("新批次已保存");
    expect(result).toHaveTextContent("HTTP 201");
    expect(result).toHaveTextContent("不會升格為平台確認價");
    const confirmEnvelope = JSON.parse(String((fetchMock.mock.calls[2][1] as RequestInit).body));
    expect(confirmEnvelope).toEqual({ schema_version: "CDH-B16-BATCH-CONFIRM-REQUEST-1", preview_id: "preview-a15", confirm_token: "confirm-a15", explicit_confirm: true });
  });

  it("renders HTTP 200 replay as no new records", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(session)).mockResolvedValueOnce(response(ready)).mockResolvedValueOnce(response(replayed, 200)));
    render(<BatchImportPanel/>); const server = await openServerPreview();
    fireEvent.click(within(server).getByRole("checkbox")); fireEvent.click(within(server).getByRole("button", { name: "明確確認並保存" }));
    expect(await screen.findByText("冪等重播，沒有新增資料")).toBeInTheDocument();
  });

  it("shows HTTP 422 row errors and never offers confirmation", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(session)).mockResolvedValueOnce(response(rejected, 422)));
    render(<BatchImportPanel/>); const server = await openServerPreview();
    expect(server).toHaveTextContent("逐筆驗證失敗，禁止確認");
    expect(server).toHaveTextContent("第 3 列：PRICE_INVALID");
    expect(within(server).queryByRole("button", { name: "明確確認並保存" })).not.toBeInTheDocument();
  });

  it.each([400, 403, 409])("surfaces B16 HTTP %s errors without confirmation", async (status) => {
    const error = { error: { code: `B16_HTTP_${status}`, message: "rejected" } };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(session)).mockResolvedValueOnce(response(error, status)));
    render(<BatchImportPanel/>); await openServerPreview().catch(() => undefined);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(`HTTP ${status}`));
    expect(screen.queryByRole("button", { name: "明確確認並保存" })).not.toBeInTheDocument();
  });

  it("rejects coupon elevation and HTTP/idempotency semantic mismatches", () => {
    expect(() => parseBatchPreview({ ...ready, rows: [{ ...row, confirmed_after_coupon_price_twd: 800 }] }, 200)).toThrow(/升格/);
    expect(() => parseBatchPreview({ ...ready, rows: [{ ...row, platform_verified: true }] }, 200)).toThrow(/升格/);
    expect(() => parseBatchCommit(created, 200)).toThrow(/冪等語義/);
    expect(() => parseBatchCommit(replayed, 201)).toThrow(/冪等語義/);
  });
});
