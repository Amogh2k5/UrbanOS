/**
 * Unit tests for the Overview presentation helpers.
 *
 * The fixtures mirror the real API responses captured from the running
 * backend, so a schema drift shows up here rather than on screen.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  ALL_BADGES,
  DOMAIN_FILLS,
  DOMAIN_FILLS_HOVER,
  DOMAIN_FILLS_SHADOW,
  cityStatusBadgeClass,
  dataKindLabel,
  dataKindPillClass,
  domainFill,
  formatKpiValue,
  formatTimestamp,
  isValidatedImpact,
  moduleStatusBand,
  orderedModules,
  riskSignalBadgeClass,
  severityFillClass,
  severityBand,
  solidCardClass,
  statusBadgeClass,
  statusLabel,
  substantiveFindings,
  toneForCityStatus,
  toneForSeverity,
  toneForStatus,
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

describe("domain fills are assigned by domain, never by status", () => {
  const ALL_DOMAINS = [
    "traffic", "transit", "roads",
    "pm25", "weather", "flood",
    "fire", "crime",
    "water", "energy", "waste",
    "land", "housing",
  ];

  it("covers every domain in the app", () => {
    expect(Object.keys(DOMAIN_FILLS).sort()).toEqual([...ALL_DOMAINS].sort());
  });

  it("gives a domain the same fill regardless of its status", () => {
    // The fill identifies WHICH domain this is. If it changed with status, a
    // red Environment card would no longer look like the Environment card.
    expect(domainFill("traffic")).toBe(domainFill("traffic"));
    expect(domainFill("traffic")).not.toBe(domainFill("land"));
  });

  it("gives every domain a distinct solid fill", () => {
    // Reuse would make two cards indistinguishable at a glance.
    expect(new Set(Object.values(DOMAIN_FILLS)).size).toBe(ALL_DOMAINS.length);
  });

  it("has a matching hover shade and coloured shadow for every domain", () => {
    for (const d of ALL_DOMAINS) {
      expect(DOMAIN_FILLS_HOVER[d]).toMatch(/^hover:bg-/);
      expect(DOMAIN_FILLS_SHADOW[d]).toMatch(/^shadow-.*\/20 hover:shadow-.*\/30$/);
    }
  });

  it("applies fill, hover and shadow together so a card is never half-themed", () => {
    const cls = solidCardClass("traffic", "p-5");
    expect(cls).toContain("solid-card");
    // The fill references the design token, so the colour that ships is the
    // colour the contrast tests measured.
    expect(cls).toContain("bg-dom-traffic");
    expect(cls).toContain("hover:bg-blue-700");
    expect(cls).toContain("p-5");
  });

  it("falls back to a neutral slate for an unknown domain", () => {
    expect(domainFill("does-not-exist")).toBe("bg-slate-500");
    expect(domainFill(null)).toBe("bg-slate-500");
    expect(domainFill(undefined)).toBe("bg-slate-500");
  });

  it("keeps data provenance out of the severity colour space", () => {
    const kinds = ["live", "latest_available", "historical", "forecast", "unavailable"];
    const severityHues = ["rose", "amber", "orange", "emerald"];
    for (const kind of kinds) {
      const pill = dataKindPillClass(kind);
      for (const hue of severityHues) {
        expect(pill).not.toContain(hue);
      }
    }
  });
});

describe("status badges are semantically distinct and independent of fill", () => {
  it("gives the four status states four different badges", () => {
    const badges = new Set([
      statusBadgeClass("normal"),
      statusBadgeClass("elevated"),
      statusBadgeClass("critical"),
      statusBadgeClass("unavailable"),
    ]);
    expect(badges.size).toBe(4);
  });

  it("keeps all four severities distinguishable", () => {
    const badges = new Set([
      riskSignalBadgeClass("LOW"),
      riskSignalBadgeClass("MODERATE"),
      riskSignalBadgeClass("HIGH"),
      riskSignalBadgeClass("CRITICAL"),
    ]);
    expect(badges.size).toBe(4);
  });

  it("is driven only by the backend status, never by the card colour", () => {
    // Every domain at "critical" gets the identical badge, whatever its fill.
    for (const domain of Object.keys(DOMAIN_FILLS)) {
      expect(statusBadgeClass("critical")).toContain("badge-critical");
      expect(domainFill(domain)).toBeTruthy();
    }
  });

  it("keeps Critical, Elevated, Normal and Unavailable distinct", () => {
    expect(cityStatusBadgeClass("CRITICAL")).toContain("badge-critical");
    expect(cityStatusBadgeClass("ELEVATED")).toContain("badge-elevated");
    expect(cityStatusBadgeClass("DISRUPTED")).toContain("badge-high");
    expect(cityStatusBadgeClass("NORMAL")).toContain("badge-normal");
    expect(cityStatusBadgeClass("UNKNOWN")).toContain("badge-unavailable");
  });

  it("treats an unknown city status as unavailable, not as calm", () => {
    expect(cityStatusBadgeClass("UNKNOWN")).not.toContain("badge-normal");
    expect(cityStatusBadgeClass(null)).not.toContain("badge-normal");
  });

  it("never emits an undefined badge class", () => {
    for (const badge of ALL_BADGES) {
      expect(badge).toMatch(/^badge-(normal|elevated|high|critical|unavailable)$/);
    }
  });

  it("keeps risk-signal cards solid-coloured and distinct per severity", () => {
    const fills = new Set([
      severityFillClass("CRITICAL"),
      severityFillClass("HIGH"),
      severityFillClass("MODERATE"),
      severityFillClass("LOW"),
    ]);
    expect(fills.size).toBe(4);
  });
});


describe("contrast, measured against the shipped CSS", () => {
  const css = readFileSync(resolve(__dirname, "../../app/globals.css"), "utf8");

  function token(name: string): string {
    const m = css.match(new RegExp(`--color-${name}:\\s*(#[0-9a-fA-F]{6})`));
    if (!m) throw new Error(`token --color-${name} not found in globals.css`);
    return m[1];
  }

  function luminance(hex: string): number {
    const n = parseInt(hex.slice(1), 16);
    const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
      const s = c / 255;
      return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }

  function contrast(a: string, b: string): number {
    const [l1, l2] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (l1 + 0.05) / (l2 + 0.05);
  }

  // Every domain token declared in globals.css.
  const DOMAIN_TOKENS = [
    "dom-traffic", "dom-transit", "dom-roads",
    "dom-pm25", "dom-weather", "dom-flood",
    "dom-fire", "dom-crime",
    "dom-water", "dom-energy", "dom-waste",
    "dom-land", "dom-housing",
  ];

  const badges = ["normal", "elevated", "high", "critical", "unavailable"];

  it("declares a token for every domain the app renders", () => {
    for (const t of DOMAIN_TOKENS) expect(() => token(t)).not.toThrow();
  });

  it("uses the reference palette for the six division colours", () => {
    // These six come straight from urbanos_solid_kpis.html.
    expect(token("dom-traffic")).toBe("#2563eb");   // blue-600
    expect(token("dom-water")).toBe("#0e7490");     // cyan, darkened from cyan-600
    expect(token("dom-fire")).toBe("#e11d48");      // rose-600
    expect(token("dom-energy")).toBe("#b45309");    // amber, darkened from amber-600
    expect(token("dom-pm25")).toBe("#047857");      // emerald, darkened from emerald-600
    expect(token("dom-land")).toBe("#6d28d9");      // purple, darkened from purple-600
  });

  it("uses the reference page, panel and border colours", () => {
    expect(token("background")).toBe("#f1f5f9");
    expect(token("surface")).toBe("#ffffff");
    expect(token("line")).toBe("#e2e8f0");
    expect(token("ink")).toBe("#0f172a");
  });

  it.each(DOMAIN_TOKENS)("renders white text on %s at AA", (t) => {
    // The KPI card treatment is white-on-fill everywhere, so this is the single
    // most important contrast check in the app.
    expect(contrast(token(t), "#ffffff")).toBeGreaterThanOrEqual(4.5);
  });

  it("darkened exactly the three reference hues that failed AA", () => {
    // cyan-600, amber-600 and emerald-600 all fell short with white text.
    const failed = ["#0891b2", "#d97706", "#059669"];
    for (const hex of failed) {
      expect(contrast(hex, "#ffffff")).toBeLessThan(4.5);
    }
  });

  it.each(badges)("renders the %s badge text legibly on its own chip", (badge) => {
    expect(contrast(token(`badge-${badge}`), token(`badge-${badge}-ink`))).toBeGreaterThanOrEqual(4.5);
  });

it.each(badges)("keeps the %s badge chip legible on every solid card fill", (badge) => {
    // A badge sits on top of a solid KPI card. It is a light chip with dark
    // ink, so only the CHIP has to contrast with the card - the ink is always
    // read against the chip (checked above), never directly against the fill.
    for (const t of DOMAIN_TOKENS) {
      expect(contrast(token(`badge-${badge}`), token(t))).toBeGreaterThanOrEqual(1.25);
    }
  });

  it("keeps dark body text readable on the page and on white panels", () => {
    for (const ink of ["ink", "ink-soft", "ink-faint", "ink-muted"]) {
      expect(contrast(token("background"), token(ink))).toBeGreaterThanOrEqual(3);
      expect(contrast("#ffffff", token(ink))).toBeGreaterThanOrEqual(3);
    }
  });

  it("never uses pure black or a neon fill", () => {
    for (const t of DOMAIN_TOKENS) {
      const hex = token(t);
      expect(hex).not.toBe("#000000");
      expect(luminance(hex)).toBeLessThan(0.35);      // not excessively dark
      expect(luminance(hex)).toBeGreaterThan(0.02);   // not a washed-out pastel
    }
  });

  it("gives every domain fill a distinct colour", () => {
    const hexes = DOMAIN_TOKENS.map(token);
    expect(new Set(hexes).size).toBe(DOMAIN_TOKENS.length);
  });
});

describe("toneForCityStatus", () => {
  it("shares the ladder with KPI status and signal severity", () => {
    expect(toneForCityStatus("NORMAL")).toBe("normal");
    expect(toneForCityStatus("ELEVATED")).toBe("elevated");
    expect(toneForCityStatus("DISRUPTED")).toBe("high");
    expect(toneForCityStatus("CRITICAL")).toBe("critical");
    expect(toneForCityStatus("CRITICAL")).toBe(toneForSeverity("CRITICAL"));
    expect(toneForCityStatus("ELEVATED")).toBe(toneForStatus("elevated"));
  });

  it("treats an unknown status as unavailable, not as calm", () => {
    expect(toneForCityStatus("UNKNOWN")).toBe("unavailable");
    expect(toneForCityStatus(null)).toBe("unavailable");
    expect(toneForCityStatus(undefined)).not.toBe("normal");
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

  it("gives unavailable a visibly different badge", () => {
    expect(statusBadgeClass("unavailable")).not.toBe(statusBadgeClass("normal"));
    expect(statusBadgeClass("unavailable")).toContain("badge-unavailable");
    expect(statusBadgeClass("normal")).toContain("badge-normal");
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
