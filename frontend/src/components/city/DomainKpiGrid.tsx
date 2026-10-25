"use client";

/**
 * Domain Performance KPI cards.
 *
 * Solid, medium-to-strong domain colour with white text - the defining
 * surface of the dashboard. The colour says which domain this is; the status
 * badge says how bad it is. Those are independent, so a green Environment card
 * carrying a red "Critical" badge is correct, not a contradiction.
 *
 * Every canonical UrbanOS module has a card here, including modules whose
 * data has not loaded: an unloaded card shows an honest "Unavailable" state
 * and never disappears. The legacy `environment` umbrella is not a module
 * and must never produce a second card next to PM2.5/Weather.
 *
 * Each card renders the module's intended metric list. Metrics are
 * independent: one unavailable metric renders an explicit placeholder
 * without hiding its siblings, and a real zero renders as 0.
 *
 * Each card navigates to its existing domain page. The insight action is a
 * separate control that must never trigger the card's navigation.
 * Unavailable data is rendered as such - never as zero.
 */
import Link from "next/link";
import { Sparkles, Car, Route, Train, Wind, CloudSun, Waves, Flame, ShieldAlert, Droplets, Map as MapIcon, Trash2, Zap, Building2, Construction } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ModuleSummary } from "@/services/api";
import {
  formatKpiValue,
  formatTimestamp,
  solidCardClass,
  statusBadgeClass,
  statusLabel,
} from "./presentation";

const ICONS: Record<string, LucideIcon> = {
  traffic: Car,
  roads: Route,
  transit: Train,
  pm25: Wind,
  weather: CloudSun,
  flood: Waves,
  fire: Flame,
  crime: ShieldAlert,
  water: Droplets,
  waste: Trash2,
  energy: Zap,
  land: MapIcon,
  housing: Building2,
  construction: Construction,
};

interface Props {
  modules: ModuleSummary[] | null | undefined;
  /** Domain ids that have at least one grounded finding. */
  domainsWithFindings: Set<string>;
  onOpenInsight: (moduleId: string) => void;
}

/** Metrics to list under the headline, one row each. The headline itself is
 * already rendered as the card's big number, so it is not repeated. */
function metricRows(mod: ModuleSummary) {
  const fallbackMetric = (mod.metrics ?? []).find((metric) => metric.value !== null && metric.value !== undefined)
    ?? mod.metrics?.[0];
  const headline = mod.kpi?.label ?? fallbackMetric?.label;
  return (mod.metrics ?? []).filter((m) => m.label !== headline);
}

export default function DomainKpiGrid({
  modules,
  domainsWithFindings,
  onOpenInsight,
}: Props) {
  return (
    <section aria-labelledby="domain-performance-heading">
      <div className="flex items-center justify-between mb-5">
        <h3
          id="domain-performance-heading"
          className="text-sm font-bold text-slate-700 uppercase tracking-wider px-3 mb-2 border-l-2 border-slate-200 pl-2.5"
        >
          Domain Performance
        </h3>
        <span className="text-[10px] font-medium text-slate-500 bg-white border border-slate-200 px-2.5 py-1 rounded-md">
          Cached summaries or unavailable
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {(modules ?? []).filter((mod) => mod.id !== "utilities").map((mod) => {
          const Icon = ICONS[mod.id] ?? Sparkles;
          // Status and metric are independent facts. The backend only supplies a
          // KPI when a real measurement exists, so show whichever one it gave
          // us: water, for example, has a genuine potable-sales reading while
          // its risk assessment is unavailable. Suppressing the metric whenever
          // status is "unavailable" threw away a real number and made the card
          // look broken. formatKpiValue already returns null for no value, so
          // an absent KPI still renders "Unavailable".
          const fallbackMetric = (mod.metrics ?? []).find((metric) => metric.value !== null && metric.value !== undefined)
            ?? mod.metrics?.[0];
          const headlineLabel = mod.kpi?.label ?? fallbackMetric?.label;
          const headlineValue = mod.kpi ?? fallbackMetric;
          const kpiText = formatKpiValue(headlineValue?.value, headlineValue?.unit);

          return (
            <Link
              key={mod.id}
              href={mod.detail_route || "/"}
              data-testid="domain-kpi-card"
              data-module={mod.id}
              data-status={mod.status}
              className={solidCardClass(mod.id, "block p-5 group")}
            >
              <div className="absolute inset-0 card-pattern opacity-30" aria-hidden="true" />
              <div
                className="absolute -right-4 -top-4 w-24 h-24 bg-white/10 rounded-full blur-2xl"
                aria-hidden="true"
              />

              <div className="relative z-10">
                <div className="flex justify-between items-start mb-5">
                  <div className="flex items-center gap-2.5">
                    <div className="w-9 h-9 rounded-xl bg-white/20 text-white flex items-center justify-center backdrop-blur-sm">
                      <Icon size={17} />
                    </div>
                    <p className="text-xs font-bold text-white uppercase tracking-wider">
                      {mod.name}
                    </p>
                  </div>

                  <button
                    type="button"
                    aria-label={`Explain ${mod.name} metric`}
                    data-testid="kpi-insight-button"
                    data-module={mod.id}
                    title="Metric insight"
                    onClick={(e) => {
                      // Keep the click away from the surrounding <Link>.
                      e.preventDefault();
                      e.stopPropagation();
                      onOpenInsight(mod.id);
                    }}
                    className={`w-7 h-7 rounded-full flex items-center justify-center transition-colors shrink-0 ${
                      domainsWithFindings.has(mod.id)
                        ? "bg-white text-slate-900 hover:bg-white/90"
                        : "bg-white/10 text-white/90 hover:bg-white/25 hover:text-white"
                    }`}
                  >
                    <Sparkles size={12} />
                  </button>
                </div>

                <p className="text-sm text-white/90 mb-1 font-medium">
                  {headlineLabel ?? "No supported metric"}
                </p>

                {kpiText ? (
                  <div className="flex items-baseline gap-2 mb-3">
                    <p data-testid="kpi-value" className="text-3xl font-bold text-white tracking-tight">
                      {kpiText}
                    </p>
                  </div>
                ) : (
                  <p data-testid="kpi-value-unavailable" className="text-xl font-bold text-white/90 tracking-tight mb-3">
                    Unavailable
                  </p>
                )}

                {(() => {
                  const rows = metricRows(mod);
                  if (rows.length === 0) return null;
                  return (
                    <div data-testid="kpi-metrics" className="mb-3 space-y-1">
                      {rows.map((m) => {
                        const formatted = formatKpiValue(m.value, m.unit);
                        return (
                          <div
                            key={m.key}
                            data-testid={`kpi-metric-${m.key}`}
                            className="flex items-baseline justify-between gap-2 text-xs"
                          >
                            <span className="text-white/90">{m.label}</span>
                            <span className={`font-mono text-right ${formatted ? "text-white" : "text-white/70"}`}>
                              {formatted ?? "Unavailable"}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  );
                })()}

                <span data-testid="kpi-status" className={statusBadgeClass(mod.status)}>
                  {statusLabel(mod.status)}
                </span>

                {mod.updated_at && (
                  <p className="mt-3 text-[11px] text-white/90">
                    Updated {formatTimestamp(mod.updated_at)}
                  </p>
                )}
                {mod.data_state && (
                  <p data-testid="kpi-data-state" className="mt-2 text-[10px] text-white/80">
                    {mod.data_state === "stale" && mod.age_seconds != null
                      ? `Stale data · ${Math.round(mod.age_seconds / 60)} min old`
                      : mod.data_state === "stale"
                        ? "Stale data"
                        : mod.data_state === "partial"
                          ? "Partial data"
                          : mod.data_state === "unavailable"
                            ? "Data unavailable"
                            : "Data available"}
                  </p>
                )}
                {mod.id === "fire" && (
                  <p data-testid="fire-card-limitation" className="mt-2 text-[10px] text-white/80">
                    SCDF published reports; not a complete real-time dispatch feed.
                  </p>
                )}
              </div>
            </Link>
          );
        })}
      </div>

      {!modules || modules.length === 0 ? (
        <p data-testid="kpi-grid-empty" className="text-sm text-slate-500">
          No domain data available.
        </p>
      ) : null}
    </section>
  );
}
