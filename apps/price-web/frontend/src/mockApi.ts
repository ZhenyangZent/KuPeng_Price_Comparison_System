import { SYNTHETIC_DETAILS } from "./fixtures";
import { SCHEMA_VERSION, type AffiliateResponse, type PriceDataClient, type ProductDetailResponse, type SearchResponse } from "./types";

const delay = (milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

export class MockApiError extends Error {
  constructor(public readonly code: "NOT_FOUND" | "INVALID_QUERY", detail: string) {
    super(detail);
  }
}

export async function searchProducts(query: string, page = 1, limit = 20): Promise<SearchResponse> {
  await delay(25);
  if (!Number.isInteger(page) || page < 1 || !Number.isInteger(limit) || limit < 1 || limit > 100) {
    throw new MockApiError("INVALID_QUERY", "page/limit 超出允許範圍");
  }
  const normalized = query.trim().toLocaleLowerCase("zh-Hant");
  const matched = SYNTHETIC_DETAILS.map((entry) => entry.product).filter((product) =>
    !normalized || `${product.title} ${product.variant_signature}`.toLocaleLowerCase("zh-Hant").includes(normalized)
  );
  const start = (page - 1) * limit;
  return {
    schema_version: SCHEMA_VERSION,
    items: structuredClone(matched.slice(start, start + limit)),
    page,
    limit,
    total: matched.length,
    contract_compatibility: ["CDH-WEB-CONTRACT-V1"],
    data_source_status: "SYNTHETIC_FIXTURE_ONLY",
    data_classification: "SYNTHETIC_DEMO_ONLY",
  };
}

export async function getProductDetail(productId: string): Promise<ProductDetailResponse> {
  await delay(20);
  const found = SYNTHETIC_DETAILS.find((entry) => entry.product.id === productId);
  if (!found) throw new MockApiError("NOT_FOUND", "找不到指定商品");
  return structuredClone(found);
}

export async function getAffiliate(productId: string): Promise<AffiliateResponse> {
  const detail = await getProductDetail(productId);
  return { schema_version: SCHEMA_VERSION, contract_compatibility: ["CDH-WEB-CONTRACT-V1"], data_source_status: "SYNTHETIC_FIXTURE_ONLY", data_classification: "SYNTHETIC_DEMO_ONLY", product_id: productId, affiliate: detail.affiliate };
}

export const syntheticApiClient: PriceDataClient = {
  mode: "SYNTHETIC_DEMO",
  searchProducts,
  getProductDetail
};
