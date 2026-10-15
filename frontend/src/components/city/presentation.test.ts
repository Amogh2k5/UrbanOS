/**
 * Unit tests for the Overview presentation helpers.
 *
 * The fixtures mirror the real API responses captured from the running
 * backend, so a schema drift shows up here rather than on screen.
 */
import { describe, expect, it } from "vitest";
import {
  accentFor,
  dataKindLabel,
  dataKindPillClass,
  formatKpiValue,
  formatTimestamp,
  isValidatedImpact,
  moduleStatusBand,
  orderedModules,
  riskSignalBorder,
  severityBand,
  statusLabel,
  statusPillClass,
  substantiveFindings,
} from "./presentation";
import type { CrossDomainImpact, Finding } from "@/types/intelligence";
import type { ModuleSummary } from "@/services/api";

// Real impact captured from POST /api/city/report
const REAL_IMPACT: CrossDomainImpact = {
  type: "multi_domain_high_risk",
  description:
    "3 domains independently report HIGH or CRITICAL risk (environment, flood, traffic). No causal link between them is asserted.",
  severity: "CRITICAL",
  affected_zones: [],
  domains_involved: ["environment", "flood", "traffic"],
  evidence: [
    "environment reports HIGH risk.",
    "flood reports HIGH risk.",
    "traffic reports HIGH risk.",
  ],
};

// Real module card captured from GET /api/overview/city
const REAL_MODULE: ModuleSummary = {
  id: "land",
  name: "Land",
  status: "normal",
  kpi: { label: "Land-Use Area", value: 796.8, unit: "km²" },
  updated_at: "2026-10-12T05:05:19.810241+08:00",
  detail_route: "/planning/land",
};

describe("severityBand", () => {
  it.each([
    ["CRITICAL", "critical"],
    ["HIGH", "high"],
    ["MODERATE", "moderate"],
    ["LOW", "low"],
    // Case-insensitive: the backend and the frontend need not agree on casing.
    ["critical", "critical"],
    ["high", "high"],
    ["moderate", "moderate"],
    // Unknown values must never escalate.
    ["SEVERE", "low"],
    ["", "low"],
    [undefined, "low"],
    [null, "low"],
  ])("maps %s -> %s", (input, expected) => {
    expect(severityBand(input as string)).toBe(expected);
  });

  it("does not escalate an unrecognised severity to critical", () => {
    expect(severityBand("APOCALYPTIC")).not.toBe("critical");
  });
});

describe("riskSignalBorder", () => {
  it("gives each severity a distinct left border", () => {
    const borders = new Set([
      riskSignalBorder("CRITICAL"),
      riskSignalBorder("HIGH"),
      riskSignalBorder("MODERATE"),
      riskSignalBorder("LOW"),
    ]);
    expect(borders.size).toBe(4);
  });

  it("escalates strictly downwards", () => {
    expect(riskSignalBorder("CRITICAL")).toContain("rose");
    expect(riskSignalBorder("HIGH")).toContain("rose");
    expect(riskSignalBorder("MODERATE")).toContain("amber");
    expect(riskSignalBorder("LOW")).toContain("blue");
  });
});

describe("module status handling", () => {
  it("distinguishes unavailable from normal", () => {
    expect(moduleStatusBand("unavailable")).toBe("unavailable");
    expect(moduleStatusBand("normal")).toBe("normal");
  });

  it("labels unavailable explicitly", () => {
    expect(statusLabel("unavailable")).toBe("Unavailable");
    expect(statusLabel("elevated")).toBe("Elevated");
    expect(statusLabel("critical")).toBe("Critical");
  });

  it("gives unavailable a visibly different pill", () => {
    expect(statusPillClass("unavailable")).not.toBe(statusPillClass("normal"));
    expect(statusPillClass("unavailable")).toContain("slate");
    expect(statusPillClass("normal")).toContain("emerald");
  });
});

describe("formatKpiValue", () => {
  it("formats the real Land KPI", () => {
    expect(formatKpiValue(796.8, "km²")).toBe("796.8 km²");
  });

  it("keeps integers without a decimal point", () => {
    expect(formatKpiValue(8093, "")).toBe("8093");
  });

  it("renders zero as zero (a real zero, not a placeholder)", () => {
    expect(formatKpiValue(0, "")).toBe("0");
  });

  it("returns null for absent values so callers can show Unavailable", () => {
    expect(formatKpiValue(null, "km²")).toBeNull();
    expect(formatKpiValue(undefined, "km²")).toBeNull();
    expect(formatKpiValue("", "km²")).toBeNull();
    expect(formatKpiValue(NaN, "km²")).toBeNull();
  });

  it("passes through string KPIs", () => {
    expect(formatKpiValue("High", "")).toBe("High");
  });
});

describe("dataKindLabel", () => {
  it("calls out unavailable rather than defaulting to a normal label", () => {
    expect(dataKindLabel("unavailable")).toBe("Unavailable");
    expect(dataKindLabel(undefined)).toBe("Unavailable");
    expect(dataKindLabel("live")).toBe("Live");
    expect(dataKindLabel("historical")).toBe("Historical");
  });

  it("gives unavailable a distinct pill", () => {
    expect(dataKindPillClass("unavailable")).not.toBe(dataKindPillClass("live"));
  });
});

describe("isValidatedImpact", () => {
  it("accepts an impact that carries evidence", () => {
    expect(isValidatedImpact(REAL_IMPACT)).toBe(true);
  });

  it("rejects an impact with no evidence (correlation, not intelligence)", () => {
    expect(isValidatedImpact({ ...REAL_IMPACT, evidence: [] })).toBe(false);
  });

  it("rejects a malformed impact", () => {
    expect(
      isValidatedImpact({ ...REAL_IMPACT, evidence: undefined } as unknown as CrossDomainImpact)
    ).toBe(false);
  });
});

describe("substantiveFindings", () => {
  const unavailable: Finding = {
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
  };

  const real: Finding = {
    ...unavailable,
    id: "water.insight_0",
    title: "What is the current/latest water supply status?",
    answer: "Reservoir storage levels are not published as open data.",
    data_kind: "latest_available",
    evidence: ["Derived from the water report."],
    freshness: "recent",
  };

  it("filters the unavailable stub out", () => {
    expect(substantiveFindings([unavailable])).toHaveLength(0);
  });

  it("keeps real findings", () => {
    expect(substantiveFindings([unavailable, real])).toHaveLength(1);
  });

  it("handles missing input", () => {
    expect(substantiveFindings(undefined)).toHaveLength(0);
    expect(substantiveFindings(null)).toHaveLength(0);
  });
});

describe("accentFor", () => {
  it("has a distinct accent per known domain", () => {
    expect(accentFor("traffic").bg).toBe("bg-blue-600");
    expect(accentFor("water").bg).toBe("bg-cyan-700");
    expect(accentFor("land").bg).toBe("bg-violet-600");
  });

  it("falls back for an unknown domain instead of returning undefined", () => {
    expect(accentFor("nope").bg).toBeTruthy();
    expect(accentFor("nope").ring).toBeTruthy();
  });
});

describe("formatTimestamp", () => {
  it("formats a real timestamp", () => {
    expect(formatTimestamp("2026-10-12T05:05:19.810241+08:00")).not.toBe("");
  });

  it("returns empty for absent or unparseable input", () => {
    expect(formatTimestamp(null)).toBe("");
    expect(formatTimestamp(undefined)).toBe("");
    expect(formatTimestamp("not-a-date")).toBe("");
  });
});

describe("orderedModules", () => {
  it("returns a copy so callers cannot mutate the source array", () => {
    const input = [REAL_MODULE];
    const out = orderedModules(input);
    out.push(REAL_MODULE);
    expect(input).toHaveLength(1);
  });

  it("handles missing input", () => {
    expect(orderedModules(null)).toEqual([]);
  });
});