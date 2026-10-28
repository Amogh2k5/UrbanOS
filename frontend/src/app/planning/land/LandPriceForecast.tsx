"use client";

import { AlertTriangle, Info, TrendingUp } from "lucide-react";
import type { LandPriceForecastEvaluation, LandPriceForecastSection } from "@/services/api";
import { DATA_KIND_STYLE } from "./landConstants";

function fmtPerGfa(v?: number | null): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `$${v.toLocaleString("en-SG", { maximumFractionDigits: 0 })}`;
}

function KindTag({ kind }: { kind: string }) {
  const s = DATA_KIND_STYLE[kind as keyof typeof DATA_KIND_STYLE] ?? DATA_KIND_STYLE.unavailable;
  return (
    <span className={`text-[9px] font-bold tracking-[0.14em] px-2 py-0.5 rounded border ${s.cls}`}>
      {s.label}
    </span>
  );
}

function EvaluationTable({
  title,
  evaluation,
  forecastMethod,
}: {
  title: string;
  evaluation: LandPriceForecastEvaluation;
  forecastMethod: string;
}) {
  return (
    <div>
      <div className="text-[10px] font-bold tracking-[0.14em] text-slate-500 mb-1">{title}</div>
      {evaluation.status === "ok" ? (
        <div>
          <table className="w-full text-xs border border-slate-200 rounded-lg">
            <thead>
              <tr className="text-left text-[9px] tracking-[0.12em] text-slate-500 bg-white">
                <th className="py-1.5 px-2">METHOD</th>
                <th className="px-2 text-right">MAE ($/GFA)</th>
                <th className="px-2 text-right">PERIODS</th>
              </tr>
            </thead>
            <tbody>
              {evaluation.methods.map((m) => (
                <tr
                  key={m.method}
                  className={`border-b border-slate-200 ${
                    m.method === forecastMethod ? "bg-amber-50/50 text-slate-800" : "text-slate-600"
                  }`}
                >
                  <td className="py-1 px-2">{m.method}</td>
                  <td className="px-2 text-right font-mono">{m.mae.toLocaleString("en-SG", { maximumFractionDigits: 2 })}</td>
                  <td className="px-2 text-right font-mono">{m.test_periods}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="text-[10px] text-slate-500 mt-1">
            {evaluation.test_periods} one-year-ahead test period(s),
            {evaluation.window_start}–{evaluation.window_end},
            trained on the {evaluation.train_years_before_first_test} completed year(s) before the first test.
          </div>
        </div>
      ) : (
        <div className="text-[11px] text-slate-600 border border-slate-200 rounded-lg p-3 bg-slate-50">
          {evaluation.insufficient_reason ??
            "Insufficient completed annual observations for a walk-forward comparison."}
        </div>
      )}
    </div>
  );
}

/**
 * Baseline estimate for the next calendar year of the annual median
 * successful tender price per GFA unit, Residential (Non-Landed) awarded GLS
 * sites only. Renders an explicit unavailable state rather than zeros when the
 * backend cannot produce a forecast, and always discloses the nominal-price
 * and low-sample caveats. The forecast targets the year AFTER the in-progress
 * Singapore year, which is never used as training data or as the target.
 */
export default function LandPriceForecast({ section }: { section: LandPriceForecastSection | null }) {
  const unavailable = !section || section.data_kind === "unavailable" || section.forecast_value === null;

  return (
    <div className="glass-panel rounded-xl border border-slate-200 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <TrendingUp size={14} className="text-primary" />
          <h3 className="text-xs font-bold tracking-[0.18em] text-slate-600">
            HISTORICAL LAND TENDER PRICE / GFA — BASELINE ESTIMATE
          </h3>
        </div>
        <KindTag kind={unavailable ? "unavailable" : section.data_kind} />
      </div>

      {unavailable ? (
        <div className="text-sm text-slate-500">
          {section
            ? "No baseline estimate is available: there is insufficient eligible award history with valid prices and positive GFA in the Residential (Non-Landed) category. No value is shown rather than reporting a zero."
            : "The price-forecast section is unavailable; no baseline estimate can be shown."}
          {section && section.limitations.length > 0 && (
            <div className="mt-3 space-y-1">
              {section.limitations.slice(0, 3).map((l) => (
                <div key={l} className="text-[10px] text-slate-600 leading-4">{l}</div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-3 mb-3">
            <div className="rounded-lg border border-slate-200 p-3">
              <div className="text-[9px] tracking-[0.12em] text-slate-500">LATEST OBSERVED YEAR</div>
              <div className="text-lg font-mono font-bold text-slate-900 mt-1">
                {section!.latest_award_year ?? "—"}
              </div>
              <div className="text-[10px] text-slate-600 mt-1">
                {section!.latest_site_count !== null
                  ? `${section!.latest_site_count} eligible awarded site(s)`
                  : "site count unavailable"}
                {section!.latest_year_low_sample && (
                  <span className="text-yellow-700 font-semibold"> — low sample</span>
                )}
              </div>
            </div>
            <div className="rounded-lg border border-slate-200 p-3">
              <div className="text-[9px] tracking-[0.12em] text-slate-500">
                HISTORICAL LAND TENDER PRICE/GFA
              </div>
              <div className="text-lg font-mono font-bold text-slate-900 mt-1">
                {fmtPerGfa(section!.latest_median_price_per_gfa)}
                <span className="text-[10px] text-slate-500 font-normal ml-1">per GFA unit</span>
              </div>
              <div className="text-[10px] text-slate-600 mt-1">
                median of {section!.latest_award_year} awards, nominal SGD
              </div>
            </div>
            <div className="rounded-lg border border-highlight-special/50 bg-highlight-special/15 p-3">
              <div className="text-[9px] tracking-[0.12em] text-ink">BASELINE ESTIMATE {section!.forecast_year ?? ""}</div>
              <div className="text-lg font-mono font-bold text-ink mt-1">
                {fmtPerGfa(section!.forecast_value)}
                <span className="text-[10px] text-ink-soft font-normal ml-1">per GFA unit</span>
              </div>
              <div className="text-[10px] text-ink-soft mt-1">
                persistence: {section!.latest_award_year} median carried forward to{" "}
                {section!.forecast_year}
                {section!.current_year_excluded !== null && (
                  <> (next calendar year; in-progress {section!.current_year_excluded} excluded)</>
                )}{" "}
                — not a guaranteed price or market quote
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-[11px] text-slate-600 leading-5 mb-3">
            <div className="flex gap-2">
              <Info size={13} className="shrink-0 mt-0.5 text-slate-500" />
              <div>
                Nominal prices, not inflation-adjusted. This baseline covers awarded GLS
                sites in the <strong>{section!.development_code}</strong> development
                category only — it does not represent all Singapore land prices.
                {section!.current_year_excluded !== null && (
                  <> The still-in-progress year {section!.current_year_excluded} is excluded from training and evaluation.</>
                )}
              </div>
            </div>
          </div>

          {section!.warnings.length > 0 && (
            <div className="mb-3 space-y-2">
              {section!.warnings.map((w) => (
                <div
                  key={w}
                  className="rounded-lg border border-yellow-500/25 bg-yellow-50 p-2.5 text-[11px] text-yellow-800/90 flex gap-2"
                >
                  <AlertTriangle size={13} className="shrink-0 mt-0.5" />
                  <div>{w}</div>
                </div>
              ))}
            </div>
          )}

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <div>
              <div className="text-[10px] font-bold tracking-[0.14em] text-slate-500 mb-1">
                ANNUAL MEDIAN PRICE / GFA — {section!.development_code.toUpperCase()}
              </div>
              <div className="overflow-y-auto max-h-[220px] border border-slate-200 rounded-lg">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-white">
                    <tr className="text-left text-[9px] tracking-[0.12em] text-slate-500">
                      <th className="py-1.5 px-2">YEAR</th>
                      <th className="px-2 text-right">MEDIAN $/GFA</th>
                      <th className="px-2 text-right">SITES</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...section!.annual_medians].reverse().map((m) => (
                      <tr key={m.award_year} className="border-b border-slate-200 text-slate-600">
                        <td className="py-1 px-2 font-mono">{m.award_year}</td>
                        <td className="px-2 text-right font-mono">{fmtPerGfa(m.median_price_per_gfa)}</td>
                        <td className="px-2 text-right font-mono">
                          {m.site_count}
                          {m.low_sample && <span className="text-yellow-700 font-semibold" title="Low sample: fewer than 3 eligible sites"> · low sample</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="space-y-4">
              <EvaluationTable
                title="WALK-FORWARD BASELINE COMPARISON — FULL HISTORY"
                evaluation={section!.evaluation}
                forecastMethod={section!.forecast_method}
              />
              <EvaluationTable
                title="WALK-FORWARD BASELINE COMPARISON — RECENT 10 YEARS"
                evaluation={section!.evaluation_recent}
                forecastMethod={section!.forecast_method}
              />
            </div>
          </div>

          <div className="mt-3 space-y-1">
            {section!.limitations.map((l) => (
              <div key={l} className="text-[10px] text-slate-600 leading-4">{l}</div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
