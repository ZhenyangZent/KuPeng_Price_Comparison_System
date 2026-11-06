import http from "node:http";

const product = {
  id: "p_a06_fixture",
  title: "SYNTHETIC TEST FIXTURE｜防風外套",
  variant_signature: "variant:SKU-XL-42|min_qty:1",
  last_observed_price_twd: 599,
  last_observed_at: "2026-11-04T02:00:00Z",
  observed_days: 2,
  sample_days_m7: 2,
  sample_days_m30: 2,
  sample_days_m90: 2,
  coverage: { basis: "COMPLETED_CALENDAR_DAYS", timezone: "Asia/Taipei", m7: { sample_days: 2, status: "LOW" }, m30: { sample_days: 2, status: "LOW" }, m90: { sample_days: 2, status: "LOW" } },
  shipping_status: "UNKNOWN",
  stock_status: "UNKNOWN",
  price_basis: "GENERAL_OBSERVED",
  source_price_basis: "UNIT_DISPLAYED",
  identity_state: "EXACT",
  quality_flags: ["PRICE_IS_USER_OBSERVED_NOT_CHECKOUT_TOTAL", "SHIPPING_UNKNOWN"],
  thumbnail: null
};
const history = [
  { observed_at: "2026-11-03T02:00:00Z", price_twd: 699, source_type: "USER_ENTERED", source_id: "a06-test-1" },
  { observed_at: "2026-11-04T02:00:00Z", price_twd: 599, source_type: "USER_FILE", source_id: "a06-test-2" }
];
const envelope = { schema_version: "CDH-WEB-CONTRACT-V2", contract_compatibility: ["CDH-WEB-CONTRACT-V1"], data_source_status: "USER_RECORDED_ONLY", data_classification: "USER_RECORDED" };
const affiliate = { state: "UNCONFIGURED", click_url: null, verified_product_match: false, bound_product_id: null };

function send(response, status, body) {
  const payload = Buffer.from(`${JSON.stringify(body)}\n`, "utf8");
  response.writeHead(status, { "content-type": "application/json; charset=utf-8", "content-length": payload.length, "cache-control": "no-store", "x-content-type-options": "nosniff" });
  response.end(payload);
}

const server = http.createServer((request, response) => {
  if (request.method !== "GET") return send(response, 405, { ...envelope, error: { code: "METHOD_NOT_ALLOWED", detail: "GET required" } });
  const url = new URL(request.url ?? "/", "http://127.0.0.1:8765");
  if (url.pathname === "/api/v2/products") {
    const query = (url.searchParams.get("q") ?? "").toLocaleLowerCase("zh-Hant");
    const items = !query || `${product.title} ${product.id} ${product.variant_signature}`.toLocaleLowerCase("zh-Hant").includes(query) ? [product] : [];
    return send(response, 200, { ...envelope, items, page: Number(url.searchParams.get("page") ?? 1), limit: Number(url.searchParams.get("limit") ?? 20), total: items.length });
  }
  if (url.pathname === `/api/v2/products/${product.id}`) {
    return send(response, 200, {
      ...envelope,
      product,
      offers: [{ offer_id: "o_a07_fixture", seller_id: "SELLER-TEST", sku_id: "SKU-XL-42", product_id: "p_a06_fixture", minimum_purchase_quantity: 1, item_condition: "UNKNOWN", item_condition_source: "NOT_RECORDED", price_basis: "GENERAL_OBSERVED", source_price_basis: "UNIT_DISPLAYED", identity_state: "EXACT" }],
      history,
      observation_period_min_twd: 599,
      observation_period_label: "觀測期間最低價",
      affiliate
    });
  }
  if (url.pathname === `/api/v2/products/${product.id}/affiliate`) return send(response, 200, { ...envelope, product_id: product.id, affiliate });
  return send(response, 404, { ...envelope, error: { code: "NOT_FOUND", detail: "product not found" } });
});

server.on("error", (error) => { console.error(error); process.exitCode = 1; });
server.listen(8765, "127.0.0.1", () => console.log("A07_V2_STUB_READY http://127.0.0.1:8765"));
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => server.close(() => process.exit(0)));
