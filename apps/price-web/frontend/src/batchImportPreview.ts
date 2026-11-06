export const A15_PREFLIGHT_MAX_BYTES = 1024 * 1024;
export const A15_PREFLIGHT_MAX_ROWS = 500;
export const B16_CSV_HEADERS = ["submission_id", "title", "platform", "product_id", "sku_id", "seller_id", "condition", "package_signature", "currency", "observed_at", "quantity", "before_coupon_price_twd", "coupon_status", "coupon_price_twd", "coupon_eligibility", "coupon_evidence_level", "coupon_evidence_note", "coupon_valid_from", "coupon_valid_until", "shipping_status", "shipping_fee_twd", "mandatory_fee_twd", "source_class", "visibility", "source_note"] as const;

export class ImportPreviewError extends Error {
  constructor(public readonly code: string, message: string) { super(message); this.name = "ImportPreviewError"; }
}

export interface ImportPreview {
  format: "CSV" | "JSON";
  filename: string;
  byte_size: number;
  columns: string[];
  records: Record<string, unknown>[];
  warnings: string[];
}

function fail(code: string, message: string): never { throw new ImportPreviewError(code, message); }

function jsonDuplicateKeyCheck(text: string) {
  let cursor = 0;
  const whitespace = () => { while (/\s/u.test(text[cursor] ?? "")) cursor += 1; };
  const stringToken = () => {
    whitespace();
    if (text[cursor] !== '"') fail("JSON_SYNTAX_INVALID", "JSON 字串格式錯誤");
    const start = cursor++;
    while (cursor < text.length) {
      if (text[cursor] === "\\") { cursor += 2; continue; }
      if (text[cursor] === '"') { cursor += 1; try { return JSON.parse(text.slice(start, cursor)) as string; } catch { fail("JSON_SYNTAX_INVALID", "JSON 字串跳脫無效"); } }
      if (text.charCodeAt(cursor) < 0x20) fail("JSON_SYNTAX_INVALID", "JSON 字串含控制字元");
      cursor += 1;
    }
    fail("JSON_SYNTAX_INVALID", "JSON 字串未結束");
  };
  const value = (): void => {
    whitespace();
    const token = text[cursor];
    if (token === "{") {
      cursor += 1; whitespace(); const keys = new Set<string>();
      if (text[cursor] === "}") { cursor += 1; return; }
      while (cursor < text.length) {
        const key = stringToken();
        if (keys.has(key)) fail("JSON_DUPLICATE_KEY", `JSON 物件含重複欄位：${key}`);
        keys.add(key); whitespace(); if (text[cursor++] !== ":") fail("JSON_SYNTAX_INVALID", "JSON 欄位缺少冒號");
        value(); whitespace();
        if (text[cursor] === "}") { cursor += 1; return; }
        if (text[cursor++] !== ",") fail("JSON_SYNTAX_INVALID", "JSON 物件分隔符無效");
      }
      fail("JSON_SYNTAX_INVALID", "JSON 物件未結束");
    }
    if (token === "[") {
      cursor += 1; whitespace(); if (text[cursor] === "]") { cursor += 1; return; }
      while (cursor < text.length) { value(); whitespace(); if (text[cursor] === "]") { cursor += 1; return; } if (text[cursor++] !== ",") fail("JSON_SYNTAX_INVALID", "JSON 陣列分隔符無效"); }
      fail("JSON_SYNTAX_INVALID", "JSON 陣列未結束");
    }
    if (token === '"') { stringToken(); return; }
    const rest = text.slice(cursor), primitive = rest.match(/^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/u)?.[0];
    if (!primitive) fail("JSON_SYNTAX_INVALID", "JSON 值無效");
    cursor += primitive.length;
  };
  value(); whitespace(); if (cursor !== text.length) fail("JSON_SYNTAX_INVALID", "JSON 結尾含額外內容");
}

function parseJson(text: string): Record<string, unknown>[] {
  jsonDuplicateKeyCheck(text);
  let parsed: unknown;
  try { parsed = JSON.parse(text); } catch { fail("JSON_SYNTAX_INVALID", "JSON 無法解析"); }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed) || Object.keys(parsed).sort().join(",") !== "observations,schema_version" || (parsed as Record<string, unknown>).schema_version !== "CDH-B16-BATCH-FILE-1" || !Array.isArray((parsed as Record<string, unknown>).observations)) fail("JSON_ENVELOPE_INVALID", "JSON 必須使用 B16 schema_version＋observations 外層格式");
  const records = (parsed as { observations: unknown[] }).observations;
  if (!records.length) fail("IMPORT_EMPTY", "檔案沒有可預覽的紀錄");
  if (records.some((record) => !record || typeof record !== "object" || Array.isArray(record))) fail("JSON_RECORD_INVALID", "JSON 每筆紀錄必須是物件");
  return records as Record<string, unknown>[];
}

function csvRows(text: string): string[][] {
  const rows: string[][] = []; let row: string[] = [], field = "", quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') { field += '"'; index += 1; }
      else if (character === '"') quoted = false;
      else field += character;
      continue;
    }
    if (character === '"') { if (field.length) fail("CSV_SYNTAX_INVALID", "CSV 引號必須位於欄位開頭"); quoted = true; }
    else if (character === ",") { row.push(field); field = ""; }
    else if (character === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
    else if (character !== "\r") field += character;
  }
  if (quoted) fail("CSV_SYNTAX_INVALID", "CSV 引號未結束");
  if (field.length || row.length) { row.push(field); rows.push(row); }
  return rows;
}

function parseCsv(text: string): Record<string, unknown>[] {
  const rows = csvRows(text.replace(/^\uFEFF/u, ""));
  if (rows.length < 2) fail("IMPORT_EMPTY", "CSV 必須包含標題列與至少一筆資料");
  const headers = rows[0].map((value) => value.trim());
  if (headers.some((value) => !value)) fail("CSV_HEADER_INVALID", "CSV 標題不得為空");
  if (new Set(headers).size !== headers.length) fail("CSV_DUPLICATE_HEADER", "CSV 標題不得重複");
  if (headers.length !== B16_CSV_HEADERS.length || headers.some((header, index) => header !== B16_CSV_HEADERS[index])) fail("CSV_HEADER_CONTRACT_MISMATCH", "CSV 標題及順序必須完全符合 B16 契約");
  return rows.slice(1).filter((values) => values.some((value) => value.length)).map((values, index) => {
    if (values.length !== headers.length) fail("CSV_COLUMN_COUNT_INVALID", `CSV 第 ${index + 2} 列欄位數不一致`);
    return Object.fromEntries(headers.map((header, column) => [header, values[column]]));
  });
}

export function previewImportText(filename: string, byteSize: number, text: string): ImportPreview {
  if (byteSize > A15_PREFLIGHT_MAX_BYTES) fail("FILE_SIZE_LIMIT", `檔案超過 A15 本機預覽上限 ${A15_PREFLIGHT_MAX_BYTES} bytes`);
  const suffix = filename.toLowerCase().split(".").at(-1), format = suffix === "csv" ? "CSV" : suffix === "json" ? "JSON" : fail("FILE_TYPE_UNSUPPORTED", "只接受 .csv 或 .json");
  if (!text.trim()) fail("IMPORT_EMPTY", "檔案是空的");
  const records = format === "CSV" ? parseCsv(text) : parseJson(text);
  if (!records.length) fail("IMPORT_EMPTY", "檔案沒有可預覽的紀錄");
  if (records.length > A15_PREFLIGHT_MAX_ROWS) fail("ROW_LIMIT", `檔案超過 A15 本機預覽上限 ${A15_PREFLIGHT_MAX_ROWS} 筆`);
  const columns: string[] = [];
  for (const record of records) for (const key of Object.keys(record)) if (!columns.includes(key)) columns.push(key);
  return { format, filename, byte_size: byteSize, columns, records, warnings: ["LOCAL_PREFLIGHT_ONLY", "B16_SERVER_VALIDATION_REQUIRED", "NO_DATABASE_WRITE", "USER_REPORTED_COUPON_NOT_CONFIRMED"] };
}

export function previewCell(value: unknown) {
  const rendered = value === null ? "null" : typeof value === "object" ? JSON.stringify(value) : String(value ?? "");
  return rendered.length > 100 ? `${rendered.slice(0, 97)}…` : rendered;
}
