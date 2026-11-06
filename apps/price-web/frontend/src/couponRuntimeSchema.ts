import {
  COUPON_SCHEMA_VERSION,
  type CouponEvidence,
  type CouponHistoryPoint,
  type CouponPriceResponse,
  type CouponSeriesIdentity,
  type CouponStatus
} from "./couponTypes";

export class CouponContractError extends Error {
  constructor(public readonly code: "INVALID_V4_PAYLOAD" | "V4_VERSION_MISMATCH", detail: string) {
    super(detail);
    this.name = "CouponContractError";
  }
}

type JsonObject = Record<string, unknown>;
const object = (value: unknown, path: string): JsonObject => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new CouponContractError("INVALID_V4_PAYLOAD", `${path} 必須是物件`);
  }
  return value as JsonObject;
};
const text = (value: unknown, path: string, nullable = false): string | null => {
  if (nullable && value === null) return null;
  if (typeof value !== "string" || value.trim() === "") throw new CouponContractError("INVALID_V4_PAYLOAD", `${path} 必須是非空字串`);
  return value;
};
const integer = (value: unknown, path: string, nullable = false): number | null => {
  if (nullable && value === null) return null;
  if (!Number.isSafeInteger(value) || (value as number) < 0) throw new CouponContractError("INVALID_V4_PAYLOAD", `${path} 必須是非負整數`);
  return value as number;
};
const bool = (value: unknown, path: string): boolean => {
  if (typeof value !== "boolean") throw new CouponContractError("INVALID_V4_PAYLOAD", `${path} 必須是 boolean`);
  return value;
};
const enumeration = <T extends string>(value: unknown, values: readonly T[], path: string): T => {
  if (typeof value !== "string" || !values.includes(value as T)) throw new CouponContractError("INVALID_V4_PAYLOAD", `${path} 不在允許值內`);
  return value as T;
};

const ISO_TIMESTAMP = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?(Z|[+-]\d{2}:\d{2})$/;
export function strictIsoTimestamp(value: unknown, path: string): string {
  const raw = text(value, path)!;
  const match = ISO_TIMESTAMP.exec(raw);
  if (!match) throw new CouponContractError("INVALID_V4_PAYLOAD", `${path} 必須是嚴格 ISO 8601 時間戳`);
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, , zone] = match;
  const year = Number(yearText), month = Number(monthText), day = Number(dayText);
  const hour = Number(hourText), minute = Number(minuteText), second = Number(secondText);
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const zoneValid = zone === "Z" || (() => {
    const zoneHour = Number(zone.slice(1, 3));
    const zoneMinute = Number(zone.slice(4, 6));
    return zoneHour <= 23 && zoneMinute <= 59;
  })();
  if (month < 1 || month > 12 || day < 1 || day > daysInMonth || hour > 23 || minute > 59 || second > 59 || !zoneValid || Number.isNaN(Date.parse(raw))) {
    throw new CouponContractError("INVALID_V4_PAYLOAD", `${path} 不是有效日曆時間`);
  }
  return raw;
}

function seriesIdentity(value: unknown): CouponSeriesIdentity {
  const r = object(value, "series_identity");
  return {
    platform: enumeration(r.platform, ["COUPANG_TW"] as const, "series_identity.platform"),
    product_id: text(r.product_id, "series_identity.product_id")!,
    sku_id: text(r.sku_id, "series_identity.sku_id")!,
    seller_id: text(r.seller_id, "series_identity.seller_id")!,
    condition: enumeration(r.condition, ["NEW"] as const, "series_identity.condition"),
    package_signature: text(r.package_signature, "series_identity.package_signature")!
  };
}

const statuses = ["CONFIRMED_APPLICABLE", "CLAIM_REQUIRED", "UNVERIFIED", "INELIGIBLE", "EXPIRED", "UNKNOWN", "NONE"] as const;
function coupon(value: unknown): CouponEvidence {
  const r = object(value, "coupon");
  const status = enumeration(r.status, statuses, "coupon.status");
  return {
    coupon_id: text(r.coupon_id, "coupon.coupon_id", true),
    status,
    discount_twd: integer(r.discount_twd, "coupon.discount_twd", true),
    already_included_in_base: bool(r.already_included_in_base, "coupon.already_included_in_base"),
    eligibility_profile: text(r.eligibility_profile, "coupon.eligibility_profile", true),
    valid_from: r.valid_from === null ? null : strictIsoTimestamp(r.valid_from, "coupon.valid_from"),
    valid_until: r.valid_until === null ? null : strictIsoTimestamp(r.valid_until, "coupon.valid_until"),
    scope_evidence: text(r.scope_evidence, "coupon.scope_evidence", true)
  };
}

function history(value: unknown, identity: CouponSeriesIdentity, path: string, confirmed: boolean): CouponHistoryPoint[] {
  if (!Array.isArray(value)) throw new CouponContractError("INVALID_V4_PAYLOAD", `${path} 必須是陣列`);
  return value.map((entry, index) => {
    const itemPath = `${path}[${index}]`, r = object(entry, itemPath);
    const point: CouponHistoryPoint = {
      observed_at: strictIsoTimestamp(r.observed_at, `${itemPath}.observed_at`),
      price_twd: integer(r.price_twd, `${itemPath}.price_twd`)! ,
      product_id: text(r.product_id, `${itemPath}.product_id`)! ,
      sku_id: text(r.sku_id, `${itemPath}.sku_id`)! ,
      seller_id: text(r.seller_id, `${itemPath}.seller_id`)! ,
      coupon_id: text(r.coupon_id, `${itemPath}.coupon_id`, true),
      eligibility_profile: text(r.eligibility_profile, `${itemPath}.eligibility_profile`, true),
      source_id: text(r.source_id, `${itemPath}.source_id`)! ,
      source_evidence: text(r.source_evidence, `${itemPath}.source_evidence`)!
    };
    if (point.product_id !== identity.product_id || point.sku_id !== identity.sku_id || point.seller_id !== identity.seller_id) {
      throw new CouponContractError("INVALID_V4_PAYLOAD", `${itemPath} 不得跨商品、SKU 或賣家混用`);
    }
    if (confirmed && (point.coupon_id === null || point.eligibility_profile === null)) {
      throw new CouponContractError("INVALID_V4_PAYLOAD", `${itemPath} 缺少已確認優惠券與資格證據`);
    }
    if (!confirmed && point.coupon_id !== null) throw new CouponContractError("INVALID_V4_PAYLOAD", `${itemPath} 券前歷史不得偽裝成券後觀測`);
    return point;
  });
}

function requireConfirmedEvidence(c: CouponEvidence, observedAt: string) {
  const required = [c.coupon_id, c.discount_twd, c.eligibility_profile, c.valid_from, c.valid_until, c.scope_evidence];
  if (required.some((value) => value === null)) throw new CouponContractError("INVALID_V4_PAYLOAD", "確認可用券缺少 ID、折抵、資格、效期或範圍證據");
  if (Date.parse(c.valid_from!) > Date.parse(observedAt) || Date.parse(c.valid_until!) < Date.parse(observedAt)) {
    throw new CouponContractError("INVALID_V4_PAYLOAD", "確認可用券不在觀測有效期內");
  }
}

export function parseCouponPriceV4(value: unknown): CouponPriceResponse {
  const r = object(value, "coupon_price");
  if (r.schema_version !== COUPON_SCHEMA_VERSION) throw new CouponContractError("V4_VERSION_MISMATCH", `只接受 ${COUPON_SCHEMA_VERSION}`);
  const identity = seriesIdentity(r.series_identity);
  const observedAt = strictIsoTimestamp(r.observed_at, "observed_at");
  const basePrice = integer(r.base_price_twd, "base_price_twd", true);
  const couponEvidence = coupon(r.coupon);
  const confirmedPrice = integer(r.confirmed_coupon_price_twd, "confirmed_coupon_price_twd", true);
  const possiblePrice = integer(r.possible_coupon_price_twd, "possible_coupon_price_twd", true);
  const displayPrice = integer(r.display_price_twd, "display_price_twd", true);
  const displayBasis = enumeration(r.display_basis, ["CONFIRMED_COUPON", "BASE_PRICE", "UNAVAILABLE"] as const, "display_basis");
  const shippingStatus = enumeration(r.shipping_status, ["FREE", "PAID", "UNKNOWN"] as const, "shipping_status");
  const requiredTotal = integer(r.required_total_twd, "required_total_twd", true);
  const priceBasis = object(r.price_basis, "price_basis");
  const amountBasis = enumeration(priceBasis.amount_basis, ["PER_ITEM"] as const, "price_basis.amount_basis");
  const quantity = integer(priceBasis.quantity, "price_basis.quantity")!;
  const discountBasis = enumeration(priceBasis.coupon_discount_basis, ["PER_ITEM"] as const, "price_basis.coupon_discount_basis");
  if (quantity !== 1) throw new CouponContractError("INVALID_V4_PAYLOAD", "V4 UI 只接受證據明確的單件金額；多件口徑須由 B10 明確轉換");
  if (shippingStatus === "UNKNOWN" && requiredTotal !== null) throw new CouponContractError("INVALID_V4_PAYLOAD", "運費未知時 required_total_twd 必須為 null");

  if (couponEvidence.status === "CONFIRMED_APPLICABLE") {
    requireConfirmedEvidence(couponEvidence, observedAt);
    if (basePrice === null || confirmedPrice === null) throw new CouponContractError("INVALID_V4_PAYLOAD", "確認券價需要有效券前與券後價");
    const expected = couponEvidence.already_included_in_base ? basePrice : basePrice - couponEvidence.discount_twd!;
    if (expected < 0 || confirmedPrice !== expected) throw new CouponContractError("INVALID_V4_PAYLOAD", "確認券後價與券前價、折抵或已包含狀態不一致");
    if (displayBasis !== "CONFIRMED_COUPON" || displayPrice !== confirmedPrice || possiblePrice !== null) throw new CouponContractError("INVALID_V4_PAYLOAD", "確認券後價必須是唯一主顯示價");
  } else {
    if (confirmedPrice !== null) throw new CouponContractError("INVALID_V4_PAYLOAD", "未確認、過期或不適用優惠券不得產生確認券價");
    if (basePrice === null) {
      if (displayBasis !== "UNAVAILABLE" || displayPrice !== null) throw new CouponContractError("INVALID_V4_PAYLOAD", "基價未知時必須維持價格未知");
    } else if (displayBasis !== "BASE_PRICE" || displayPrice !== basePrice) {
      throw new CouponContractError("INVALID_V4_PAYLOAD", "非確認優惠券不得取代券前主價");
    }
    if (couponEvidence.status === "NONE" && (couponEvidence.coupon_id !== null || couponEvidence.discount_twd !== null || possiblePrice !== null)) {
      throw new CouponContractError("INVALID_V4_PAYLOAD", "無券狀態不得夾帶優惠券價格");
    }
  }

  const rawHistory = object(r.history, "history");
  return {
    schema_version: COUPON_SCHEMA_VERSION,
    series_identity: identity,
    data_classification: enumeration(r.data_classification, ["SYNTHETIC_FIXTURE"] as const, "data_classification"),
    source_id: text(r.source_id, "source_id")!,
    observed_at: observedAt,
    base_price_twd: basePrice,
    coupon: couponEvidence,
    confirmed_coupon_price_twd: confirmedPrice,
    possible_coupon_price_twd: possiblePrice,
    display_price_twd: displayPrice,
    display_basis: displayBasis,
    shipping_status: shippingStatus,
    required_total_twd: requiredTotal,
    price_basis: { amount_basis: amountBasis, quantity: 1, coupon_discount_basis: discountBasis },
    history: {
      before_coupon: history(rawHistory.before_coupon, identity, "history.before_coupon", false),
      confirmed_after_coupon: history(rawHistory.confirmed_after_coupon, identity, "history.confirmed_after_coupon", true)
    }
  };
}

export const isConfirmedCouponStatus = (status: CouponStatus) => status === "CONFIRMED_APPLICABLE";
