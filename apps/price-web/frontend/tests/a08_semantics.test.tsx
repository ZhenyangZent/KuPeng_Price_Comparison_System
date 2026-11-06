import {render,screen,waitFor} from "@testing-library/react";
import {describe,expect,it} from "vitest";
import App from "../src/App";
import {safeAffiliateUrl} from "../src/affiliate";
import {SYNTHETIC_DETAILS} from "../src/fixtures";
import {parseDetailV2,parseSearchV2} from "../src/runtimeSchema";
const unavailable=SYNTHETIC_DETAILS.find(x=>x.product.price_basis==="UNAVAILABLE")!;
const valid=SYNTHETIC_DETAILS.find(x=>x.product.price_basis==="GENERAL_OBSERVED")!;
describe("A08 unavailable and raw-history semantics",()=>{
 it("keeps valid and unavailable products on the same page",()=>{const parsed=parseSearchV2({...valid,items:[valid.product,unavailable.product],page:1,limit:20,total:2});expect(parsed.items.map(x=>x.price_basis)).toEqual(["GENERAL_OBSERVED","UNAVAILABLE"]);});
 it("accepts raw minimum but rejects daily median substitution",()=>{const base={...valid,history:[{observed_at:"2026-11-01T01:00:00Z",price_twd:10,source_type:"SYNTHETIC",source_id:"1"},{observed_at:"2026-11-01T02:00:00Z",price_twd:20,source_type:"SYNTHETIC",source_id:"2"},{observed_at:"2026-11-01T03:00:00Z",price_twd:30,source_type:"SYNTHETIC",source_id:"3"}]};expect(parseDetailV2({...base,observation_period_min_twd:10},valid.product.id).observation_period_min_twd).toBe(10);expect(()=>parseDetailV2({...base,observation_period_min_twd:20},valid.product.id)).toThrow(/\u4e0d\u4e00\u81f4/);});
 it("blocks affiliate even under a synthetic approved policy when price is unavailable",()=>{const aff={...unavailable.affiliate,state:"VERIFIED" as const,click_url:"https://affiliate.test/item",verified_product_match:true,bound_product_id:unavailable.product.id,bound_sku_id:null,provider_id:"provider",official_host_verified:true,verified_variant_match:true,verified_seller_match:true,valid_from:"2026-01-01T00:00:00Z",valid_until:"2027-01-01T00:00:00Z",tw_disclosure:"測試"};expect(safeAffiliateUrl(unavailable.product.id,unavailable.offers[0],aff,{approved_provider_id:"provider",official_hosts:["affiliate.test"]},new Date("2026-11-05T00:00:00Z"))).toBeNull();});
 it("renders unavailable without breaking other recorded results",async()=>{history.replaceState({},"","/?mode=synthetic&product=syn-empty");render(<App/>);expect(await screen.findByText("此商品沒有適用、可比的價格。")).toBeInTheDocument();expect(screen.getAllByText("價格不可用").length).toBeGreaterThan(0);expect(screen.getByText("SYNTHETIC｜USB-C 充電線")).toBeInTheDocument();expect(screen.getByRole("button",{name:"尚未取得可驗證的專屬連結"})).toBeDisabled();});
 it("recovers an invalid shared product id to a recorded identity",async()=>{history.replaceState({},"","/?mode=synthetic&product=wrong-sku");render(<App/>);await waitFor(()=>expect(location.search).not.toContain("wrong-sku"));expect(screen.getByText(/4 個已收錄商品身分/)).toBeInTheDocument();});
});
