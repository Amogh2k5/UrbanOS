"use client";

/**
 * AI City Situation.
 *
 * Renders the narrative produced by the grounded LLM layer, which in turn only
 * ever speaks about validated coordinator output. When the backend supplies no
 * narrative, this states that plainly - it never substitutes prose of its own.
 */
import { Sparkles, Info, TriangleAlert } from "lucide-react";
import type { CitySituationReport } from "@/types/intelligence";
import { formatTimestamp } from "./presentation";

interface Props {
  narrative: string | null;
  report: CitySituationReport | null;
  /**
   * True only when the coordinator assessment behind `report` has actually
   * been accepted as this page's City Situation.
   *
   * Required on purpose: a report object existing is not the same as a
   * validated city assessment, and the header must never present a status or
   * risk level as validated while the assessment is still pending. A defaulted
   * prop would quietly reintroduce exactly that.
   */
  assessmentReady: boolean;
  loading?: boolean;
  error?: string | null;
}

const BAND_TEXT: Record<string, string> = {
  NORMAL: "text-emerald-300",
  ELEVATED: "text-amber-300",
  DISRUPTED: "text-rose-300",
  CRITICAL: "text-rose-400",
  UNKNOWN: "text-slate-400",
};

const BAND_BORDER: Record<string, string> = {
  NORMAL: "border-emerald-500/40",
  ELEVATED: "border-amber-500/40",
  DISRUPTED: "border-rose-500/50",
  CRITICAL: "border-rose-600/60",
  UNKNOWN: "border-slate-700",
};

/**
 * Render a structured City Situation.
 *
 * The backend emits plain text with ALL-CAPS section headings on their own
 * line (SITUATION, CROSS-DOMAIN SIGNALS, DOMAIN ASSESSMENT, ...). Those are
 * rendered as headings and their bodies as separate blocks, so an operator can
 * scan the report instead of reading one run-on paragraph. Anything that does
 * not match the heading shape is passed through unchanged.
 */
function renderStructured(text: string): React.ReactNode {
  const lines = text.split("\n");
  const blocks: React.ReactNode[] = [];

  lines.forEach((raw, i) => {
    const line = raw.trim();
    if (!line) return;
    const isHeading = /^[A-Z][A-Z\s-]{4,}$/.test(line) && !/\d/.test(line);
    blocks.push(
      isHeading ? (
        <p
          key={i}
          data-testid="city-situation-section"
          className="text-[11px] font-bold uppercase tracking-widest text-slate-500 mt-5 mb-1 first:mt-0"
        >
          {line}
        </p>
      ) : (
        <p key={i} className="text-slate-200 leading-relaxed text-sm mb-1.5">
          {line}
        </p>
      )
    );
  });

  return <div data-testid="city-situation-structured">{blocks}</div>;
}

export default function CitySituationPanel({
  narrative,
  report,
  assessmentReady,
  loading,
  error,
}: Props) {
  const status = report?.overall_city_status ?? "UNKNOWN";
  const risk = report?.overall_risk_level ?? "UNKNOWN";
  const confidence = report?.confidence;
  // A report can exist while the assessment is still pending. Showing its
  // status/risk then would present an unvalidated value as a city conclusion,
  // so an explicit pending state is rendered instead.
  const assessed = Boolean(report) && assessmentReady;

  return (
    <section
      data-testid="city-situation"
      className="glass-panel rounded-2xl overflow-hidden border border-slate-800"
    >
      <div className="bg-slate-900/60 border-b border-slate-800 px-6 py-4 flex items-center justify-between gap-4">
        <h2 className="font-heading font-bold text-sm tracking-wide text-slate-100 flex items-center">
          <span className="w-6 h-6 rounded-md bg-slate-800 text-slate-200 flex items-center justify-center mr-2 border border-slate-700">
            <Sparkles size={12} />
          </span>
          AI City Situation
        </h2>

        {report &&
          (assessed ? (
            <div className="flex items-center gap-2 text-xs font-semibold">
              <span
                data-testid="city-status-badge"
                className={`px-2.5 py-1 rounded-lg border ${BAND_BORDER[status]} ${BAND_TEXT[status]}`}
              >
                {status}
              </span>
              <span data-testid="city-risk" className="text-slate-400">
                Risk {risk}
              </span>
              {confidence && (
                <span className="text-slate-500 font-mono" data-testid="city-confidence">
                  confidence {confidence}
                </span>
              )}
            </div>
          ) : (
            <span
              data-testid="city-assessment-pending"
              className="px-2.5 py-1 rounded-lg border border-slate-700 bg-slate-800/60 text-slate-400 text-xs font-semibold"
            >
              Assessment pending
            </span>
          ))}
      </div>

      <div className="p-6 md:p-8">
        {loading ? (
          <div
            data-testid="city-situation-loading"
            className="space-y-3 animate-pulse"
            aria-busy="true"
          >
            <div className="h-4 w-full rounded bg-slate-800" />
            <div className="h-4 w-5/6 rounded bg-slate-800" />
            <div className="h-4 w-2/3 rounded bg-slate-800" />
          </div>
        ) : error ? (
          <div
            data-testid="city-situation-error"
            className="flex items-start gap-3 text-sm text-rose-300"
          >
            <TriangleAlert size={18} className="mt-0.5 shrink-0" />
            <p>
              City situation unavailable: {error}. The deterministic figures below are unaffected.
            </p>
          </div>
        ) : narrative ? (
          <div data-testid="city-situation-narrative" className="max-w-4xl">
            {renderStructured(narrative)}
          </div>
        ) : (
          <div
            data-testid="city-situation-unavailable"
            className="flex items-start gap-3 text-sm text-slate-400"
          >
            <Info size={18} className="mt-0.5 shrink-0" />
            <p>
              No city narrative is available. This can happen when the coordinator
              report is still being computed or the narrative could not be validated
              against its evidence. The deterministic status, risk signals and KPI
              values below remain accurate.
            </p>
          </div>
        )}

        {report && (report.limitations?.length > 0 || report.affected_zones?.length > 0) && (
          <div className="mt-6 pt-4 border-t border-slate-800 flex flex-wrap gap-x-6 gap-y-2 text-xs text-slate-500">
            {report.affected_zones?.length > 0 && (
              <span data-testid="city-affected-zones">
                Affected zones: <span className="text-slate-400">{report.affected_zones.join(", ")}</span>
              </span>
            )}
            {report.limitations?.length > 0 && (
              <span data-testid="city-limitations" className="max-w-2xl">
                {report.limitations[0]}
              </span>
            )}
            {report.generated_at && (
              <span data-testid="city-generated-at">Updated {formatTimestamp(report.generated_at)}</span>
            )}
          </div>
        )}
      </div>
    </section>
  );
}