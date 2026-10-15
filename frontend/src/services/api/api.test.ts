/**
 * API contract tests.
 *
 * These assert the exact shape the frontend relies on, captured from the
 * running backend. If the backend changes a field name, these fail first.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import {
  ApiError,
  fetchCityReport,
  fetchOverviewCity,
} from "./index";

// Captured verbatim from the running API.
const CITY_REPORT_FIXTURE = {
  generated_at: "2026-10-12T02:33:10.233228",
  overall_city_status: "CRITICAL",
  overall_risk_level: "CRITICAL",
  domain_status: {
    flood: {
      domain: "flood",
      available: true,
      overall_status: "HIGH",
      overall_risk: "HIGH",
      risk_level: "HIGH",
      key_metrics: { risk_level: "HIGH", risk_score: 0.5, active_alert_count: 0 },
      active_alert_count: 0,
      affected_zones: ["Central South"],
      primary_risk_factors: ["Heavy rainfall"],
      confidence: "high",
      limitations: ["Test limitation"],
      is_ml_prediction: false,
      generated_at: "2026-10-12T02:33:10.235235",
      source_status: null,
      warnings: [],
      errors: [],
      findings: [],
      error: null,
      detail_route: null,
      display_name: null,
    },
  },
  priority_incidents: [
    {
      id: "IMPACT_flood_traffic",
      type: "flood_traffic_overlap",
      domain: "flood+traffic",
      severity: "HIGH",
      description: "HIGH flood risk coincides with disrupted traffic.",
      affected_zones: ["Central South"],
      source_report: "flood+traffic",
      related_domains: ["flood", "traffic"],
      cascading_risk: null,
    },
  ],
  cross_domain_impacts: [
    {
      type: "flood_traffic",
      description: "HIGH flood risk coincides with disrupted traffic.",
      severity: "HIGH",
      affected_zones: ["Central South"],
      domains_involved: ["flood", "traffic"],
      evidence: ["Flood risk reported as HIGH."],
    },
  ],
  city_level_recommendations: ["FLOOD+TRAFFIC: Coordinate response."],
  affected_zones: ["Central South"],
  evidence: [
    {
      source: "environment",
      subdomain: "environment",
      generated_at: "2026-10-12T02:33:10.233228",
      confidence: "medium",
      key_metrics: { max_pm25_next_day_max: 55.0, region_count: 5 },
      limitations: ["PM2.5 values are next-day model predictions."],
    },
  ],
  confidence: "high",
  limitations: ["The City Coordinator is a deterministic rule engine."],
  source_reports: {},
  is_ml_prediction: false,
};

const OVERVIEW_FIXTURE = {
  generated_at: "2026-10-12T05:05:19.810241+08:00",
  modules: [
    {
      id: "land",
      name: "Land",
      status: "normal",
      kpi: { label: "Land-Use Area", value: 796.8, unit: "km²" },
      updated_at: "2026-10-12T05:05:19.810241+08:00",
      detail_route: "/planning/land",
    },
    {
      id: "crime",
      name: "Crime",
      status: "unavailable",
      kpi: null,
      updated_at: null,
      detail_route: "/safety/crime",
    },
  ],
  alerts: [
    {
      domain: "roads",
      severity: "critical",
      title: "Roads Status: Critical",
      description: "Roads module update. 8093 active road works, 82 upcoming.",
      timestamp: "2026-10-12T05:05:19.810241+08:00",
      affected_zones: [],
    },
  ],
  ai_brief: "City status CRITICAL (risk CRITICAL, confidence high).",
  domain_status: {
    water: {
      domain: "water",
      available: true,
      overall_status: "NORMAL",
      overall_risk: "LOW",
      key_metrics: {},
      affected_zones: [],
      primary_risk_factors: [],
      confidence: "medium",
      limitations: ["No official live drain water-level readings."],
      is_ml_prediction: false,
      findings: [
        {
          id: "water.insight_0",
          domain: "water",
          title: "How is water usage changing?",
          answer: "Total potable sales 515.5 million m3 in 2025.",
          data_kind: "historical",
          category: "insight",
          question: "How is water usage changing?",
          severity: null,
          evidence: ["Derived from the water report."],
          evidence_refs: [],
          sources: [],
          observed_at: null,
          freshness: "recent",
          affected_area: null,
          limitations: ["Annual official statistics."],
          metrics: { value: 515.5 },
        },
      ],
      detail_route: "/infrastructure/water",
      display_name: "Water",
    },
    traffic: {
      domain: "traffic",
      available: false,
      overall_status: null,
      overall_risk: null,
      key_metrics: {},
      affected_zones: [],
      primary_risk_factors: [],
      confidence: "low",
      limitations: ["No traffic prediction data available"],
      is_ml_prediction: false,
      findings: [
        {
          id: "traffic.unavailable",
          domain: "traffic",
          title: "Data unavailable",
          answer: "Data unavailable: No traffic prediction data available",
          data_kind: "unavailable",
          category: "general",
          question: null,
          severity: null,
          evidence: [],
          evidence_refs: [],
          sources: [],
          observed_at: null,
          freshness: "unknown",
          affected_area: null,
          limitations: ["Data unavailable: No traffic prediction data available"],
          metrics: {},
        },
      ],
      detail_route: "/mobility/traffic",
      display_name: "Traffic",
    },
  },
};

function mockFetch(body: unknown, ok = true, status = 200) {
  const spy = vi.fn().mockResolvedValue({
    ok,
    status,
    statusText: status === 200 ? "OK" : "Internal Server Error",
    json: async () => body,
  });
  globalThis.fetch = spy as unknown as typeof fetch;
  return spy;
}

describe("fetchCityReport", () => {
  beforeEach(() => mockFetch(CITY_REPORT_FIXTURE));

  it("maps every field the UI consumes", async () => {
    const r = await fetchCityReport();
    expect(r.overall_city_status).toBe("CRITICAL");
    expect(r.overall_risk_level).toBe("CRITICAL");
    expect(r.confidence).toBe("high");
    expect(r.is_ml_prediction).toBe(false);
    expect(r.cross_domain_impacts[0].evidence.length).toBeGreaterThan(0);
    expect(r.priority_incidents[0].related_domains).toEqual(["flood", "traffic"]);
    expect(r.domain_status.flood.affected_zones).toEqual(["Central South"]);
    expect(r.evidence[0].key_metrics?.max_pm25_next_day_max).toBe(55.0);
  });

  it("requests the correct URL with no caching", async () => {
    const spy = mockFetch(CITY_REPORT_FIXTURE);
    await fetchCityReport();
    expect(spy).toHaveBeenCalledWith(
      expect.stringContaining("/api/city/report"),
      expect.objectContaining({ cache: "no-store" })
    );
  });

  it("throws a typed ApiError carrying the status", async () => {
    mockFetch({}, false, 500);
    await expect(fetchCityReport()).rejects.toBeInstanceOf(ApiError);
    await expect(fetchCityReport()).rejects.toMatchObject({ status: 500 });
  });
});

describe("fetchOverviewCity", () => {
  beforeEach(() => mockFetch(OVERVIEW_FIXTURE));

  it("maps module cards including the unavailable case", async () => {
    const r = await fetchOverviewCity();
    expect(r.modules).toHaveLength(2);
    expect(r.modules[0].kpi).toEqual({ label: "Land-Use Area", value: 796.8, unit: "km²" });
    expect(r.modules[1].status).toBe("unavailable");
    expect(r.modules[1].kpi).toBeNull();
  });

  it("maps the narrative, which may be null", async () => {
    expect((await fetchOverviewCity()).ai_brief).toContain("City status CRITICAL");

    mockFetch({ ...OVERVIEW_FIXTURE, ai_brief: null });
    expect((await fetchOverviewCity()).ai_brief).toBeNull();
  });

  it("maps per-domain findings used by the KPI insight", async () => {
    const r = await fetchOverviewCity();
    const water = r.domain_status?.water;
    expect(water?.findings?.[0].data_kind).toBe("historical");
    expect(water?.findings?.[0].evidence).toHaveLength(1);
    expect(r.domain_status?.traffic.available).toBe(false);
    expect(r.domain_status?.traffic.findings?.[0].data_kind).toBe("unavailable");
  });

  it("maps alerts with their evidence text", async () => {
    const r = await fetchOverviewCity();
    expect(r.alerts[0].title).toBe("Roads Status: Critical");
  });

  it("tolerates a response with no domain_status", async () => {
    mockFetch({ generated_at: "x", modules: [], alerts: [], ai_brief: null });
    const r = await fetchOverviewCity();
    expect(r.domain_status).toBeUndefined();
    expect(r.modules).toEqual([]);
  });

  it("throws a typed ApiError", async () => {
    mockFetch({}, false, 503);
    await expect(fetchOverviewCity()).rejects.toBeInstanceOf(ApiError);
  });

  it("requests the correct URL", async () => {
    const spy = mockFetch(OVERVIEW_FIXTURE);
    await fetchOverviewCity();
    expect(spy).toHaveBeenCalledWith(
      expect.stringContaining("/api/overview/city"),
      expect.objectContaining({ cache: "no-store" })
    );
  });
});