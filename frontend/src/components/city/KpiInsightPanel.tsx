"use client";

/**
 * KPI insight panel.
 *
 * Shows only findings the backend produced. When a domain has no grounded
 * finding - including the case where the domain is simply unavailable - this
 * says so explicitly instead of composing a plausible-sounding explanation.
 */
import { X, Sparkles, Info, Clock, AlertTriangle } from "lucide-react";
import type { DomainStatus, Finding } from "@/types/intelligence";
import {
  dataKindLabel,
  dataKindPillClass,
  formatTimestamp,
} from "./presentation";

interface Props {
  domainId: string;
  status: DomainStatus | null | undefined;
  onClose: () => void;
}

function FindingRow({ finding }: { finding: Finding }) {
  return (
    <li
      data-testid="kpi-insight-finding"
      data-kind={finding.data_kind}
      className="border border-slate-200 rounded-lg p-3 bg-slate-50"
    >
      <div className="flex items-start justify-between gap-3 mb-1.5">
        <h4 className="text-sm font-semibold text-slate-800">{finding.title}</h4>
        <span
          data-testid="kpi-insight-kind"
          className={`text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded border shrink-0 ${dataKindPillClass(
            finding.data_kind
          )}`}
        >
          {dataKindLabel(finding.data_kind)}
        </span>
      </div>

      {finding.question && (
        <p className="text-[11px] text-slate-500 mb-1 italic">{finding.question}</p>
      )}

      <p data-testid="kpi-insight-answer" className="text-xs text-slate-600 leading-relaxed">
        {finding.answer}
      </p>

      {finding.metrics && Object.keys(finding.metrics).length > 0 && (
        <dl
          data-testid="kpi-insight-metrics"
          className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px]"
        >
          {Object.entries(finding.metrics)
            .filter(([, v]) => v !== null && v !== undefined)
            .map(([k, v]) => (
              <div key={k} className="flex gap-1">
                <dt className="text-slate-500">{k.replace(/_/g, " ")}</dt>
                <dd className="text-slate-600 font-mono">{String(v)}</dd>
              </div>
            ))}
        </dl>
      )}

      {finding.evidence?.length > 0 && (
        <ul
          data-testid="kpi-insight-evidence"
          className="mt-2 space-y-0.5 text-[11px] text-slate-500 border-l border-slate-200 pl-2"
        >
          {finding.evidence.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}

      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-slate-500">
        {finding.observed_at && (
          <span data-testid="kpi-insight-observed" className="flex items-center gap-1">
            <Clock size={10} />
            {formatTimestamp(finding.observed_at)}
          </span>
        )}
        {finding.affected_area && (
          <span data-testid="kpi-insight-area">Area: {finding.affected_area}</span>
        )}
        {finding.freshness && finding.freshness !== "unknown" && (
          <span data-testid="kpi-insight-freshness">Freshness: {finding.freshness}</span>
        )}
      </div>

      {finding.limitations?.length > 0 && (
        <ul
          data-testid="kpi-insight-limitations"
          className="mt-2 space-y-0.5 text-[11px] text-amber-800/80"
        >
          {finding.limitations.map((l, i) => (
            <li key={i} className="flex gap-1">
              <AlertTriangle size={11} className="mt-0.5 shrink-0" />
              {l}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export default function KpiInsightPanel({ domainId, status, onClose }: Props) {
  const findings = status?.findings ?? [];
  const substantive = findings.filter((f) => f.data_kind !== "unavailable");
  const domainUnavailable = status ? !status.available : true;

  return (
    <div
      className="fixed inset-0 z-[80] flex items-end sm:items-center justify-center bg-slate-900/50 backdrop-blur-sm p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        data-testid="kpi-insight-panel"
        role="dialog"
        aria-modal="true"
        aria-label={`${status?.display_name ?? domainId} metric insight`}
        onClick={(e) => e.stopPropagation()}
        className="card-panel rounded-2xl w-full max-w-2xl max-h-[80vh] flex flex-col"
      >
        <div className="flex items-center justify-between px-6 py-4 card-panel-header shrink-0">
          <h3 className="font-heading font-bold text-sm text-slate-800 flex items-center">
            <Sparkles size={14} className="mr-2 text-[var(--color-primary)]" />
            {status?.display_name ?? domainId} &middot; Metric Insight
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close insight"
            data-testid="kpi-insight-close"
            className="text-slate-500 hover:text-slate-700 transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <div className="p-6 overflow-y-auto space-y-4 custom-scrollbar">
          {domainUnavailable && (
            <div
              data-testid="kpi-insight-unavailable"
              className="flex items-start gap-3 text-sm text-slate-700 border border-amber-200 bg-amber-50 rounded-lg p-3"
            >
              <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-600" />
              <p>
                {status?.error
                  ? `This domain could not be assessed: ${status.error}`
                  : "This domain could not be assessed."}{" "}
                Absence of data is not evidence of normal conditions.
              </p>
            </div>
          )}

          {substantive.length > 0 ? (
            <ul className="space-y-3" data-testid="kpi-insight-list">
              {substantive.map((f) => (
                <FindingRow key={f.id} finding={f} />
              ))}
            </ul>
          ) : (
            !domainUnavailable && (
              <div
                data-testid="kpi-insight-none"
                className="flex items-start gap-3 text-sm text-slate-500"
              >
                <Info size={16} className="mt-0.5 shrink-0" />
                <p>
                  No grounded insight is available for this domain yet. UrbanOS only
                  shows explanations it can support with evidence, so it will not
                  invent one here.
                </p>
              </div>
            )
          )}

          {status?.limitations && status.limitations.length > 0 && (
            <div data-testid="kpi-insight-domain-limitations" className="pt-2 border-t border-slate-200">
              <h4 className="text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-1">
                Domain limitations
              </h4>
              <ul className="space-y-0.5 text-[11px] text-slate-500">
                {status.limitations.slice(0, 4).map((l, i) => (
                  <li key={i}>{l}</li>
                ))}
              </ul>
            </div>
          )}

          {status?.generated_at && (
            <p className="text-[11px] text-slate-500 font-mono">
              Domain data as of {formatTimestamp(status.generated_at)}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
