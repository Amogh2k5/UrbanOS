/**
 * City Overview page-level integration test.
 *
 * Verifies the wiring between the two endpoints the Overview consumes, and
 * that a failure in one does not blank the other.
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

  it("fetches both endpoints exactly once each", async () => {
    const spy = mockEndpoints(BOTH_OK);
    render(<OverviewPage />);
    await waitFor(() => expect(screen.getByTestId("city-situation")).toBeTruthy());

    const urls = spy.mock.calls.map((c) => String(c[0]));
    expect(urls.filter((u) => u.includes("/api/city/report"))).toHaveLength(1);
    expect(urls.filter((u) => u.includes("/api/overview/city"))).toHaveLength(1);
  });

  it("renders the narrative from the overview endpoint", async () => {
    mockEndpoints(BOTH_OK);
    render(<OverviewPage />);
    await waitFor(() =>
      expect(screen.getByTestId("city-situation-narrative").textContent).toContain(
        "City status DISRUPTED"
      )
    );
  });

  it("renders risk signals from the coordinator endpoint", async () => {
    mockEndpoints(BOTH_OK);
    render(<OverviewPage />);
    await waitFor(() =>
      expect(screen.getAllByTestId("risk-signal-card")).toHaveLength(1)
    );
    expect(screen.getByTestId("risk-signal-zones").textContent).toContain("Central South");
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
    await waitFor(() =>
      expect(screen.getByTestId("risk-signals-error").textContent).toContain("API error 500")
    );
    // Overview data still renders.
    expect(screen.getAllByTestId("domain-kpi-card")).toHaveLength(2);
    expect(screen.getByTestId("city-situation-narrative")).toBeTruthy();
  });

  it("keeps risk signals working when the overview endpoint fails", async () => {
    mockEndpoints({
      "/api/city/report": { ok: true, status: 200, body: CITY_REPORT_OK },
      "/api/overview/city": { ok: false, status: 500, body: {} },
    });
    render(<OverviewPage />);
    await waitFor(() =>
      expect(screen.getByTestId("city-situation-error").textContent).toContain("API error 500")
    );
    expect(screen.getAllByTestId("risk-signal-card")).toHaveLength(1);
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
  });

  it("populates the shared store so map/inspector components can consume it", async () => {
    mockEndpoints(BOTH_OK);
    const { useAppStore } = await import("@/store");
    render(<OverviewPage />);
    await waitFor(() => expect(screen.getAllByTestId("risk-signal-card")).toHaveLength(1));
    await waitFor(() => {
      expect(useAppStore.getState().report?.overall_city_status).toBe("DISRUPTED");
    });
  });
});

// ---------------------------------------------------------------------------
// City Situation reconciliation
//
// A coordinator run takes far longer than a page load, so the Overview usually
// answers from a cold cache: its narrative is per-domain evidence that
// explicitly claims no city status. `/api/city/report` blocks until that run
// finishes, and the pending text must then be replaced - otherwise the page
// shows a completed report next to a stale "assessment pending" paragraph.
// ---------------------------------------------------------------------------
const PENDING_BRIEF =
  "City assessment pending: the City Coordinator has not produced a city-level " +
  "assessment yet, so no city status or risk level is claimed.";

const OVERVIEW_PENDING: typeof OVERVIEW_OK = {
  ...OVERVIEW_OK,
  ai_brief: PENDING_BRIEF,
  city_assessment_ready: false,
};

const ASSESSED_BRIEF = "City status DISRUPTED (risk HIGH, confidence high).";

const NARRATIVE_READY = {
  ok: true,
  status: 200,
  body: {
    ai_brief: ASSESSED_BRIEF,
    city_assessment_ready: true,
    report_generated_at: "2026-10-12T02:33:10.233228",
  },
};

function reply(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    statusText: "200",
    json: async () => body,
  } as unknown as Response;
}

function narrativeCalls(spy: ReturnType<typeof mockEndpoints>) {
  return spy.mock.calls.filter((c) =>
    String(c[0]).includes("/api/overview/city-narrative")
  ).length;
}

describe("City Situation reconciliation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("replaces the pending brief once the coordinator report completes", async () => {
    mockEndpoints({
      "/api/city/report": { ok: true, status: 200, body: CITY_REPORT_OK },
      "/api/overview/city": { ok: true, status: 200, body: OVERVIEW_PENDING },
      "/api/overview/city-narrative": NARRATIVE_READY,
    });
    render(<OverviewPage />);

    await waitFor(() =>
      expect(screen.getByTestId("city-situation-narrative").textContent).toBe(ASSESSED_BRIEF)
    );
    expect(screen.getByTestId("city-situation-narrative").textContent).not.toContain(
      "assessment pending"
    );
  });

  it("never shows stale pending text once a report has been received", async () => {
    mockEndpoints({
      "/api/city/report": { ok: true, status: 200, body: CITY_REPORT_OK },
      "/api/overview/city": { ok: true, status: 200, body: OVERVIEW_PENDING },
      "/api/overview/city-narrative": NARRATIVE_READY,
    });
    render(<OverviewPage />);

    // The city status badge comes from the coordinator report and must agree
    // with the narrative once both have landed.
    await waitFor(() => {
      expect(screen.getByTestId("city-status-badge").textContent).toBe("DISRUPTED");
      expect(screen.getByTestId("city-situation-narrative").textContent).toBe(ASSESSED_BRIEF);
    });
  });

  it("does not reconcile when the overview already carries a city assessment", async () => {
    const spy = mockEndpoints(BOTH_OK);
    render(<OverviewPage />);
    await waitFor(() =>
      expect(screen.getByTestId("city-situation-narrative").textContent).toContain(
        "City status DISRUPTED"
      )
    );
    expect(narrativeCalls(spy)).toBe(0);
  });

  it("does not reconcile when the coordinator report failed", async () => {
    const spy = mockEndpoints({
      "/api/city/report": { ok: false, status: 500, body: {} },
      "/api/overview/city": { ok: true, status: 200, body: OVERVIEW_PENDING },
      "/api/overview/city-narrative": NARRATIVE_READY,
    });
    render(<OverviewPage />);

    await waitFor(() =>
      expect(screen.getByTestId("risk-signals-error").textContent).toContain("API error 500")
    );
    // The honest deterministic fallback stays; no city status is claimed.
    expect(screen.getByTestId("city-situation-narrative").textContent).toBe(PENDING_BRIEF);
    expect(narrativeCalls(spy)).toBe(0);
  });

  it("keeps the fallback when reconciliation itself fails", async () => {
    mockEndpoints({
      "/api/city/report": { ok: true, status: 200, body: CITY_REPORT_OK },
      "/api/overview/city": { ok: true, status: 200, body: OVERVIEW_PENDING },
      "/api/overview/city-narrative": { ok: false, status: 500, body: {} },
    });
    render(<OverviewPage />);

    await waitFor(() =>
      expect(screen.getByTestId("city-situation-narrative").textContent).toBe(PENDING_BRIEF)
    );
    // A failed reconciliation is not surfaced as a page-level error.
    expect(screen.queryByTestId("city-situation-error")).toBeNull();
  });

  it("keeps the fallback when the coordinator still reports no assessment", async () => {
    mockEndpoints({
      "/api/city/report": { ok: true, status: 200, body: CITY_REPORT_OK },
      "/api/overview/city": { ok: true, status: 200, body: OVERVIEW_PENDING },
      "/api/overview/city-narrative": {
        ok: true,
        status: 200,
        body: {
          ai_brief: null,
          city_assessment_ready: false,
          report_generated_at: null,
        },
      },
    });
    render(<OverviewPage />);

    await waitFor(() =>
      expect(screen.getByTestId("city-situation-narrative").textContent).toBe(PENDING_BRIEF)
    );
  });

  it("refreshes at most once - no polling and no request loop", async () => {
    const spy = mockEndpoints({
      "/api/city/report": { ok: true, status: 200, body: CITY_REPORT_OK },
      "/api/overview/city": { ok: true, status: 200, body: OVERVIEW_PENDING },
      "/api/overview/city-narrative": NARRATIVE_READY,
    });
    render(<OverviewPage />);

    await waitFor(() =>
      expect(screen.getByTestId("city-situation-narrative").textContent).toBe(ASSESSED_BRIEF)
    );

    const urls = spy.mock.calls.map((c) => String(c[0]));
    expect(narrativeCalls(spy)).toBe(1);
    expect(urls.filter((u) => u.includes("/api/city/report"))).toHaveLength(1);
    // The full Overview endpoint is NOT re-fetched: only the narrative is.
    expect(urls.filter((u) => u.endsWith("/api/overview/city"))).toHaveLength(1);

    // Let any stray timer fire, then confirm nothing more was requested.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(narrativeCalls(spy)).toBe(1);
  });

  it("retries only once even when the refresh keeps failing", async () => {
    const spy = mockEndpoints({
      "/api/city/report": { ok: true, status: 200, body: CITY_REPORT_OK },
      "/api/overview/city": { ok: true, status: 200, body: OVERVIEW_PENDING },
      "/api/overview/city-narrative": { ok: false, status: 500, body: {} },
    });
    render(<OverviewPage />);

    await waitFor(() => expect(narrativeCalls(spy)).toBe(1));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(narrativeCalls(spy)).toBe(1);
  });

  // -------------------------------------------------------------------------
  // Badge / readiness consistency.
  //
  // A coordinator report can exist while the assessment is still pending. Its
  // NORMAL / Risk LOW must not be presented as a validated city conclusion.
  // -------------------------------------------------------------------------
  it("shows the pending badge, not the report status, until reconciliation lands", async () => {
    // Gate only the narrative refresh: while the blocking report request is in
    // flight the whole panel is a loading skeleton, so the observable state is
    // "report arrived, assessment not yet applied".
    let release: (() => void) | null = null;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });

    const spy = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/city/report")) return reply(CITY_REPORT_OK);
      if (url.includes("/api/overview/city-narrative")) {
        await gate;
        return reply(NARRATIVE_READY.body);
      }
      return reply(OVERVIEW_PENDING);
    });
    globalThis.fetch = spy as unknown as typeof fetch;

    render(<OverviewPage />);

    // Report is present, assessment is not: the header must not present
    // DISRUPTED / Risk HIGH as a validated city conclusion.
    await waitFor(() => expect(screen.getByTestId("city-assessment-pending")).toBeTruthy());
    expect(screen.queryByTestId("city-status-badge")).toBeNull();
    expect(screen.queryByTestId("city-risk")).toBeNull();
    expect(screen.queryByTestId("city-confidence")).toBeNull();
    expect(
      document.querySelector('[data-testid="city-situation"]')?.textContent
    ).not.toContain("DISRUPTED");

    release!();
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
    await waitFor(() =>
      expect(screen.getByTestId("city-status-badge").textContent).toBe("DISRUPTED")
    );
    expect(screen.queryByTestId("city-assessment-pending")).toBeNull();
    expect(screen.getByTestId("city-situation-narrative").textContent).toBe(ASSESSED_BRIEF);
  });

  it("badge and narrative agree after reconciliation", async () => {
    mockEndpoints({
      "/api/city/report": { ok: true, status: 200, body: CITY_REPORT_OK },
      "/api/overview/city": { ok: true, status: 200, body: OVERVIEW_PENDING },
      "/api/overview/city-narrative": NARRATIVE_READY,
    });
    render(<OverviewPage />);

    await waitFor(() => {
      expect(screen.getByTestId("city-status-badge").textContent).toBe("DISRUPTED");
      expect(screen.getByTestId("city-situation-narrative").textContent).toBe(ASSESSED_BRIEF);
    });
    expect(screen.queryByTestId("city-assessment-pending")).toBeNull();
  });

  it("keeps domain KPIs independent of the city assessment", async () => {
    mockEndpoints({
      "/api/city/report": { ok: true, status: 200, body: CITY_REPORT_OK },
      "/api/overview/city": { ok: true, status: 200, body: OVERVIEW_PENDING },
      "/api/overview/city-narrative": NARRATIVE_READY,
    });
    render(<OverviewPage />);

    await waitFor(() =>
      expect(screen.getByTestId("city-situation-narrative").textContent).toBe(ASSESSED_BRIEF)
    );
    // Reconciling the city narrative must not disturb the module cards.
    expect(screen.getAllByTestId("domain-kpi-card")).toHaveLength(2);
    expect(screen.getByTestId("kpi-value").textContent).toContain("796.8");
  });
});