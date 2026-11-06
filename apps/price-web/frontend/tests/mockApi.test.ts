import {describe,expect,it} from "vitest";import {getProductDetail,searchProducts} from "../src/mockApi";
describe("A07 V2 synthetic fixture",()=>{
 it("returns explicit synthetic V2 classification",async()=>{const r=await searchProducts("SYN-EARBUD");expect(r.schema_version).toBe("CDH-WEB-CONTRACT-V2");expect(r.data_source_status).toBe("SYNTHETIC_FIXTURE_ONLY");expect(r.total).toBe(2);});
 it("keeps same-name SKUs and seller identities separate",async()=>{const a=await getProductDetail("syn-earbuds-black"),b=await getProductDetail("syn-earbuds-white");expect(a.product.title).toBe(b.product.title);expect(a.offers[0].sku_id).not.toBe(b.offers[0].sku_id);expect(a.offers[0].seller_id).not.toBe(b.offers[0].seller_id);});
 it("keeps zero distinct from absent price",async()=>{expect((await getProductDetail("syn-earbuds-white")).product.last_observed_price_twd).toBe(0);expect((await getProductDetail("syn-empty")).product.last_observed_price_twd).toBeNull();});
 it("marks stale data from evidence only",async()=>{expect((await getProductDetail("syn-cable")).product.quality_flags).toContain("STALE_LAST_OBSERVATION");});
});
