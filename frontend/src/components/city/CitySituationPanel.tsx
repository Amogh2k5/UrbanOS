"use client";

/**
 * AI City Situation.
 *
 * A white content panel, per the reference: this is a long structured report,
 * not a KPI, so it reads better on white than on a colour wash. Its status is
 * carried entirely by the semantic badge in the header - the panel's own
 * chrome is colourless by design, so nothing here can be mistaken for risk.
 *
 * The narrative itself only ever speaks about validated coordinator output.
 * When the backend supplies no narrative, this states that plainly.
 */
import { Sparkles, Info, TriangleAlert } from "lucide-react";
import type { CitySituationReport } from "@/types/intelligence";
import { cityStatusBadgeClass, formatTimestamp } from "./presentation";

interface Props {
  narrative: string | null;
  report: CitySituationReport | null;
  /**
   * True only when the coordinator assessment behind `report` has actually been
   * accepted as this page's City Situation. Required on purpose: a report object
   * existing is not the same as a validated city assessment, and the header must
   * never present a status or risk level as validated while still pending.
   */
  assessmentReady: boolean;
  loading?: boolean;
  error?: string | null;
}

/**
 * Render a structured City Situation.
 *
 * The backend emits plain text with ALL-CAPS section headings on their own line
 * (SITUATION, CROSS-DOMAIN SIGNALS, DOMAIN ASSESSMENT, ...). Those become
 * headings with their bodies as separate blocks, so an operator can scan the
 * report. Anything not matching the heading shape passes through unchanged.
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
          className="text-sm font-bold text-slate-700 uppercase tracking-wider mt-7 mb-2 first:mt-0 border-l-2 border-slate-200 pl-2.5"
        >
          {line}
        </p>
      ) : (
        <p key={i} className="text-[15px] leading-relaxed text-slate-700 mb-2">
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
    <section data-testid="city-situation" className="card-panel overflow-hidden">
      <div className="card-panel-header px-6 py-4 flex items-center justify-between gap-4">
        <h2 className="font-heading font-bold text-lg tracking-tight text-slate-900 flex items-center">
          <span className="w-7 h-7 rounded-lg bg-slate-900 text-white flex items-center justify-center mr-2.5">
            <Sparkles size={14} />
          </span>
          AI City Situation
        </h2>

        {report &&
          (assessed ? (
            <div className="flex items-center gap-2 text-xs font-semibold">
              <span data-testid="city-status-badge" className={cityStatusBadgeClass(status)}>
                {status}
              </span>
              <span data-testid="city-risk" className="text-slate-500">
                Risk {risk}
              </span>
              {confidence && (
                <span className="text-slate-500 font-mono" data-testid="city-confidence">
                  confidence {confidence}
                </span>
              )}
            </div>
          ) : (
            <span data-testid="city-assessment-pending" className="status-badge badge-unavailable">
              Assessment pending
            </span>
          ))}
      </div>

      <div className="p-6 md:p-8">
        {loading ? (
          <div data-testid="city-situation-loading" className="space-y-3 animate-pulse" aria-busy="true">
            <div className="h-4 w-full rounded bg-slate-200" />
            <div className="h-4 w-5/6 rounded bg-slate-200" />
            <div className="h-4 w-2/3 rounded bg-slate-200" />
          </div>
        ) : error ? (
          <div data-testid="city-situation-error" className="flex items-start gap-3 text-sm text-rose-700">
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
          <div data-testid="city-situation-unavailable" className="flex items-start gap-3 text-sm text-slate-500">
            <Info size={18} className="mt-0.5 shrink-0" />
            <p>
              No city narrative is available. This can happen when the coordinator report is still
              being computed or the narrative could not be validated against its evidence. The
              deterministic status, risk signals and KPI values below remain accurate.
            </p>
          </div>
        )}

        {(report && report.affected_zones?.length > 0) || report?.generated_at ? (
          <div className="mt-6 pt-4 border-t border-slate-100 flex flex-wrap gap-x-6 gap-y-2 text-xs text-slate-500">
            {report?.affected_zones && report.affected_zones.length > 0 && (
              <span data-testid="city-affected-zones">
                Affected zones: <span className="text-slate-700">{report.affected_zones.join(", ")}</span>
              </span>
            )}
            {report?.generated_at && (
              <span data-testid="city-generated-at">Updated {formatTimestamp(report.generated_at)}</span>
            )}
          </div>
        ) : null}

        {report?.limitations && report.limitations.length > 0 && (
          <p className="mt-3 text-xs text-slate-500" data-testid="city-limitations">
            {report.limitations[0]}
          </p>
        )}
      </div>
    </section>
  );
}
