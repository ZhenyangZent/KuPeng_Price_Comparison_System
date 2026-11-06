import { strictIsoTimestamp } from "./couponRuntimeSchema";
import {
  B10_WIRE_SCHEMA,
  type B10AfterHistoryPoint,
  type B10BeforeHistoryPoint,
  type B10Coupon,
  type B10DailyRepresentative,
  type B10DetailResponse,
  type B10HistoryQuality,
  type B10Product,
  type B10SearchResponse,
  type B10SeriesIdentity
} from "./b10WireTypes";

export class B10WireError extends Error {
  constructor(public readonly code: "INVALID_B10_WIRE" | "B10_VERSION_MISMATCH" | "B10_IDENTITY_MISMATCH" | "B10_SNAPSHOT_MISMATCH", detail: string) {
    super(detail);
    this.name = "B10WireError";
  }
}
type JsonObject = Record<string, unknown>;
const object = (v: unknown, p: string): JsonObject => { if (typeof v !== "object" || v === null || Array.isArray(v)) throw new B10WireError("INVALID_B10_WIRE", `${p} 必須是物件`); return v as JsonObject; };
const text = (v: unknown, p: string, nullable = false): string | null => { if (nullable && v === null) return null; if (typeof v !== "string" || v.trim() === "") throw new B10WireError("INVALID_B10_WIRE", `${p} 必須是非空字串`); return v; };
const integer = (v: unknown, p: string, nullable = false): number | null => { if (nullable && v === null) return null; if (!Number.isSafeInteger(v) || (v as number) < 0) throw new B10WireError("INVALID_B10_WIRE", `${p} 必須是非負整數`); return v as number; };
const bool = (v: unknown, p: string): boolean => { if (typeof v !== "boolean") throw new B10WireError("INVALID_B10_WIRE", `${p} 必須是 boolean`); return v; };
const enumeration = <T extends string>(v: unknown, values: readonly T[], p: string): T => { if (typeof v !== "string" || !values.includes(v as T)) throw new B10WireError("INVALID_B10_WIRE", `${p} 不在允許值內`); return v as T; };
const stringArray = (v: unknown, p: string): string[] => { if (!Array.isArray(v) || v.some((item) => typeof item !== "string") || new Set(v).size !== v.length) throw new B10WireError("INVALID_B10_WIRE", `${p} 必須是唯一字串陣列`); return v as string[]; };
const timestamp = (v: unknown, p: string, nullable = false): string | null => { if (nullable && v === null) return null; try { return strictIsoTimestamp(v, p); } catch (error) { throw new B10WireError("INVALID_B10_WIRE", error instanceof Error ? error.message : `${p} 時間無效`); } };

function envelope(r: JsonObject) {
  if (r.schema_version !== B10_WIRE_SCHEMA) throw new B10WireError("B10_VERSION_MISMATCH", `只接受 ${B10_WIRE_SCHEMA}`);
  return {
    schema_version: B10_WIRE_SCHEMA,
    data_classification: enumeration(r.data_classification, ["SYNTHETIC_FIXTURE"] as const, "data_classification"),
    data_version: text(r.data_version, "data_version")!
  };
}

function identity(v: unknown, p: string): B10SeriesIdentity {
  const r = object(v, p);
  return {
    platform: enumeration(r.platform, ["COUPANG_TW"] as const, `${p}.platform`),
    product_id: text(r.product_id, `${p}.product_id`)! , sku_id: text(r.sku_id, `${p}.sku_id`)! , seller_id: text(r.seller_id, `${p}.seller_id`)! ,
    condition: text(r.condition, `${p}.condition`)! , package_signature: text(r.package_signature, `${p}.package_signature`)!
  };
}

function coupon(v: unknown, p: string): B10Coupon {
  const r = object(v, p);
  return {
    coupon_id: text(r.coupon_id, `${p}.coupon_id`, true),
    status: enumeration(r.status, ["CONFIRMED_APPLICABLE","CLAIM_REQUIRED","UNVERIFIED","INELIGIBLE","EXPIRED","UNKNOWN","NONE"] as const, `${p}.status`),
    discount_twd: integer(r.discount_twd, `${p}.discount_twd`, true),
    discount_scope: enumeration(r.discount_scope, ["UNIT","ORDER_TOTAL","NONE"] as const, `${p}.discount_scope`),
    already_included_in_base: bool(r.already_included_in_base, `${p}.already_included_in_base`),
    eligibility_profile: text(r.eligibility_profile, `${p}.eligibility_profile`, true),
    valid_from: timestamp(r.valid_from, `${p}.valid_from`, true), valid_until: timestamp(r.valid_until, `${p}.valid_until`, true),
    scope_evidence: text(r.scope_evidence, `${p}.scope_evidence`, true), pre_coupon_comparison_source: text(r.pre_coupon_comparison_source, `${p}.pre_coupon_comparison_source`, true),
    evaluation_reasons: stringArray(r.evaluation_reasons, `${p}.evaluation_reasons`)
  };
}

function product(v: unknown, p: string): B10Product {
  const r = object(v, p), c = coupon(r.coupon, `${p}.coupon`);
  const sourcePermissionRaw = object(r.source_permission, `${p}.source_permission`);
  const sourcePermission = { allowed: bool(sourcePermissionRaw.allowed, `${p}.source_permission.allowed`), state: text(sourcePermissionRaw.state, `${p}.source_permission.state`)! , reason: text(sourcePermissionRaw.reason, `${p}.source_permission.reason`)! };
  const result: B10Product = {
    series_key: text(r.series_key, `${p}.series_key`)! , title: text(r.title, `${p}.title`)! , series_identity: identity(r.series_identity, `${p}.series_identity`),
    data_classification: enumeration(r.data_classification, ["SYNTHETIC_FIXTURE"] as const, `${p}.data_classification`),
    source_id: text(r.source_id, `${p}.source_id`, true), observed_at: timestamp(r.observed_at, `${p}.observed_at`, true),
    base_price_twd: integer(r.base_price_twd, `${p}.base_price_twd`, true), before_coupon_price_twd: integer(r.before_coupon_price_twd, `${p}.before_coupon_price_twd`, true),
    coupon: c, confirmed_coupon_price_twd: integer(r.confirmed_coupon_price_twd, `${p}.confirmed_coupon_price_twd`, true), possible_coupon_price_twd: integer(r.possible_coupon_price_twd, `${p}.possible_coupon_price_twd`, true),
    display_price_twd: integer(r.display_price_twd, `${p}.display_price_twd`, true), display_basis: enumeration(r.display_basis, ["CONFIRMED_COUPON","BASE_PRICE","PRICE_UNAVAILABLE"] as const, `${p}.display_basis`),
    minimum_purchase_quantity: integer(r.minimum_purchase_quantity, `${p}.minimum_purchase_quantity`)! , minimum_item_spend_twd: integer(r.minimum_item_spend_twd, `${p}.minimum_item_spend_twd`, true),
    shipping_status: text(r.shipping_status, `${p}.shipping_status`)! , required_total_twd: integer(r.required_total_twd, `${p}.required_total_twd`, true), source_permission: sourcePermission,
    quality_flags: stringArray(r.quality_flags, `${p}.quality_flags`)
  };
  if (result.minimum_purchase_quantity < 1) throw new B10WireError("INVALID_B10_WIRE", `${p}.minimum_purchase_quantity 必須至少為 1`);
  if (!sourcePermission.allowed && result.display_basis !== "PRICE_UNAVAILABLE") throw new B10WireError("INVALID_B10_WIRE", `${p} 來源權限失效時不得顯示價格`);
  if (result.display_basis === "PRICE_UNAVAILABLE") {
    if (result.display_price_twd !== null || result.confirmed_coupon_price_twd !== null || result.minimum_item_spend_twd !== null || result.required_total_twd !== null) throw new B10WireError("INVALID_B10_WIRE", `${p} PRICE_UNAVAILABLE 不得夾帶可購買價格`);
  } else {
    if (result.display_price_twd === null || result.minimum_item_spend_twd !== result.display_price_twd * result.minimum_purchase_quantity) throw new B10WireError("INVALID_B10_WIRE", `${p} 展示價與最低整筆商品額不一致`);
  }
  if (result.display_basis === "CONFIRMED_COUPON") {
    if (c.status !== "CONFIRMED_APPLICABLE" || result.confirmed_coupon_price_twd !== result.display_price_twd || !sourcePermission.allowed || [c.coupon_id,c.eligibility_profile,c.valid_from,c.valid_until,c.scope_evidence].some((item) => item === null)) throw new B10WireError("INVALID_B10_WIRE", `${p} 確認券價缺少一致證據`);
    if (result.observed_at === null || Date.parse(c.valid_from!) > Date.parse(result.observed_at) || Date.parse(c.valid_until!) < Date.parse(result.observed_at)) throw new B10WireError("INVALID_B10_WIRE", `${p} 確認券不適用於觀測時間`);
  } else if (result.confirmed_coupon_price_twd !== null) throw new B10WireError("INVALID_B10_WIRE", `${p} 非確認基準不得夾帶確認券價`);
  if (result.display_basis === "BASE_PRICE" && (result.base_price_twd === null || result.display_price_twd !== result.base_price_twd)) throw new B10WireError("INVALID_B10_WIRE", `${p} BASE_PRICE 主價不一致`);
  if (result.shipping_status === "UNKNOWN" && result.required_total_twd !== null) throw new B10WireError("INVALID_B10_WIRE", `${p} 運費未知時 required_total_twd 必須為 null`);
  return result;
}

function beforePoint(v: unknown, p: string, key: string): B10BeforeHistoryPoint {
  const r = object(v,p), point={observed_at:timestamp(r.observed_at,`${p}.observed_at`)! ,price_twd:integer(r.price_twd,`${p}.price_twd`)! ,source_id:text(r.source_id,`${p}.source_id`)! ,comparison_source:text(r.comparison_source,`${p}.comparison_source`)! ,series_key:text(r.series_key,`${p}.series_key`)!};
  if(point.series_key!==key)throw new B10WireError("B10_IDENTITY_MISMATCH",`${p}.series_key 與 detail 不一致`);return point;
}
function afterPoint(v: unknown, p: string, key: string): B10AfterHistoryPoint {
  const r=object(v,p),point={observed_at:timestamp(r.observed_at,`${p}.observed_at`)! ,price_twd:integer(r.price_twd,`${p}.price_twd`)! ,coupon_id:text(r.coupon_id,`${p}.coupon_id`)! ,eligibility_profile:text(r.eligibility_profile,`${p}.eligibility_profile`)! ,source_id:text(r.source_id,`${p}.source_id`)! ,scope_evidence:text(r.scope_evidence,`${p}.scope_evidence`)! ,series_key:text(r.series_key,`${p}.series_key`)!};
  if(point.series_key!==key)throw new B10WireError("B10_IDENTITY_MISMATCH",`${p}.series_key 與 detail 不一致`);return point;
}
function quality(v: unknown,p:string,actual:number):B10HistoryQuality{const r=object(v,p);if(!Array.isArray(r.daily_representatives))throw new B10WireError("INVALID_B10_WIRE",`${p}.daily_representatives 必須是陣列`);const daily:B10DailyRepresentative[]=r.daily_representatives.map((entry,index)=>{const q=object(entry,`${p}.daily_representatives[${index}]`);const date=text(q.taipei_date,`${p}.daily_representatives[${index}].taipei_date`)!;if(!/^\d{4}-\d{2}-\d{2}$/.test(date))throw new B10WireError("INVALID_B10_WIRE",`${p} 日期無效`);return{taipei_date:date,representative_price_twd:integer(q.representative_price_twd,`${p}.daily_representatives[${index}].representative_price_twd`)! ,sample_count:integer(q.sample_count,`${p}.daily_representatives[${index}].sample_count`)!};});const result={raw_sample_count:integer(r.raw_sample_count,`${p}.raw_sample_count`)! ,daily_representatives:daily,truncated:bool(r.truncated,`${p}.truncated`)};if(result.raw_sample_count!==actual)throw new B10WireError("INVALID_B10_WIRE",`${p}.raw_sample_count 與實際歷史不一致`);return result;}

export function parseB10Search(v: unknown): B10SearchResponse {
  const r=object(v,"search"),e=envelope(r);if(!Array.isArray(r.items))throw new B10WireError("INVALID_B10_WIRE","search.items 必須是陣列");const page=integer(r.page,"search.page")!,limit=integer(r.limit,"search.limit")!,total=integer(r.total,"search.total")!;if(page<1||limit<1||limit>100||total<r.items.length)throw new B10WireError("INVALID_B10_WIRE","search 分頁不一致");return{...e,items:r.items.map((item,index)=>product(item,`search.items[${index}]`)),page,limit,total};
}

export function parseB10Detail(v: unknown, expectedSeriesKey: string, expected?: B10Product): B10DetailResponse {
  const r=object(v,"detail"),e=envelope(r),p=product(r.product,"detail.product");if(p.series_key!==expectedSeriesKey)throw new B10WireError("B10_IDENTITY_MISMATCH","detail series_key 與請求不一致");
  if(expected){const a=p.series_identity,b=expected.series_identity;if(p.series_key!==expected.series_key||a.product_id!==b.product_id||a.sku_id!==b.sku_id||a.seller_id!==b.seller_id||a.condition!==b.condition||a.package_signature!==b.package_signature)throw new B10WireError("B10_IDENTITY_MISMATCH","search/detail 精確商品身分不一致");}
  const h=object(r.history,"detail.history");if(!Array.isArray(h.before_coupon)||!Array.isArray(h.confirmed_after_coupon))throw new B10WireError("INVALID_B10_WIRE","detail history 必須含兩條陣列");const before=h.before_coupon.map((item,index)=>beforePoint(item,`detail.history.before_coupon[${index}]`,p.series_key));const after=h.confirmed_after_coupon.map((item,index)=>afterPoint(item,`detail.history.confirmed_after_coupon[${index}]`,p.series_key));const q=object(r.history_quality,"detail.history_quality");return{...e,product:p,history:{before_coupon:before,confirmed_after_coupon:after},history_quality:{before_coupon:quality(q.before_coupon,"detail.history_quality.before_coupon",before.length),confirmed_after_coupon:quality(q.confirmed_after_coupon,"detail.history_quality.confirmed_after_coupon",after.length)}};
}

export function assertSameB10Snapshot(search: B10SearchResponse, detail: B10DetailResponse) { if(search.data_version!==detail.data_version)throw new B10WireError("B10_SNAPSHOT_MISMATCH","Search 與 Detail data_version 不一致，拒絕混用快照"); }
