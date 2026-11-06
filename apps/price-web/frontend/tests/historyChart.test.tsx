import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HistoryChart } from "../src/HistoryChart";

describe("HistoryChart", () => {
  it("reports real sample count and tracked-period minimum", () => {
    render(<HistoryChart history={[{ observed_at: "2026-11-01T00:00:00Z", price_twd: 400, source_type: "SYNTHETIC", source_id: "a" }, { observed_at: "2026-11-03T00:00:00Z", price_twd: 320, source_type: "SYNTHETIC", source_id: "b" }]} />);
    expect(screen.getByRole("img")).toHaveAccessibleName(/2 筆實際觀測/);
    expect(screen.getByText(/觀測期間最低/)).toHaveTextContent("NT$ 320");
  });
  it("does not draw an invented zero when history is empty", () => {
    render(<HistoryChart history={[]} />);
    expect(screen.getByRole("status")).toHaveTextContent("空白不會補成 NT$0");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
