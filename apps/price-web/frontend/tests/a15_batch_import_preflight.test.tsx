import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BatchImportPanel } from "../src/BatchImportPanel";
import { B16_CSV_HEADERS, ImportPreviewError, previewImportText } from "../src/batchImportPreview";

export const csvRows = [
  B16_CSV_HEADERS.join(","),
  "SUB-A15-1,測試商品,COUPANG_TW,PROD-A15,SKU-A15,SELLER-A15,NEW,EA,TWD,2026-11-03T04:00:00Z,1,1000,USER_REPORTED,900,UNKNOWN,USER_ASSERTED,synthetic receipt,,,UNKNOWN,,,USER_ENTERED,PRIVATE_LOCAL,A15 synthetic",
  "SUB-A15-2,測試商品,COUPANG_TW,PROD-A15,SKU-A15,SELLER-A15,NEW,EA,TWD,2026-11-04T04:00:00Z,1,950,NONE,,UNKNOWN,NONE,,,,UNKNOWN,,,USER_ENTERED,PRIVATE_LOCAL,A15 synthetic",
].join("\n");

function select(input: HTMLElement, name: string, source: string) {
  const bytes = new TextEncoder().encode(source);
  const file = { name, size: bytes.length, arrayBuffer: async () => bytes.buffer };
  Object.defineProperty(input, "files", { configurable: true, value: [file] });
  fireEvent.change(input);
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("A15 exact B16 local preflight", () => {
  it("shows exact B16 CSV rows locally without any HTTP or database write", async () => {
    const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock); render(<BatchImportPanel/>);
    select(screen.getByLabelText("選擇合成 CSV 或 JSON"), "two-days.csv", csvRows);
    const table = await screen.findByRole("region", { name: "批次匯入本機預覽表格" });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(table).toHaveTextContent("LOCAL_PREFLIGHT_ONLY");
    expect(table).toHaveTextContent("NO_DATABASE_WRITE");
    expect(table).toHaveTextContent("USER_REPORTED_COUPON_NOT_CONFIRMED");
    expect(within(table).getByRole("button", { name: "送往 B16 安全預覽" })).toBeEnabled();
    await waitFor(() => expect(fetchMock).not.toHaveBeenCalled());
  });

  it("expands the B16 JSON envelope observations instead of treating it as one row", () => {
    const source = JSON.stringify({ schema_version: "CDH-B16-BATCH-FILE-1", observations: [
      { submission_id: "SUB-1", title: "one" },
      { submission_id: "SUB-2", title: "two", coupon_status: "USER_REPORTED" },
    ] });
    const result = previewImportText("two-days.json", new TextEncoder().encode(source).length, source);
    expect(result.records).toHaveLength(2);
    expect(result.columns).toEqual(["submission_id", "title", "coupon_status"]);
  });

  it("rejects duplicate JSON keys before JSON.parse can discard evidence", () => {
    const source = '{"schema_version":"CDH-B16-BATCH-FILE-1","observations":[{"product_id":"P1","product_id":"P2"}]}';
    expect(() => previewImportText("duplicate.json", source.length, source)).toThrowError(ImportPreviewError);
    try { previewImportText("duplicate.json", source.length, source); } catch (error) { expect(error).toMatchObject({ code: "JSON_DUPLICATE_KEY" }); }
  });

  it("rejects non-contract CSV, top-level JSON arrays, unsupported and >1 MiB files", () => {
    expect(() => previewImportText("bad.csv", 20, "a,b\n1,2")).toThrow(/完全符合 B16 契約/);
    expect(() => previewImportText("array.json", 2, "[]")).toThrow(/外層格式/);
    expect(() => previewImportText("bad.txt", 2, "{}")).toThrow(/只接受/);
    expect(() => previewImportText("large.json", 1024 * 1024 + 1, "{}")).toThrow(/1048576 bytes/);
  });
});
