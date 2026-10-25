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
 * 1. DOMAIN FILL (`DOMAIN_FILLS`) - a solid, medium-to-strong colour that
 *    identifies which domain a card belongs to. Used for KPI cards, and always
 *    paired with white text. A card's fill never encodes risk: a green
 *    Environment card can legitimately carry a red "Critical" badge.
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

/**
 * Every domain gets a solid fill. The shades are the reference palette where
 * white text already cleared AA, and one step darker where it did not:
 * cyan-600, amber-600 and emerald-600 all measured under 4.5:1 with white.
 */
export const DOMAIN_FILLS: Record<string, string> = {
  // Transport / Mobility
  traffic: "bg-dom-traffic",
  transit: "bg-dom-transit",
  roads: "bg-dom-roads",
  // Environment
  pm25: "bg-dom-pm25",
  weather: "bg-dom-weather",
  flood: "bg-dom-flood",
  // Public safety
  fire: "bg-dom-fire",
  crime: "bg-dom-crime",
  // Infrastructure
  water: "bg-dom-water",
  energy: "bg-dom-energy",
  waste: "bg-dom-waste",
  // Planning / Administration
  land: "bg-dom-land",
  housing: "bg-dom-housing",
  construction: "bg-dom-construction",
};;

/** Matching darker shade, used for hover and for pressed states. */
export const DOMAIN_FILLS_HOVER: Record<string, string> = {
  traffic: "hover:bg-blue-700",
  transit: "hover:bg-indigo-800",
  roads: "hover:bg-blue-800",
  pm25: "hover:bg-emerald-800",
  weather: "hover:bg-teal-800",
  flood: "hover:bg-sky-800",
  fire: "hover:bg-rose-700",
  crime: "hover:bg-rose-900",
  water: "hover:bg-cyan-800",
  energy: "hover:bg-amber-800",
  waste: "hover:bg-teal-800",
  land: "hover:bg-violet-800",
  housing: "hover:bg-violet-900",
  construction: "hover:bg-amber-950",
};

/** Matching coloured shadow, as in the reference. */
export const DOMAIN_FILLS_SHADOW: Record<string, string> = {
  traffic: "shadow-blue-600/20 hover:shadow-blue-600/30",
  transit: "shadow-indigo-700/20 hover:shadow-indigo-700/30",
  roads: "shadow-blue-700/20 hover:shadow-blue-700/30",
  pm25: "shadow-emerald-700/20 hover:shadow-emerald-700/30",
  weather: "shadow-teal-700/20 hover:shadow-teal-700/30",
  flood: "shadow-sky-700/20 hover:shadow-sky-700/30",
  fire: "shadow-rose-600/20 hover:shadow-rose-600/30",
  crime: "shadow-rose-800/20 hover:shadow-rose-800/30",
  water: "shadow-cyan-700/20 hover:shadow-cyan-700/30",
  energy: "shadow-amber-700/20 hover:shadow-amber-700/30",
  waste: "shadow-teal-700/20 hover:shadow-teal-700/30",
  land: "shadow-violet-700/20 hover:shadow-violet-700/30",
  housing: "shadow-violet-800/20 hover:shadow-violet-800/30",
  construction: "shadow-amber-900/20 hover:shadow-amber-900/30",
};

/** An unknown domain must not borrow a real domain's colour. */
export const DEFAULT_FILL = "bg-slate-500";
const DEFAULT_HOVER = "hover:bg-slate-600";
const DEFAULT_SHADOW = "shadow-slate-500/20 hover:shadow-slate-500/30";

export function domainFill(domainId?: string | null): string {
  if (!domainId) return DEFAULT_FILL;
  return DOMAIN_FILLS[domainId] ?? DEFAULT_FILL;
}

export function domainFillHover(domainId?: string | null): string {
  if (!domainId) return DEFAULT_HOVER;
  return DOMAIN_FILLS_HOVER[domainId] ?? DEFAULT_HOVER;
}

export function domainFillShadow(domainId?: string | null): string {
  if (!domainId) return DEFAULT_SHADOW;
  return DOMAIN_FILLS_SHADOW[domainId] ?? DEFAULT_SHADOW;
}

/**
 * The whole solid-card treatment for one domain: fill + hover + shadow.
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
 * Solid KPI card on a domain detail page.
 *
 * Alias for `solidCardClass`, kept as the name the detail pages import so a
 * domain's headline card is guaranteed to use the same fill, hover and shadow
 * as its card on the Overview.
 */
export function domainCardClass(domainId: string, extra?: string): string {
  return solidCardClass(domainId, extra);
}

/** Detail-page and navigation headings take the domain colour as an accent. */
export function domainAccentClass(domainId?: string | null): string {
  const token = domainFill(domainId).replace("bg-", "text-");
  return token;
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
