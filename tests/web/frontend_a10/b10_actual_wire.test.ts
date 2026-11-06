import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { assertSameB10Snapshot, parseB10Detail, parseB10Search } from "../../../apps/price-web/frontend/src/b10RuntimeSchema";

const sourceEvidenceRoot = path.resolve("input/orchestrator_bundles/UNIFIED_CONTINUOUS_20261105_R07/extracted/EVIDENCE");
const packagedEvidenceRoot = path.resolve("input_contract/EVIDENCE");
const evidenceRoot = existsSync(sourceEvidenceRoot) ? sourceEvidenceRoot : packagedEvidenceRoot;
const searchRaw = JSON.parse(readFileSync(path.join(evidenceRoot, "B10_REAL_SEARCH.json"), "utf8"));
const detailRaw = JSON.parse(readFileSync(path.join(evidenceRoot, "B10_REAL_DETAIL.json"), "utf8"));

describe("A10 exact R07 B10 evidence acceptance", () => {
  it("accepts the central Search and Detail captures as envelopes", () => {
    const search = parseB10Search(searchRaw), detail = parseB10Detail(detailRaw, "series-1", search.items[0]);
    assertSameB10Snapshot(search, detail);
    expect([search.items[0].display_price_twd, detail.product.before_coupon_price_twd]).toEqual([49, 99]);
  });

  it("continues rejecting the old A09 product-only and envelope-as-product calls", () => {
    expect(() => parseB10Search(searchRaw.items[0])).toThrow(/只接受|items/);
    expect(() => parseB10Detail(detailRaw.product, "series-1")).toThrow(/只接受|product/);
  });

  it("binds history to the requested series and current exact identity", () => {
    const search = parseB10Search(searchRaw);
    const crossSeries = structuredClone(detailRaw); crossSeries.history.confirmed_after_coupon[0].series_key = "other";
    expect(() => parseB10Detail(crossSeries, "series-1", search.items[0])).toThrow(/series_key/);
    const crossSku = structuredClone(detailRaw); crossSku.product.series_identity.sku_id = "other";
    expect(() => parseB10Detail(crossSku, "series-1", search.items[0])).toThrow(/精確商品身分/);
  });

  it("does not require the old invented price_basis.quantity field", () => {
    expect(searchRaw.items[0]).not.toHaveProperty("price_basis");
    expect(() => parseB10Search(searchRaw)).not.toThrow();
  });
});
