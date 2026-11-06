import {afterEach,describe,expect,it,vi} from "vitest";import {localApiClient} from "../src/localApi";import {SYNTHETIC_DETAILS} from "../src/fixtures";
afterEach(()=>vi.unstubAllGlobals());
const env={schema_version:"CDH-WEB-CONTRACT-V2",contract_compatibility:["CDH-WEB-CONTRACT-V1"],data_source_status:"USER_RECORDED_ONLY",data_classification:"USER_RECORDED"};
describe("A07 same-origin V2 client",()=>{
 it("uses only proxy V2 endpoint with no fallback duplicate request",async()=>{const fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>({...env,items:[],page:1,limit:100,total:0})});vi.stubGlobal("fetch",fetch);await localApiClient.searchProducts("SKU-X",1,100);expect(fetch).toHaveBeenCalledTimes(1);expect(fetch.mock.calls[0][0]).toContain("/cdh-local-api/api/v2/products?");});
 it("rejects wrong schema",async()=>{vi.stubGlobal("fetch",vi.fn().mockResolvedValue({ok:true,json:async()=>({...env,schema_version:"WRONG",items:[],page:1,limit:20,total:0})}));await expect(localApiClient.searchProducts("")).rejects.toThrow(/CDH-WEB-CONTRACT-V2/);});
 it("deduplicates an identical in-flight search",async()=>{let resolve!:Function;const fetch=vi.fn(()=>new Promise(r=>{resolve=r;}));vi.stubGlobal("fetch",fetch);const a=localApiClient.searchProducts("same"),b=localApiClient.searchProducts("same");resolve({ok:true,json:async()=>({...env,items:[],page:1,limit:20,total:0})});await Promise.all([a,b]);expect(fetch).toHaveBeenCalledTimes(1);});
});
