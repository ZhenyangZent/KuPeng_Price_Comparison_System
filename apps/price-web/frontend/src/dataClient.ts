import { localApiClient } from "./localApi";
import { syntheticApiClient } from "./mockApi";
import type { DataMode, PriceDataClient } from "./types";

export function createPriceDataClient(mode: DataMode): PriceDataClient {
  return mode === "SYNTHETIC_DEMO" ? syntheticApiClient : localApiClient;
}
