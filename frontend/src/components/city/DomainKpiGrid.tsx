"use client";

/**
 * Domain Performance KPI cards.
 *
 * Each card navigates to its existing domain page. The insight action is a
 * separate control that opens the grounded KPI insight panel and must never
 * trigger the card's navigation.
 *
 * Unavailable data is rendered as such - never as zero.
 */
import Link from "next/link";
import { Sparkles, Car, Route, Train, Wind, CloudSun, Waves, Flame, ShieldAlert, Droplets, Map as MapIcon } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ModuleSummary } from "@/services/api";
import {
  accentFor,
  formatKpiValue,
  statusLabel,
  statusTextClass,
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
  land: MapIcon,
};

interface Props {
  modules: ModuleSummary[] | null | undefined;
  /** Domain ids that have at least one grounded finding. */
  domainsWithFindings: Set<string>;
  onOpenInsight: (moduleId: string) => void;
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
          className="text-xs font-bold text-slate-500 uppercase tracking-widest"
        >
          Domain Performance
        </h3>
        <span className="text-[10px] font-medium text-slate-500 bg-slate-800 px-2 py-0.5 rounded-full">
          Live backend values
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {(modules ?? []).map((mod) => {
          const Icon = ICONS[mod.id] ?? Sparkles;
          const accent = accentFor(mod.id);
          // Status and metric are independent facts. The backend only supplies
          // a KPI when a real measurement exists, so show whichever one it gave
          // us: water, for example, has a genuine potable-sales reading while
          // its risk assessment is unavailable. Suppressing the metric whenever
          // status is "unavailable" threw away a real number and made the card
          // look broken. formatKpiValue already returns null for no value, so
          // an absent KPI still renders "Unavailable".
          const kpiText = formatKpiValue(mod.kpi?.value, mod.kpi?.unit);

          return (
            <Link
              key={mod.id}
              href={mod.detail_route || "/"}
              data-testid="domain-kpi-card"
              data-module={mod.id}
              data-status={mod.status}
              className={`block ${accent.bg} rounded-2xl p-5 shadow-lg ${accent.ring} transition-all duration-200 hover:-translate-y-1 hover:shadow-xl group relative overflow-hidden`}
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
                        ? "bg-white/20 text-yellow-200 hover:bg-white/30"
                        : "bg-white/10 text-white/50 hover:bg-white/20 hover:text-white"
                    }`}
                  >
                    <Sparkles size={12} />
                  </button>
                </div>

                {kpiText ? (
                  <>
                    <p className="text-sm text-white/80 mb-1 font-medium">
                      {mod.kpi?.label}
                    </p>
                    <div className="flex items-baseline gap-2 mb-3">
                      <p
                        data-testid="kpi-value"
                        className="text-3xl font-bold text-white tracking-tight"
                      >
                        {kpiText}
                      </p>
                    </div>
                    <div className="inline-flex items-center px-2.5 py-1 rounded-lg bg-black/25 backdrop-blur-sm border border-white/10">
                      <p
                        data-testid="kpi-status"
                        className={`text-[11px] font-semibold text-white ${statusTextClass(
                          mod.status
                        )}`}
                      >
                        {statusLabel(mod.status)}
                      </p>
                    </div>
                  </>
                ) : (
                  <>
                    <p className="text-sm text-white/80 mb-1 font-medium">
                      {mod.kpi?.label ?? "No supported metric"}
                    </p>
                    <p
                      data-testid="kpi-value-unavailable"
                      className="text-xl font-bold text-white/60 tracking-tight mb-3"
                    >
                      Unavailable
                    </p>
                    <div className="inline-flex items-center px-2.5 py-1 rounded-lg bg-black/25 backdrop-blur-sm border border-white/10">
                      <p
                        data-testid="kpi-status"
                        className={`text-[11px] font-semibold text-white ${statusTextClass(
                          mod.status
                        )}`}
                      >
                        {statusLabel(mod.status)}
                      </p>
                    </div>
                  </>
                )}
              </div>
            </Link>
          );
        })}
      </div>

      {!modules || modules.length === 0 ? (
        <p data-testid="kpi-grid-empty" className="text-sm text-slate-400">
          No domain data available.
        </p>
      ) : null}
    </section>
  );
}