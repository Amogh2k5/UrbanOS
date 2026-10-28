/**
 * Presentation helpers for the City Overview.
 *
 * Pure functions only - no React, no DOM - so the mapping between backend
 * values and what the user sees is unit-testable in isolation.
 *
 * Nothing here invents a value. When the backend reports "unavailable" the
 * helpers surface that fact rather than substituting a zero or a default.
 *
 * ---------------------------------------------------------------------------
 * COLOUR SYSTEM
 *
 * Two channels, kept strictly apart:
 *
 * 1. SHARED CARD FILL - one Slate surface across domains. Domain identity is
 *    carried by labels and data, while the separate status badge communicates
 *    risk.
 *
 * 2. STATUS BADGE (`statusBadgeClass`) - the only colour that carries risk
 *    meaning. Critical, Elevated, Normal and Unavailable stay distinguishable
 *    regardless of what the card behind them is coloured.
 *
 * Data provenance (live / forecast / historical) is a third axis and is kept
 * neutral, so a "Forecast" chip can never be misread as a warning.
 */
import type {
  CrossDomainImpact,
  DataKind,
  Finding,
} from "@/types/intelligence";
import type { ModuleSummary } from "@/services/api";

/**
 * The shared risk ladder. KPI status, signal severity and the city status band
 * all resolve onto it so the badges are comparable everywhere.
 */
export type Tone = "normal" | "low" | "elevated" | "high" | "critical" | "unavailable";

/* ------------------------------------------------------------------ *
 * Domain fills
 * ------------------------------------------------------------------ */

/** Domain cards share one Slate fill regardless of system identity. */
const SHARED_FILL = "bg-card";
const SHARED_HOVER = "hover:bg-card";
const SHARED_SHADOW = "shadow-slate-900/10 hover:shadow-slate-900/15";

export function domainFill(domainId?: string | null): string {
  void domainId;
  return SHARED_FILL;
}

export function domainFillHover(domainId?: string | null): string {
  void domainId;
  return SHARED_HOVER;
}

export function domainFillShadow(domainId?: string | null): string {
  void domainId;
  return SHARED_SHADOW;
}

/**
 * The shared dark-card treatment; the domain argument is retained for callers.
 * Use this so a card can never be half-themed.
 */
export function solidCardClass(domainId?: string | null, extra?: string): string {
  return [
    "solid-card",
    domainFill(domainId),
    domainFillHover(domainId),
    domainFillShadow(domainId),
    extra ?? "",
  ]
    .filter(Boolean)
    .join(" ");
}

/**
 * Ordinary KPI card on a domain detail page. The domain remains in the class
 * name for traceability, while all metric cards share the same light surface.
 */
export function domainCardClass(domainId: string, extra?: string): string {
  return [
    "solid-card",
    "metric-card",
    `metric-card-${domainId}`,
    "bg-white",
    "border",
    "border-line",
    "text-ink",
    extra ?? "",
  ]
    .filter(Boolean)
    .join(" ");
}

/** Detail-page and navigation headings take the domain colour as an accent. */
export function domainAccentClass(domainId?: string | null): string {
  void domainId;
  return "text-primary";
}

/* ------------------------------------------------------------------ *
 * Status badges - the only risk-bearing colour
 * ------------------------------------------------------------------ */

export function severityBand(severity?: string | null): "critical" | "high" | "moderate" | "low" {
  switch ((severity ?? "").toUpperCase()) {
    case "CRITICAL":
      return "critical";
    case "HIGH":
      return "high";
    case "MODERATE":
      return "moderate";
    default:
      return "low";
  }
}

export type ModuleStatus = "normal" | "elevated" | "high" | "critical" | "unavailable";

export function moduleStatusBand(status?: string | null): "critical" | "high" | "elevated" | "unavailable" | "normal" {
  switch ((status ?? "").toLowerCase()) {
    case "critical":
      return "critical";
    case "high":
      return "high";
    case "elevated":
      return "elevated";
    case "unavailable":
      return "unavailable";
    default:
      return "normal";
  }
}

export function toneForStatus(status?: string | null): Tone {
  return moduleStatusBand(status);
}

export function toneForSeverity(severity?: string | null): Tone {
  switch (severityBand(severity)) {
    case "critical":
      return "critical";
    case "high":
      return "high";
    case "moderate":
      return "elevated";
    default:
      return "low";
  }
}

/**
 * The city-wide status band. UNKNOWN resolves to the neutral unavailable badge:
 * it is the absence of an assessment, not a calm city.
 */
export function toneForCityStatus(status?: string | null): Tone {
  switch ((status ?? "").toUpperCase()) {
    case "NORMAL":
      return "normal";
    case "ELEVATED":
      return "elevated";
    case "DISRUPTED":
      return "high";
    case "CRITICAL":
      return "critical";
    default:
      return "unavailable";
  }
}

const BADGE_CLASSES: Record<Tone, string> = {
  normal: "badge-normal",
  low: "badge-normal",
  elevated: "badge-elevated",
  high: "badge-high",
  critical: "badge-critical",
  unavailable: "badge-unavailable",
};

export const BADGE_BASE = "status-badge";

export function statusBadgeClass(status?: string | null): string {
  return `${BADGE_BASE} ${BADGE_CLASSES[toneForStatus(status)]}`;
}

export function riskSignalBadgeClass(severity?: string | null): string {
  return `${BADGE_BASE} ${BADGE_CLASSES[toneForSeverity(severity)]}`;
}

export function cityStatusBadgeClass(status?: string | null): string {
  return `${BADGE_BASE} ${BADGE_CLASSES[toneForCityStatus(status)]}`;
}

export const ALL_BADGES: string[] = [...new Set(Object.values(BADGE_CLASSES))];

/**
 * Solid fill for a risk-signal card, keyed to severity.
 *
 * These use the `--color-signal-*` tokens, NOT the domain fills: severity is a
 * different axis from "which system", and reusing domain colours here would
 * make a critical Traffic signal look like the Traffic card.
 */
export const SEVERITY_FILLS: Record<Tone, { bg: string; hover: string; shadow: string }> = {
  critical: { bg: "bg-signal-critical", hover: "hover:bg-rose-700", shadow: "shadow-rose-600/20 hover:shadow-rose-600/30" },
  high: { bg: "bg-signal-high", hover: "hover:bg-orange-800", shadow: "shadow-orange-700/20 hover:shadow-orange-700/30" },
  elevated: { bg: "bg-signal-elevated", hover: "hover:bg-amber-800", shadow: "shadow-amber-700/20 hover:shadow-amber-700/30" },
  low: { bg: "bg-signal-low", hover: "hover:bg-blue-700", shadow: "shadow-blue-600/20 hover:shadow-blue-600/30" },
  normal: { bg: "bg-signal-low", hover: "hover:bg-blue-700", shadow: "shadow-blue-600/20 hover:shadow-blue-600/30" },
  unavailable: { bg: "bg-slate-500", hover: "hover:bg-slate-600", shadow: "shadow-slate-500/20 hover:shadow-slate-500/30" },
};

export function severityFillClass(severity?: string | null): string {
  const f = SEVERITY_FILLS[toneForSeverity(severity)];
  return ["solid-card", f.bg, f.hover, f.shadow].join(" ");
}

export function statusLabel(status?: string | null): string {
  const band = moduleStatusBand(status);
  if (band === "unavailable") return "Unavailable";
  return band.charAt(0).toUpperCase() + band.slice(1);
}

/**
 * Human label for a data kind. `unavailable` is called out explicitly so it is
 * never mistaken for a normal reading.
 */
export function dataKindLabel(kind?: DataKind | string | null): string {
  switch (kind) {
    case "live":
      return "Live";
    case "latest_available":
      return "Latest available";
    case "historical":
      return "Historical";
    case "forecast":
      return "Forecast";
    default:
      return "Unavailable";
  }
}

/** Provenance chips stay neutral so they can never read as severity. */
export function dataKindPillClass(kind?: DataKind | string | null): string {
  switch (kind) {
    case "live":
      return "bg-slate-100 text-slate-700 border-slate-200";
    case "latest_available":
      return "bg-slate-100 text-slate-600 border-slate-200";
    case "historical":
      return "bg-slate-100 text-slate-600 border-slate-200";
    case "forecast":
      return "bg-slate-100 text-slate-600 border-slate-200";
    default:
      return "bg-slate-50 text-slate-500 border-slate-200";
  }
}

/**
 * Format a KPI for display.
 *
 * Returns null when the backend supplied no KPI, which the UI must render as
 * "no supported metric" rather than as a zero.
 */
export function formatKpiValue(value: unknown, unit?: string | null): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return null;
    const rounded = Number.isInteger(value) ? String(value) : value.toFixed(1);
    return unit ? `${rounded} ${unit}` : rounded;
  }
  const text = String(value);
  return unit ? `${text} ${unit}` : text;
}

/** Only risk signals the coordinator actually validated (evidence required). */
export function isValidatedImpact(impact: CrossDomainImpact): boolean {
  return Array.isArray(impact?.evidence) && impact.evidence.length > 0;
}

/** Findings that actually state something, i.e. not the unavailable stub. */
export function substantiveFindings(findings?: Finding[] | null): Finding[] {
  return (findings ?? []).filter((f) => f && f.data_kind !== "unavailable");
}

/** Format an ISO timestamp for display; returns '' when absent or unparseable. */
export function formatTimestamp(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("en-SG", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Singapore",
  });
}

/** Cards the Overview renders: everything the backend returned, in order. */
export function orderedModules(modules?: ModuleSummary[] | null): ModuleSummary[] {
  return [...(modules ?? [])];
}
