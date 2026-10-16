/**
 * Component tests for the City Overview sections.
 *
 * Fixtures are taken verbatim from the running backend so the tests fail if the
 * UI is wired to fields the API does not actually return.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import CitySituationPanel from "./CitySituationPanel";
import RiskSignals, { classifyImpactState } from "./RiskSignals";
import DomainKpiGrid from "./DomainKpiGrid";
import KpiInsightPanel from "./KpiInsightPanel";
import type { CitySituationReport, DomainStatus } from "@/types/intelligence";
import type { ModuleSummary } from "@/services/api";

// Captured from GET /api/city/report
const REAL_REPORT: CitySituationReport = {
  generated_at: "2026-10-12T02:33:10.233228",
  overall_city_status: "CRITICAL",
  overall_risk_level: "CRITICAL",
  domain_status: {},
  priority_incidents: [],
  cross_domain_impacts: [
    {
      type: "multi_domain_high_risk",
      description:
        "3 domains independently report HIGH or CRITICAL risk (environment, flood, traffic). No causal link between them is asserted.",
      severity: "CRITICAL",
      affected_zones: [],
      domains_involved: ["environment", "flood", "traffic"],
      evidence: ["environment reports HIGH risk.", "flood reports HIGH risk."],
    },
    {
      type: "flood_traffic",
      description:
        "HIGH flood risk coincides with disrupted traffic conditions in Central South.",
      severity: "HIGH",
      affected_zones: ["Central South"],
      domains_involved: ["flood", "traffic"],
      evidence: ["Flood risk reported as HIGH."],
    },
  ],
  city_level_recommendations: ["MULTI-DOMAIN CRITICAL: ..."],
  affected_zones: ["Central South"],
  evidence: [],
  confidence: "high",
  limitations: ["The City Coordinator is a deterministic rule engine, not an ML predictor."],
  source_reports: {},
  is_ml_prediction: false,
};

const REAL_MODULES: ModuleSummary[] = [
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
  {
    id: "flood",
    name: "Rain & Flood",
    status: "normal",
    kpi: null,
    updated_at: null,
    detail_route: "/environment/flood",
  },
];

// ======================================================== City Situation
describe("CitySituationPanel", () => {
  it("renders the backend narrative verbatim", () => {
    render(
      <CitySituationPanel
        narrative="City operations are disrupted in Central South."
        report={REAL_REPORT}
        assessmentReady
      />
    );
    expect(screen.getByTestId("city-situation-narrative").textContent).toContain(
      "City operations are disrupted in Central South."
    );
  });

  it("shows the coordinator status, risk and confidence", () => {
    render(<CitySituationPanel narrative="x" report={REAL_REPORT} assessmentReady />);
    expect(screen.getByTestId("city-status-badge").textContent).toBe("CRITICAL");
    expect(screen.getByTestId("city-confidence").textContent).toContain("high");
  });

  it("states plainly when no narrative is available rather than inventing one", () => {
    render(<CitySituationPanel narrative={null} report={REAL_REPORT} assessmentReady />);
    expect(screen.getByTestId("city-situation-unavailable")).toBeTruthy();
    expect(screen.queryByTestId("city-situation-narrative")).toBeNull();
  });

  it("distinguishes an API error from a missing narrative", () => {
    render(
      <CitySituationPanel narrative={null} report={null} assessmentReady={false} error="API error 500" />
    );
    expect(screen.getByTestId("city-situation-error").textContent).toContain("API error 500");
    expect(screen.queryByTestId("city-situation-unavailable")).toBeNull();
  });

  it("renders a loading skeleton", () => {
    render(<CitySituationPanel narrative={null} report={null} assessmentReady={false} loading />);
    expect(screen.getByTestId("city-situation-loading")).toBeTruthy();
  });

  it("surfaces affected zones and limitations as provenance", () => {
    render(<CitySituationPanel narrative="x" report={REAL_REPORT} assessmentReady />);
    expect(screen.getByTestId("city-affected-zones").textContent).toContain("Central South");
    expect(screen.getByTestId("city-limitations").textContent).toContain(
      "deterministic rule engine"
    );
  });

  it("renders with no report at all without crashing", () => {
    render(<CitySituationPanel narrative={null} report={null} assessmentReady={false} />);
    expect(screen.getByTestId("city-situation")).toBeTruthy();
  });

  // ------------------------------------------------------------------
  // A report object existing is not the same as a validated city
  // assessment. Presenting NORMAL / Risk LOW while the assessment is still
  // pending would publish an unvalidated value as a city conclusion.
  // ------------------------------------------------------------------
  it("shows an explicit pending state instead of a status while pending", () => {
    render(
      <CitySituationPanel narrative={null} report={REAL_REPORT} assessmentReady={false} />
    );
    expect(screen.getByTestId("city-assessment-pending")).toBeTruthy();
    expect(screen.queryByTestId("city-status-badge")).toBeNull();
    expect(screen.queryByTestId("city-risk")).toBeNull();
    expect(screen.queryByTestId("city-confidence")).toBeNull();
  });

  it("does not leak the report's status text while pending", () => {
    render(
      <CitySituationPanel narrative={null} report={REAL_REPORT} assessmentReady={false} />
    );
    const header = document.querySelector('[data-testid="city-situation"]');
    expect(header?.textContent).not.toContain("CRITICAL");
    expect(header?.textContent).not.toContain("Risk HIGH");
  });

  it("reveals the validated status once the assessment is ready", () => {
    render(
      <CitySituationPanel narrative="Assessed." report={REAL_REPORT} assessmentReady />
    );
    expect(screen.queryByTestId("city-assessment-pending")).toBeNull();
    expect(screen.getByTestId("city-status-badge").textContent).toBe("CRITICAL");
    expect(screen.getByTestId("city-risk").textContent).toContain("CRITICAL");
  });

  it("renders no status block at all when there is no report", () => {
    render(<CitySituationPanel narrative={null} report={null} assessmentReady={false} />);
    expect(screen.queryByTestId("city-assessment-pending")).toBeNull();
    expect(screen.queryByTestId("city-status-badge")).toBeNull();
  });
});

// ======================================================== Risk Signals
describe("RiskSignals", () => {
  it("renders each validated impact with its evidence", () => {
    render(<RiskSignals impacts={REAL_REPORT.cross_domain_impacts} reportAvailable />);
    expect(screen.getAllByTestId("risk-signal-card")).toHaveLength(2);
    // Both validated impacts must carry their evidence list.
    const evidence = screen.getAllByTestId("risk-signal-evidence");
    expect(evidence).toHaveLength(2);
    expect(evidence[1].textContent).toContain("Flood risk reported as HIGH.");
  });

  it("shows the impact's own severity", () => {
    render(<RiskSignals impacts={REAL_REPORT.cross_domain_impacts} reportAvailable />);
    const cards = screen.getAllByTestId("risk-signal-card");
    expect(cards[0].getAttribute("data-severity")).toBe("CRITICAL");
    expect(cards[1].getAttribute("data-severity")).toBe("HIGH");
  });

  it("shows affected zones when present", () => {
    render(<RiskSignals impacts={REAL_REPORT.cross_domain_impacts} reportAvailable />);
    expect(screen.getAllByTestId("risk-signal-zones")[0].textContent).toContain(
      "Central South"
    );
  });

  it("hides an impact that carries no evidence", () => {
    const unvalidated = [
      { ...REAL_REPORT.cross_domain_impacts[0], evidence: [] },
      REAL_REPORT.cross_domain_impacts[1],
    ];
    render(<RiskSignals impacts={unvalidated} reportAvailable />);
    expect(screen.getAllByTestId("risk-signal-card")).toHaveLength(1);
    expect(screen.getByTestId("risk-signals-dropped").textContent).toContain(
      "1 unvalidated signal"
    );
  });

  it("shows an intentional empty state for zero validated impacts", () => {
    render(<RiskSignals impacts={[]} reportAvailable />);
    const empty = screen.getByTestId("risk-signals-empty");
    expect(empty.textContent).toContain("No validated cross-domain signals");
    // It must point at what is still trustworthy instead of implying safety.
    expect(empty.textContent).toContain("not an all-clear");
    // No impact card, severity or zone may be manufactured.
    expect(screen.queryAllByTestId("risk-signal-card")).toHaveLength(0);
    expect(screen.queryByTestId("risk-signal-severity")).toBeNull();
    expect(screen.queryByTestId("risk-signal-zones")).toBeNull();
  });

  it("never states the city has no risks when impacts are zero", () => {
    render(<RiskSignals impacts={[]} reportAvailable />);
    const text = screen.getByTestId("risk-signals-empty").textContent ?? "";
    for (const reassurance of ["no risks", "all clear", "all-clear.", "safe", "normal"]) {
      // "not an all-clear" is explicitly allowed; a bare claim is not.
      expect(text.replace(/not an all-clear/g, "")).not.toMatch(
        new RegExp(reassurance.replace(".", "\\."), "i")
      );
    }
  });

  it("distinguishes 'nothing found' from 'could not be computed'", () => {
    render(<RiskSignals impacts={[]} reportAvailable={false} />);
    const panel = screen.getByTestId("risk-signals-unavailable");
    expect(panel.textContent).toContain("could not be computed");
    expect(screen.queryByTestId("risk-signals-empty")).toBeNull();
  });

  it("distinguishes missing impact data from zero impacts", () => {
    render(<RiskSignals impacts={undefined} reportAvailable />);
    expect(screen.getByTestId("risk-signals-no-data").textContent).toContain(
      "carried no cross-domain impact data"
    );
    expect(screen.queryByTestId("risk-signals-empty")).toBeNull();
  });

  it("shows an error state for an API failure", () => {
    render(<RiskSignals impacts={null} error="API error 500" reportAvailable={false} />);
    expect(screen.getByTestId("risk-signals-error").textContent).toContain("API error 500");
    expect(screen.queryByTestId("risk-signals-empty")).toBeNull();
  });

  it("shows a loading state rather than an empty state", () => {
    render(<RiskSignals impacts={null} loading />);
    expect(screen.getByTestId("risk-signals-loading")).toBeTruthy();
    expect(screen.queryByTestId("risk-signals-empty")).toBeNull();
  });

  it("keeps the hidden-signal disclosure when every impact lacks evidence", () => {
    const unvalidated = [
      { ...REAL_REPORT.cross_domain_impacts[0], evidence: [] },
      { ...REAL_REPORT.cross_domain_impacts[1], evidence: [] },
    ];
    render(<RiskSignals impacts={unvalidated} reportAvailable />);
    expect(screen.queryAllByTestId("risk-signal-card")).toHaveLength(0);
    // The candidates existed and were withheld, so that must still be stated.
    expect(screen.getByTestId("risk-signals-dropped").textContent).toContain(
      "2 unvalidated signals hidden"
    );
    expect(screen.getByTestId("risk-signals-empty").textContent).toContain(
      "none carried supporting evidence"
    );
  });

  it("does not render a hidden-signal disclosure when nothing was filtered", () => {
    render(<RiskSignals impacts={[]} reportAvailable />);
    expect(screen.queryByTestId("risk-signals-dropped")).toBeNull();
  });

  it("renders a distinct error state", () => {
    render(<RiskSignals impacts={null} error="API error 500" />);
    expect(screen.getByTestId("risk-signals-error").textContent).toContain("API error 500");
  });

  it("renders the loading state", () => {
    render(<RiskSignals impacts={null} loading />);
    expect(screen.getByTestId("risk-signals-loading")).toBeTruthy();
  });
});

// The state classifier is pure, so the four cases are pinned directly.
describe("classifyImpactState", () => {
  it("maps every input to exactly one state", () => {
    expect(classifyImpactState({ impacts: null, loading: true }).kind).toBe("loading");
    expect(classifyImpactState({ impacts: null, error: "500" }).kind).toBe("error");
    expect(classifyImpactState({ impacts: [], reportAvailable: false }).kind).toBe("unavailable");
    expect(classifyImpactState({ impacts: undefined, reportAvailable: true }).kind).toBe("no-data");
    expect(classifyImpactState({ impacts: [], reportAvailable: true }).kind).toBe("empty");
    expect(
      classifyImpactState({ impacts: REAL_REPORT.cross_domain_impacts, reportAvailable: true }).kind
    ).toBe("signals");
  });

  it("counts withheld impacts in both the empty and populated states", () => {
    const unvalidated = [{ ...REAL_REPORT.cross_domain_impacts[0], evidence: [] }];
    expect(classifyImpactState({ impacts: unvalidated, reportAvailable: true })).toEqual({
      kind: "empty",
      hidden: 1,
    });
    expect(
      classifyImpactState({
        impacts: [...REAL_REPORT.cross_domain_impacts, ...unvalidated],
        reportAvailable: true,
      })
    ).toMatchObject({ kind: "signals", hidden: 1 });
  });

  it("prioritises loading and error over any payload", () => {
    expect(classifyImpactState({ impacts: [], loading: true, error: "500" }).kind).toBe("loading");
    expect(
      classifyImpactState({ impacts: [], error: "500", reportAvailable: false }).kind
    ).toBe("error");
  });
});

// ======================================================== KPI grid
describe("DomainKpiGrid", () => {
  it("renders a card per module with a link to its domain page", () => {
    render(
      <DomainKpiGrid modules={REAL_MODULES} domainsWithFindings={new Set()} onOpenInsight={vi.fn()} />
    );
    const cards = screen.getAllByTestId("domain-kpi-card");
    expect(cards).toHaveLength(3);
    expect(cards[0].getAttribute("href")).toBe("/planning/land");
  });

  it("renders the real KPI value and unit", () => {
    render(
      <DomainKpiGrid modules={REAL_MODULES} domainsWithFindings={new Set()} onOpenInsight={vi.fn()} />
    );
    expect(screen.getAllByTestId("kpi-value")[0].textContent).toBe("796.8 km²");
  });

  it("renders Unavailable rather than a zero when a module has no KPI", () => {
    render(
      <DomainKpiGrid modules={REAL_MODULES} domainsWithFindings={new Set()} onOpenInsight={vi.fn()} />
    );
    expect(screen.getAllByTestId("kpi-value-unavailable").length).toBeGreaterThan(0);
    const cards = screen.getAllByTestId("domain-kpi-card");
    const crimeCard = cards[1];
    expect(crimeCard.getAttribute("data-status")).toBe("unavailable");
    expect(crimeCard.textContent).toContain("Unavailable");
    expect(crimeCard.textContent).toContain("No supported metric");
  });

  it("shows a real KPI even when the domain status is unavailable", () => {
    // Regression: the card suppressed the metric whenever status was
    // "unavailable", so Water - which has a genuine potable-sales reading but
    // an unassessable risk level (overall_risk UNKNOWN) - rendered
    // "No supported metric" and looked broken. Status and metric are
    // independent facts and both must survive.
    const modules: ModuleSummary[] = [
      {
        id: "water",
        name: "Water",
        status: "unavailable",
        kpi: { label: "Potable Sales", value: 515.5, unit: "million m3" },
        updated_at: null,
        detail_route: "/infrastructure/water",
      },
    ];
    render(<DomainKpiGrid modules={modules} domainsWithFindings={new Set()} onOpenInsight={vi.fn()} />);

    const card = screen.getByTestId("domain-kpi-card");
    expect(screen.getByTestId("kpi-value").textContent).toBe("515.5 million m3");
    // The honest status is still shown alongside the real metric.
    expect(screen.getByTestId("kpi-status").textContent).toBe("Unavailable");
    expect(screen.queryByTestId("kpi-value-unavailable")).toBeNull();
  });

  it("never renders a bare zero for a missing KPI", () => {
    render(
      <DomainKpiGrid modules={REAL_MODULES} domainsWithFindings={new Set()} onOpenInsight={vi.fn()} />
    );
    const values = screen.queryAllByTestId("kpi-value").map((n) => n.textContent);
    expect(values).not.toContain("0");
  });

  // ------------------------------------------- insight click isolation
  it("insight action does NOT trigger the card's navigation", () => {
    const onOpenInsight = vi.fn();
    render(
      <DomainKpiGrid modules={REAL_MODULES} domainsWithFindings={new Set(["land"])} onOpenInsight={onOpenInsight} />
    );
    const button = screen.getAllByTestId("kpi-insight-button")[0];

    const link = button.closest("a");
    expect(link).not.toBeNull();
    fireEvent.click(button);

    expect(onOpenInsight).toHaveBeenCalledWith("land");
    // The click must not have followed the surrounding link.
    expect(link?.getAttribute("href")).toBe("/planning/land");
  });

  it("insight buttons are real buttons, one per module", () => {
    render(
      <DomainKpiGrid modules={REAL_MODULES} domainsWithFindings={new Set()} onOpenInsight={vi.fn()} />
    );
    const buttons = screen.getAllByTestId("kpi-insight-button");
    expect(buttons).toHaveLength(REAL_MODULES.length);
    buttons.forEach((b) => expect(b.tagName).toBe("BUTTON"));
  });

  it("marks the insight button when the domain has a grounded finding", () => {
    render(
      <DomainKpiGrid modules={REAL_MODULES} domainsWithFindings={new Set(["land"])} onOpenInsight={vi.fn()} />
    );
    const land = screen.getAllByTestId("kpi-insight-button")[0];
    const crime = screen.getAllByTestId("kpi-insight-button")[1];
    expect(land.className).toContain("text-yellow-200");
    expect(crime.className).toContain("text-white/50");
  });

  it("shows an empty state with no modules", () => {
    render(<DomainKpiGrid modules={null} domainsWithFindings={new Set()} onOpenInsight={vi.fn()} />);
    expect(screen.getByTestId("kpi-grid-empty")).toBeTruthy();
  });
});

// ======================================================== KPI insight panel
const AVAILABLE_DOMAIN: DomainStatus = {
  domain: "water",
  available: true,
  overall_status: "NORMAL",
  overall_risk: "LOW",
  key_metrics: {},
  affected_zones: [],
  primary_risk_factors: [],
  confidence: "high",
  limitations: ["Reservoir storage levels are not published as open data."],
  is_ml_prediction: false,
  generated_at: "2026-10-12T05:05:19.810241+08:00",
  display_name: "Water",
  findings: [
    {
      id: "water.insight_0",
      domain: "water",
      title: "What is the current/latest water supply status?",
      answer: "Reservoir storage levels are not published as open data.",
      data_kind: "unavailable",
      category: "insight",
      question: null,
      severity: null,
      evidence: [],
      evidence_refs: [],
      sources: [],
      observed_at: null,
      freshness: "unknown",
      affected_area: null,
      limitations: [],
      metrics: {},
    },
    {
      id: "water.insight_1",
      domain: "water",
      title: "How is water usage changing?",
      answer: "Total potable sales 515.5 million m3 in 2025 (+1.2% vs 2024).",
      data_kind: "historical",
      category: "insight",
      question: "How is water usage changing?",
      severity: null,
      evidence: ["Derived from the water report."],
      evidence_refs: [],
      sources: [],
      observed_at: "2026-10-12T05:05:19.810241+08:00",
      freshness: "recent",
      affected_area: null,
      limitations: ["Annual official statistics."],
      metrics: { value: 515.5, unit: "million m3" },
    },
  ],
};

describe("KpiInsightPanel", () => {
  it("renders only substantive findings, not the unavailable stub", () => {
    render(
      <KpiInsightPanel domainId="water" status={AVAILABLE_DOMAIN} onClose={vi.fn()} />
    );
    const rows = screen.getAllByTestId("kpi-insight-finding");
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain("How is water usage changing?");
  });

  it("shows evidence, metrics, freshness and limitations", () => {
    render(<KpiInsightPanel domainId="water" status={AVAILABLE_DOMAIN} onClose={vi.fn()} />);
    expect(screen.getByTestId("kpi-insight-evidence").textContent).toContain(
      "Derived from the water report."
    );
    expect(screen.getByTestId("kpi-insight-metrics").textContent).toContain("515.5");
    expect(screen.getByTestId("kpi-insight-freshness").textContent).toContain("recent");
    expect(screen.getByTestId("kpi-insight-limitations").textContent).toContain(
      "Annual official statistics."
    );
  });

  it("says so explicitly when no grounded insight exists", () => {
    const bare: DomainStatus = {
      ...AVAILABLE_DOMAIN,
      findings: [],
      display_name: "Roads",
    };
    render(<KpiInsightPanel domainId="roads" status={bare} onClose={vi.fn()} />);
    const el = screen.getByTestId("kpi-insight-none");
    expect(el.textContent).toContain("No grounded insight is available");
    expect(el.textContent).toContain("will not");
  });

  it("states unavailability and never implies normality", () => {
    const down: DomainStatus = {
      ...AVAILABLE_DOMAIN,
      available: false,
      error: "No traffic prediction data available",
      findings: [],
    };
    render(<KpiInsightPanel domainId="traffic" status={down} onClose={vi.fn()} />);
    const el = screen.getByTestId("kpi-insight-unavailable");
    expect(el.textContent).toContain("No traffic prediction data available");
    expect(el.textContent).toContain("Absence of data is not evidence of normal conditions");
  });

  it("handles a completely missing domain status", () => {
    render(<KpiInsightPanel domainId="ghost" status={null} onClose={vi.fn()} />);
    expect(screen.getByTestId("kpi-insight-unavailable")).toBeTruthy();
  });

  it("closes when the close button is pressed", () => {
    const onClose = vi.fn();
    render(<KpiInsightPanel domainId="water" status={AVAILABLE_DOMAIN} onClose={onClose} />);
    fireEvent.click(screen.getByTestId("kpi-insight-close"));
    expect(onClose).toHaveBeenCalled();
  });

  it("closes on backdrop click but not on panel click", () => {
    const onClose = vi.fn();
    render(<KpiInsightPanel domainId="water" status={AVAILABLE_DOMAIN} onClose={onClose} />);
    fireEvent.click(screen.getByTestId("kpi-insight-panel"));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("kpi-insight-panel").parentElement as HTMLElement);
    expect(onClose).toHaveBeenCalled();
  });

  it("shows domain limitations as provenance", () => {
    render(<KpiInsightPanel domainId="water" status={AVAILABLE_DOMAIN} onClose={vi.fn()} />);
    expect(screen.getByTestId("kpi-insight-domain-limitations").textContent).toContain(
      "Reservoir storage levels"
    );
  });
});

// ============================================ no hardcoded intelligence
describe("Overview components contain no fabricated intelligence", () => {
  // Scans the component sources for the reference design's demo content and
  // for the hardcoded causal claim the earlier audit found.
  const FILES = [
    "./CitySituationPanel.tsx",
    "./RiskSignals.tsx",
    "./DomainKpiGrid.tsx",
    "./KpiInsightPanel.tsx",
  ];

  const FORBIDDEN = [
    "East Coast",        // reference demo location
    "Bedok Canal",       // reference demo metric
    "Ambulance",         // reference demo alert
    "overlapping domain alerts", // the hardcoded claim removed in Phase 1
    "Condition analysis indicates", // the removed template
  ];

  it.each(FILES)("%s has no reference demo content or hardcoded claims", (file) => {
    const source = readFileSync(resolve(__dirname, file), "utf-8");
    for (const phrase of FORBIDDEN) {
      expect(source).not.toContain(phrase);
    }
  });

  it("renders nothing that looks like a demo metric", () => {
    render(<RiskSignals impacts={[]} reportAvailable />);
    expect(screen.getByTestId("risk-signals-empty").textContent).not.toMatch(/\d+\s*km\/h/);
  });
});