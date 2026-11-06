import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CouponApiExperience } from "../src/CouponApiExperience";

const emptySearch = {
  schema_version: "CDH-B10-COUPON-HISTORY-API-V4",
  data_classification: "SYNTHETIC_FIXTURE",
  data_version: "a16-empty",
  page: 1,
  limit: 20,
  total: 0,
  items: [],
};

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("shows three mutually distinct price classifications and all first-use entry points", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(emptySearch), {
    status: 200,
    headers: { "content-type": "application/json" },
  })));
  render(<CouponApiExperience/>);

  const guide = screen.getByRole("region", { name: "價格資料分類說明" });
  expect(guide).toHaveTextContent("SYNTHETIC DEMO");
  expect(guide).toHaveTextContent("PRIVATE USER-REPORTED");
  expect(guide).toHaveTextContent("PLATFORM CONFIRMED");
  expect(guide).toHaveTextContent("不是平台驗證");
  expect(guide).toHaveTextContent("證據完整才成立");
  expect(screen.getByRole("region", { name: "CSV JSON 批次匯入預覽" })).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "私人手動價格記錄" })).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "已儲存的私人商品" })).toBeInTheDocument();
  expect(screen.getByRole("search", { name: "搜尋已儲存的私人商品" })).toBeInTheDocument();
});
