import type { ProductDetailResponse, ProductSummary } from "./types";
export interface ProductListView {
  id:string; title:string; skuLabel:string; price:number|null; observedAt:string|null; observedDays:number;
  shipping:string; stale:boolean; noPrice:boolean;
  priceUnavailable:boolean; dealEligible:boolean;
}
export const toProductListView=(p:ProductSummary):ProductListView=>({
  id:p.id,title:p.title,skuLabel:p.variant_signature,price:p.last_observed_price_twd,observedAt:p.last_observed_at,
  observedDays:p.observed_days,shipping:p.shipping_status,stale:p.quality_flags.includes("STALE_LAST_OBSERVATION")||p.quality_flags.includes("STALE_OR_MISSING_LAST_OBSERVATION"),noPrice:p.last_observed_price_twd===null,priceUnavailable:p.price_basis==="UNAVAILABLE",dealEligible:p.price_basis==="GENERAL_OBSERVED"&&p.last_observed_price_twd!==null
});
export const detailFreshness=(d:ProductDetailResponse)=>d.product.quality_flags.includes("STALE_LAST_OBSERVATION")?"STALE" as const:"CURRENT" as const;
export const detailSku=(d:ProductDetailResponse)=>d.offers[0]?.sku_id??"UNKNOWN";
