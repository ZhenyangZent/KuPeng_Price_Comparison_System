import type { B10DetailResponse, B10Product } from "./b10WireTypes";

const statusLabels: Record<B10Product["coupon"]["status"], string> = {
  CONFIRMED_APPLICABLE: "已確認適用",
  CLAIM_REQUIRED: "需先領券，尚未確認",
  UNVERIFIED: "優惠資格未驗證",
  INELIGIBLE: "目前資格不適用",
  EXPIRED: "優惠券已過期",
  UNKNOWN: "優惠券條件未知",
  NONE: "未提供優惠券"
};

export interface B10CouponView {
  primaryPrice: number | null;
  primaryLabel: "已確認券後商品價" | "券前商品價" | "價格未知";
  confirmed: boolean;
  couponStatusLabel: string;
  minimumSpend: number | null;
  checkoutTotalKnown: boolean;
  sourceUsable: boolean;
}

export function adaptB10Product(product: B10Product): B10CouponView {
  const confirmed = product.display_basis === "CONFIRMED_COUPON";
  const statusLabel = !confirmed && product.coupon.status === "CONFIRMED_APPLICABLE" && product.coupon.evaluation_reasons.includes("COUPON_NOT_CURRENTLY_VALID")
    ? "優惠券已過期／目前不可用"
    : statusLabels[product.coupon.status];
  return {
    primaryPrice: product.display_price_twd,
    primaryLabel: confirmed ? "已確認券後商品價" : product.display_basis === "BASE_PRICE" ? "券前商品價" : "價格未知",
    confirmed,
    couponStatusLabel: statusLabel,
    minimumSpend: product.minimum_item_spend_twd,
    checkoutTotalKnown: product.required_total_twd !== null,
    sourceUsable: product.source_permission.allowed
  };
}

export function detailTruncationWarning(detail: B10DetailResponse): string | null {
  const labels: string[] = [];
  if (detail.history_quality.before_coupon.truncated) labels.push("券前歷史");
  if (detail.history_quality.confirmed_after_coupon.truncated) labels.push("券後歷史");
  return labels.length ? `${labels.join("、")}已達 API 裁切上限；畫面只代表回傳的 raw observations。` : null;
}
