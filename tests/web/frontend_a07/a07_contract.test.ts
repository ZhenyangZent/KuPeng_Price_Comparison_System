import {describe,expect,it} from "vitest";
import {SCHEMA_VERSION} from "../../../apps/price-web/frontend/src/types";
import {SYNTHETIC_DETAILS} from "../../../apps/price-web/frontend/src/fixtures";
import {detailFreshness,detailSku,toProductListView} from "../../../apps/price-web/frontend/src/uiAdapter";
import {safeAffiliateUrl} from "../../../apps/price-web/frontend/src/affiliate";
describe("A07 role-path acceptance",()=>{
 it("binds to frozen B06 V2",()=>expect(SCHEMA_VERSION).toBe("CDH-WEB-CONTRACT-V2"));
 it("keeps same-title SKUs separate",()=>{const same=SYNTHETIC_DETAILS.filter(x=>x.product.title.includes("無線耳機"));expect(same).toHaveLength(2);expect(new Set(same.map(detailSku)).size).toBe(2);});
 it("does not turn a zero observed price into free shipping",()=>{const d=SYNTHETIC_DETAILS.find(x=>x.product.last_observed_price_twd===0)!;const view=toProductListView(d.product);expect(view.price).toBe(0);expect(view.shipping).toBe("UNKNOWN");});
 it("keeps no-price as null",()=>expect(SYNTHETIC_DETAILS.find(x=>x.history.length===0)!.product.last_observed_price_twd).toBeNull());
 it("marks stale only from the quality flag",()=>expect(detailFreshness(SYNTHETIC_DETAILS.find(x=>x.product.id==="syn-cable")!)).toBe("STALE"));
 it("fails affiliate CTA closed without approved policy",()=>{const d=SYNTHETIC_DETAILS[0];expect(safeAffiliateUrl(d.product.id,d.offers[0],d.affiliate)).toBeNull();});
});
