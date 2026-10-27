import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { LandPriceForecastSection } from "@/services/api";
import LandPriceForecast from "./LandPriceForecast";

const AVAILABLE: LandPriceForecastSection = {
  data_kind: "forecast",
  development_code: "Residential (Non-Landed)",
  scope: "Awarded GLS sites in one development category only.",
  forecast_method: "persistence",
  is_nominal: true,
  latest_award_year: 2025,
  latest_median_price_per_gfa: 14405.06,
  latest_site_count: 11,
  latest_year_low_sample: false,
  forecast_year: 2027,
  forecast_value: 14405.06,
  current_year_excluded: 2026,
  annual_medians: [
    { award_year: 2025, median_price_per_gfa: 14405.06, site_count: 11, low_sample: false },
    { award_year: 2024, median_price_per_gfa: 11082.0, site_count: 8, low_sample: false },
    { award_year: 2021, median_price_per_gfa: 12031.33, site_count: 1, low_sample: true },
  ],
  evaluation: {
    status: "ok",
    window: "all_completed_years",
    test_periods: 28,
    window_start: 1995,
    window_end: 2025,
    train_years_before_first_test: 3,
    methods: [
      { method: "persistence", mae: 1092.73, test_periods: 28 },
      { method: "expanding_median", mae: 3399.12, test_periods: 28 },
      { method: "rolling_median_3", mae: 1428.14, test_periods: 28 },
    ],
    note: "One-year-ahead walk-forward.",
    insufficient_reason: null,
  },
  evaluation_recent: {
    status: "ok",
    window: "recent_years",
    test_periods: 7,
    window_start: 2019,
    window_end: 2025,
    train_years_before_first_test: 3,
    methods: [
      { method: "persistence", mae: 1685.98, test_periods: 7 },
      { method: "expanding_median", mae: 1928.55, test_periods: 7 },
      { method: "rolling_median_3", mae: 2355.99, test_periods: 7 },
    ],
    note: "One-year-ahead walk-forward, recent window.",
    insufficient_reason: null,
  },
  eligibility: { sites_total: 972, sites_eligible: 214 },
  warnings: ["6 eligible site(s) awarded in 2026 or later were excluded: the year is still in progress."],
  limitations: [
    "Prices are NOMINAL successful tender prices as published; no inflation adjustment is applied.",
    "This is a persistence baseline, not an ML prediction, not a guaranteed price.",
  ],
};

const UNAVAILABLE: LandPriceForecastSection = {
  ...AVAILABLE,
  data_kind: "unavailable",
  forecast_value: null,
  forecast_year: null,
  latest_award_year: null,
  latest_median_price_per_gfa: null,
  latest_site_count: null,
  annual_medians: [],
  warnings: [],
  limitations: ["Insufficient history for a baseline estimate: 1 completed award year(s) with eligible sites; at least 2 required."],
};

describe("LandPriceForecast", () => {
  it("renders the baseline estimate, nominal disclaimer and both evaluation windows when available", () => {
    render(<LandPriceForecast section={AVAILABLE} />);
    expect(screen.getAllByText(/HISTORICAL LAND TENDER PRICE/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("BASELINE ESTIMATE 2027")).toBeTruthy();
    // persistence carries the same median forward: headline cards + 2025 table row
    expect(screen.getAllByText("$14,405").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/Nominal prices, not inflation-adjusted/i)).toBeTruthy();
    // the in-progress year is named and kept distinct from the target
    expect(screen.getByText(/in-progress 2026 excluded/i)).toBeTruthy();
    expect(screen.getByText(/carried forward to 2027/i)).toBeTruthy();
    // method rows appear in both windows
    expect(screen.getAllByText("persistence").length).toBe(2);
    expect(screen.getAllByText("expanding_median").length).toBe(2);
    expect(screen.getByText("1,092.73")).toBeTruthy();
    expect(screen.getByText("3,399.12")).toBeTruthy();
    expect(screen.getByText(/28 one-year-ahead test period/i)).toBeTruthy();
    // recent window renders alongside the full-history window
    expect(screen.getByText(/FULL HISTORY/i)).toBeTruthy();
    expect(screen.getByText(/RECENT 10 YEARS/i)).toBeTruthy();
    expect(screen.getByText("1,685.98")).toBeTruthy();
    expect(screen.getByText(/7 one-year-ahead test period/i)).toBeTruthy();
  });

  it("renders per-year medians with site counts and low-sample disclosure", () => {
    render(<LandPriceForecast section={AVAILABLE} />);
    expect(screen.getByText("2021")).toBeTruthy();
    expect(screen.getAllByText(/low sample/i).length).toBeGreaterThan(0);
    expect(screen.getByText("$12,031")).toBeTruthy();
    expect(screen.getByText("$11,082")).toBeTruthy();
  });

  it("renders warnings such as the excluded in-progress year", () => {
    render(<LandPriceForecast section={AVAILABLE} />);
    expect(screen.getByText(/6 eligible site\(s\) awarded in 2026 or later were excluded/i)).toBeTruthy();
  });

  it("renders an explicit unavailable state with no invented values", () => {
    render(<LandPriceForecast section={UNAVAILABLE} />);
    expect(screen.getByText(/No baseline estimate is available/i)).toBeTruthy();
    expect(screen.getByText(/rather than reporting a zero/i)).toBeTruthy();
    expect(screen.queryByText("BASELINE ESTIMATE 2026")).toBeNull();
  });

  it("renders the unavailable state when the section itself is missing", () => {
    render(<LandPriceForecast section={null} />);
    expect(screen.getByText(/price-forecast section is unavailable/i)).toBeTruthy();
  });

  it("renders the insufficient-history evaluation note when the walk-forward cannot run", () => {
    const insufficientEval = {
      status: "insufficient_history" as const,
      window: "all_completed_years",
      test_periods: null,
      window_start: null,
      window_end: null,
      train_years_before_first_test: null,
      methods: [],
      note: "",
      insufficient_reason: "Only 3 completed award year(s) with an eligible median; a walk-forward comparison needs at least 4.",
    };
    const thin: LandPriceForecastSection = {
      ...AVAILABLE,
      evaluation: insufficientEval,
      evaluation_recent: { ...insufficientEval, window: "recent_years" },
    };
    render(<LandPriceForecast section={thin} />);
    expect(screen.getAllByText(/Only 3 completed award year\(s\)/i).length).toBe(2);
    expect(screen.queryByText("expanding_median")).toBeNull();
    expect(screen.queryByText("persistence")).toBeNull();
  });
});
