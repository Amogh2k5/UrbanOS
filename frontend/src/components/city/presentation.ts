/**
 * Presentation helpers for the City Overview.
 *
 * Pure functions only - no React, no DOM - so the mapping between backend
 * values and what the user sees is unit-testable in isolation.
 *
 * Nothing here invents a value. When the backend reports "unavailable" the
 * helpers surface that fact rather than substituting a zero or a default.
 */
import type {
  CrossDomainImpact,
  DataKind,
  Finding,
} from "@/types/intelligence";
import type { ModuleSummary } from "@/services/api";

/** Solid accent colour per domain, mirroring the reference design. */
export const MODULE_ACCENTS: Record<string, { bg: string; ring: string }> = {
  traffic: { bg: "bg-blue-600", ring: "shadow-blue-600/20" },
  roads: { bg: "bg-indigo-600", ring: "shadow-indigo-600/20" },
  transit: { bg: "bg-cyan-600", ring: "shadow-cyan-600/20" },
  pm25: { bg: "bg-emerald-600", ring: "shadow-emerald-600/20" },
  weather: { bg: "bg-teal-600", ring: "shadow-teal-600/20" },
  flood: { bg: "bg-sky-600", ring: "shadow-sky-600/20" },
  fire: { bg: "bg-rose-600", ring: "shadow-rose-600/20" },
  crime: { bg: "bg-orange-600", ring: "shadow-orange-600/20" },
  water: { bg: "bg-cyan-700", ring: "shadow-cyan-700/20" },
  land: { bg: "bg-violet-600", ring: "shadow-violet-600/20" },
};

export const DEFAULT_ACCENT = { bg: "bg-slate-600", ring: "shadow-slate-600/20" };

export function accentFor(moduleId: string) {
  return MODULE_ACCENTS[moduleId] ?? DEFAULT_ACCENT;
}

/** Severity band used for risk-signal borders and chips. */
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

/** Border colour for an Active Risk Signal card. */
export function riskSignalBorder(severity?: string | null): string {
  switch (severityBand(severity)) {
    case "critical":
      return "border-l-rose-700";
    case "high":
      return "border-l-rose-500";
    case "moderate":
      return "border-l-amber-500";
    default:
      return "border-l-blue-500";
  }
}

/** Module status from `/api/overview/city`, which uses lower-case bands. */
export type ModuleStatus = "normal" | "elevated" | "critical" | "unavailable";

export function moduleStatusBand(status?: string | null): "critical" | "elevated" | "unavailable" | "normal" {
  switch ((status ?? "").toLowerCase()) {
    case "critical":
      return "critical";
    case "elevated":
      return "elevated";
    case "unavailable":
      return "unavailable";
    default:
      return "normal";
  }
}

export function statusLabel(status?: string | null): string {
  const band = moduleStatusBand(status);
  if (band === "unavailable") return "Unavailable";
  return band.charAt(0).toUpperCase() + band.slice(1);
}

export function statusTextClass(status?: string | null): string {
  switch (moduleStatusBand(status)) {
    case "critical":
      return "text-rose-300";
    case "elevated":
      return "text-amber-300";
    case "unavailable":
      return "text-slate-400";
    default:
      return "text-emerald-300";
  }
}

export function statusPillClass(status?: string | null): string {
  switch (moduleStatusBand(status)) {
    case "critical":
      return "bg-rose-500/20 text-rose-200 border-rose-400/40";
    case "elevated":
      return "bg-amber-500/20 text-amber-200 border-amber-400/40";
    case "unavailable":
      return "bg-slate-700/60 text-slate-300 border-slate-600";
    default:
      return "bg-emerald-500/20 text-emerald-200 border-emerald-400/40";
  }
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

export function dataKindPillClass(kind?: DataKind | string | null): string {
  switch (kind) {
    case "live":
      return "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";
    case "latest_available":
      return "bg-sky-500/15 text-sky-300 border-sky-500/30";
    case "historical":
      return "bg-violet-500/15 text-violet-300 border-violet-500/30";
    case "forecast":
      return "bg-amber-500/15 text-amber-300 border-amber-500/30";
    default:
      return "bg-slate-700/60 text-slate-300 border-slate-600";
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