/**
 * City Overview page-level integration test.
 *
 * Verifies that Overview is cheap by default and the full coordinator report
 * runs only after an explicit user request.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import OverviewPage from "./page";

const OVERVIEW_OK = {
  generated_at: "2026-10-12T05:05:19.810241+08:00",
  modules: [
    {
      id: "land",
      name: "Land",
      status: "normal",
      kpi: { label: "Land-Use Area", value: 796.8, unit: "km²" },
      updated_at: null,
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
  alerts: [],
  ai_brief: "City status DISRUPTED (risk HIGH, confidence high).",
  city_assessment_ready: true,
  domain_status: {
    land: {
      domain: "land",
      available: true,
      overall_status: "NORMAL",
      overall_risk: "LOW",
      key_metrics: {},
      affected_zones: [],
      primary_risk_factors: [],
      confidence: "high",
      limitations: [],
      is_ml_prediction: false,
      findings: [
        {
          id: "land.insight_0",
          domain: "land",
          title: "What is the dominant land use?",
          answer: "Residential is the largest group at 140.5 km2.",
          data_kind: "latest_available",
          category: "insight",
          question: "What is the dominant land use?",
          severity: null,
          evidence: ["Derived from the land report."],
          evidence_refs: [],
          sources: [],
          observed_at: null,
          freshness: "recent",
          affected_area: null,
          limitations: [],
          metrics: {},
        },
      ],
      detail_route: "/planning/land",
      display_name: "Land",
    },
  },
};

const CITY_REPORT_OK = {
  generated_at: "2026-10-12T02:33:10.233228",
  overall_city_status: "DISRUPTED",
  overall_risk_level: "HIGH",
  domain_status: {},
  priority_incidents: [],
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
  city_level_recommendations: [],
  affected_zones: ["Central South"],
  evidence: [],
  confidence: "high",
  limitations: [],
  source_reports: {},
  is_ml_prediction: false,
};

type Reply = { ok: boolean; status: number; body: unknown };

function mockEndpoints(replies: Record<string, Reply>) {
  const spy = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    // Order matters: "/api/overview/city" is a substring of
    // "/api/overview/city-narrative", so the longer path must be tested first.
    const key =
      url.includes("/api/city/report")
        ? "/api/city/report"
        : url.includes("/api/overview/city-narrative")
          ? "/api/overview/city-narrative"
          : url.includes("/api/overview/city")
            ? "/api/overview/city"
            : null;
    const reply = key ? replies[key] : undefined;
    if (!reply) throw new Error(`unexpected fetch: ${url}`);
    return {
      ok: reply.ok,
      status: reply.status,
      statusText: String(reply.status),
      json: async () => reply.body,
    } as unknown as Response;
  });
  globalThis.fetch = spy as unknown as typeof fetch;
  return spy;
}

const BOTH_OK: Record<string, Reply> = {
  "/api/city/report": { ok: true, status: 200, body: CITY_REPORT_OK },
  "/api/overview/city": { ok: true, status: 200, body: OVERVIEW_OK },
  "/api/overview/city-narrative": {
    ok: true,
    status: 200,
    body: {
      ai_brief: "City status DISRUPTED (risk HIGH, confidence high).",
      city_assessment_ready: true,
      report_generated_at: "2026-10-12T02:33:10.233228",
    },
  },
};

describe("City Overview page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads only cached Overview summaries on mount", async () => {
    const spy = mockEndpoints(BOTH_OK);
    render(<OverviewPage />);
    await waitFor(() => expect(screen.getByTestId("city-situation")).toBeTruthy());
    expect(screen.queryByTestId("module-detail-strip")).toBeNull();

    const urls = spy.mock.calls.map((c) => String(c[0]));
    expect(urls.filter((u) => u.includes("/api/city/report"))).toHaveLength(0);
    expect(urls.filter((u) => u.includes("/api/overview/city"))).toHaveLength(1);
    expect(screen.getByTestId("request-city-report")).toBeTruthy();
  });

  it("renders the narrative from the overview endpoint", async () => {
    mockEndpoints(BOTH_OK);
    render(<OverviewPage />);
    await waitFor(() =>
      expect(screen.getByTestId("city-situation-narrative").textContent).toContain(
        "Disrupted city status with high overall risk"
      )
    );
  });

  it("renders the coordinator assessment in City Situation", async () => {
    mockEndpoints(BOTH_OK);
    render(<OverviewPage />);
    fireEvent.click(await screen.findByTestId("request-city-report"));
    await waitFor(() =>
      expect(screen.getByTestId("city-status-badge")).toBeTruthy()
    );
    expect(screen.getByTestId("city-affected-zones").textContent).toContain("Central South");
  });

  it("renders a KPI card per module with its domain route", async () => {
    mockEndpoints(BOTH_OK);
    render(<OverviewPage />);
    await waitFor(() => expect(screen.getAllByTestId("domain-kpi-card")).toHaveLength(2));
    const cards = screen.getAllByTestId("domain-kpi-card");
    expect(cards[0].getAttribute("href")).toBe("/planning/land");
    expect(cards[1].getAttribute("href")).toBe("/safety/crime");
  });

  it("opens the KPI insight panel without navigating", async () => {
    mockEndpoints(BOTH_OK);
    render(<OverviewPage />);
    await waitFor(() => expect(screen.getAllByTestId("kpi-insight-button")).toHaveLength(2));

    fireEvent.click(screen.getAllByTestId("kpi-insight-button")[0]);

    await waitFor(() => expect(screen.getByTestId("kpi-insight-panel")).toBeTruthy());
    // The grounded finding is shown, not invented.
    expect(screen.getByTestId("kpi-insight-answer").textContent).toContain(
      "Residential is the largest group"
    );
  });

  it("closes the insight panel again", async () => {
    mockEndpoints(BOTH_OK);
    render(<OverviewPage />);
    await waitFor(() => expect(screen.getAllByTestId("kpi-insight-button")).toHaveLength(2));
    fireEvent.click(screen.getAllByTestId("kpi-insight-button")[0]);
    await waitFor(() => expect(screen.getByTestId("kpi-insight-panel")).toBeTruthy());
    fireEvent.click(screen.getByTestId("kpi-insight-close"));
    await waitFor(() => expect(screen.queryByTestId("kpi-insight-panel")).toBeNull());
  });

  it("keeps KPI cards working when the coordinator fails", async () => {
    mockEndpoints({
      "/api/city/report": { ok: false, status: 500, body: {} },
      "/api/overview/city": { ok: true, status: 200, body: OVERVIEW_OK },
    });
    render(<OverviewPage />);
    fireEvent.click(await screen.findByTestId("request-city-report"));
    await waitFor(() => expect(screen.getByTestId("city-situation-narrative")).toBeTruthy());
    // Overview data still renders.
    expect(screen.getAllByTestId("domain-kpi-card")).toHaveLength(2);
    expect(screen.getByTestId("city-situation-narrative")).toBeTruthy();
  });

  it("does not start the coordinator when the overview endpoint fails", async () => {
    const spy = mockEndpoints({
      "/api/city/report": { ok: true, status: 200, body: CITY_REPORT_OK },
      "/api/overview/city": { ok: false, status: 500, body: {} },
    });
    render(<OverviewPage />);
    await waitFor(() => expect(screen.getByTestId("city-situation-error")).toBeTruthy());
    expect(screen.queryByTestId("risk-signals")).toBeNull();
    expect(screen.getByTestId("city-situation-error")).toBeTruthy();
    expect(spy.mock.calls.filter((c) => String(c[0]).includes("/api/city/report"))).toHaveLength(0);
  });

  it("shows a clear unavailable state when there is no narrative", async () => {
    mockEndpoints({
      "/api/city/report": { ok: true, status: 200, body: CITY_REPORT_OK },
      "/api/overview/city": { ok: true, status: 200, body: { ...OVERVIEW_OK, ai_brief: null } },
    });
    render(<OverviewPage />);
    await waitFor(() =>
      expect(screen.getByTestId("city-situation-unavailable")).toBeTruthy()
    );
    expect(screen.getByTestId("request-city-report")).toBeTruthy();
  });

  it("populates the shared store so map/inspector components can consume it", async () => {
    mockEndpoints(BOTH_OK);
    const { useAppStore } = await import("@/store");
    render(<OverviewPage />);
    fireEvent.click(await screen.findByTestId("request-city-report"));
    await waitFor(() => {
      expect(useAppStore.getState().report?.overall_city_status).toBe("DISRUPTED");
    });
  });
});

describe("on-demand city assessment", () => {
  beforeEach(() => vi.clearAllMocks());

  it("requests the full report and narrative only after explicit action", async () => {
    const spy = mockEndpoints(BOTH_OK);
    render(<OverviewPage />);
    await screen.findByTestId("city-situation-narrative");
    expect(spy.mock.calls.filter((c) => String(c[0]).includes("/api/city/report"))).toHaveLength(0);

    fireEvent.click(screen.getByTestId("request-city-report"));
    await waitFor(() => expect(screen.getByTestId("city-status-badge")).toBeTruthy());
    expect(spy.mock.calls.filter((c) => String(c[0]).includes("/api/city/report"))).toHaveLength(1);
    expect(spy.mock.calls.filter((c) => String(c[0]).includes("/api/overview/city-narrative"))).toHaveLength(1);
  });

  it("keeps Overview usable when an explicitly requested report fails", async () => {
    const spy = mockEndpoints({
      "/api/city/report": { ok: false, status: 503, body: {} },
      "/api/overview/city": { ok: true, status: 200, body: OVERVIEW_OK },
    });
    render(<OverviewPage />);
    await screen.findByTestId("city-situation-narrative");
    expect(screen.getAllByTestId("domain-kpi-card")).toHaveLength(2);
    fireEvent.click(screen.getByTestId("request-city-report"));
    await waitFor(() => expect(screen.getByTestId("city-situation-narrative")).toBeTruthy());
    expect(screen.getAllByTestId("domain-kpi-card")).toHaveLength(2);
    expect(spy.mock.calls.filter((c) => String(c[0]).includes("/api/city/report"))).toHaveLength(1);
  });

  it("refreshes the domain cards from the warmed coordinator cache after a successful assessment", async () => {
    // Cold overview: every module honestly unavailable.
    const COLD = {
      ...OVERVIEW_OK,
      ai_brief: null,
      city_assessment_ready: false,
      modules: OVERVIEW_OK.modules.map((m) => ({
        ...m,
        status: "unavailable" as const,
        kpi: null,
      })),
      domain_status: {},
    };
    let overviewCalls = 0;
    const spy = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/city/report")) {
        return { ok: true, status: 200, statusText: "200", json: async () => CITY_REPORT_OK } as unknown as Response;
      }
      if (url.includes("/api/overview/city-narrative")) {
        return {
          ok: true, status: 200, statusText: "200",
          json: async () => ({ ai_brief: "City status DISRUPTED (risk HIGH, confidence high).", city_assessment_ready: true, report_generated_at: "2026-10-12T02:33:10.233228" }),
        } as unknown as Response;
      }
      if (url.includes("/api/overview/city")) {
        overviewCalls += 1;
        return { ok: true, status: 200, statusText: "200", json: async () => (overviewCalls === 1 ? COLD : OVERVIEW_OK) } as unknown as Response;
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    globalThis.fetch = spy as unknown as typeof fetch;

    render(<OverviewPage />);
    // Cold state: cards are explicitly unavailable, never zero or invented.
    await waitFor(() =>
      expect(screen.getAllByTestId("kpi-value-unavailable")).toHaveLength(2)
    );

    fireEvent.click(screen.getByTestId("request-city-report"));

    // The assessment warmed the coordinator cache; the page re-reads it.
    await waitFor(() =>
      expect(screen.getByTestId("kpi-value").textContent).toContain("796.8")
    );
    expect(screen.getAllByTestId("kpi-value-unavailable")).toHaveLength(1);
    const cityFetches = spy.mock.calls
      .map((c) => String(c[0]))
      .filter((u) => u.includes("/api/overview/city") && !u.includes("city-narrative"));
    expect(cityFetches).toHaveLength(2);
    expect(screen.getByTestId("city-status-badge").textContent).toBe("Disrupted");
  });
});
