"use client";

/**
 * Active Risk Signals.
 *
 * Renders only coordinator cross-domain impacts that carry supporting
 * evidence. An impact with no evidence is correlation, not intelligence, so it
 * is filtered out here rather than displayed as a finding.
 */
import { Crosshair, ShieldAlert, Info } from "lucide-react";
import type { CrossDomainImpact } from "@/types/intelligence";
import {
  isValidatedImpact,
  riskSignalBorder,
  severityBand,
} from "./presentation";

const SEVERITY_PILL: Record<string, string> = {
  critical: "bg-rose-950 text-rose-200 border-rose-800",
  high: "bg-amber-950 text-amber-200 border-amber-800",
  moderate: "bg-amber-500/15 text-amber-200 border-amber-500/40",
  low: "bg-blue-500/15 text-blue-200 border-blue-500/40",
};

const SEVERITY_LABEL: Record<string, string> = {
  critical: "Critical",
  high: "High impact",
  moderate: "Moderate",
  low: "Low",
};

const DOMAIN_ICON: Record<string, string> = {
  flood_traffic: "Flood + Traffic",
  drain_flood_context: "Water + Flood",
  weather_flood: "Weather + Flood",
  air_quality_weather: "Air Quality + Weather",
  air_quality_traffic: "Air Quality + Traffic",
  multi_domain_high_risk: "Multiple systems under strain",
};

/** `air_quality` -> `Air Quality`. Never leak the raw id into the UI. */
function domainLabel(domain: string): string {
  const words = String(domain ?? "").replace(/_/g, " ").trim().split(/\s+/).filter(Boolean);
  return words.length ? words.map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ") : "City";
}

/** Human title for a signal type. */
function signalTitle(impact: CrossDomainImpact): string {
  if (DOMAIN_ICON[impact.type]) return DOMAIN_ICON[impact.type];
  const domains = (impact.domains_involved ?? []).map(domainLabel);
  if (domains.length >= 2) return `${domains.slice(0, 2).join(" + ")} at once`;
  return domainLabel(impact.type);
}

interface Props {
  impacts: CrossDomainImpact[] | null | undefined;
  loading?: boolean;
  error?: string | null;
  /** True when the coordinator ran but found nothing to report. */
  reportAvailable?: boolean;
}

/**
 * An impact the coordinator produced but could not back with evidence.
 * Revealing it would present correlation as intelligence, so it is withheld -
 * but it is still counted and disclosed, never silently dropped.
 */
type ImpactState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "unavailable" }
  | { kind: "no-data" }
  | { kind: "empty"; hidden: number }
  | { kind: "signals"; impacts: CrossDomainImpact[]; hidden: number };

/**
 * Classify what the caller actually has, so that "zero signals" is never
 * confused with "no data" or "could not be computed".
 */
export function classifyImpactState(props: Props): ImpactState {
  const { impacts, loading, error, reportAvailable } = props;

  if (loading) return { kind: "loading" };
  if (error) return { kind: "error", message: error };
  // The coordinator report itself is missing or failed: we know nothing about
  // cross-domain risk, which is not the same as knowing there is none.
  if (reportAvailable === false) return { kind: "unavailable" };
  // A loaded report that carried no impact array at all. Distinct from `[]`,
  // which is the coordinator affirmatively reporting zero signals.
  if (impacts === null || impacts === undefined) return { kind: "no-data" };

  const validated = impacts.filter(isValidatedImpact);
  const hidden = impacts.length - validated.length;

  if (validated.length === 0) return { kind: "empty", hidden };
  return { kind: "signals", impacts: validated, hidden };
}

export default function RiskSignals(props: Props) {
  const state = classifyImpactState(props);

  return (
    <section data-testid="risk-signals" aria-labelledby="risk-signals-heading">
      <h3
        id="risk-signals-heading"
        className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-4"
      >
        Active Risk Signals
      </h3>

      {state.kind === "loading" ? (
        <div
          data-testid="risk-signals-loading"
          className="grid grid-cols-1 md:grid-cols-2 gap-4 animate-pulse"
          aria-busy="true"
        >
          {[0, 1].map((i) => (
            <div key={i} className="h-28 rounded-xl bg-slate-800/60" />
          ))}
        </div>
      ) : state.kind === "error" ? (
        <div
          data-testid="risk-signals-error"
          className="flex items-start gap-3 text-sm text-rose-300 border border-rose-900/60 bg-rose-950/20 rounded-xl p-4"
        >
          <ShieldAlert size={18} className="mt-0.5 shrink-0" />
          <p>Risk signals unavailable: {state.message}.</p>
        </div>
      ) : state.kind === "unavailable" ? (
        <EmptyPanel
          testId="risk-signals-unavailable"
          icon={<ShieldAlert size={18} className="text-slate-500" />}
          title="Cross-domain assessment unavailable"
          body="Risk signals are not available because the coordinator report could not be computed. This says nothing about whether cross-domain risk exists."
        />
      ) : state.kind === "no-data" ? (
        <EmptyPanel
          testId="risk-signals-no-data"
          icon={<Info size={18} className="text-slate-500" />}
          title="No impact data returned"
          body="The coordinator report loaded but carried no cross-domain impact data, so no conclusion can be drawn. This is a data gap, not an all-clear."
        />
      ) : state.kind === "empty" ? (
        <>
          <EmptyPanel
            testId="risk-signals-empty"
            icon={<Info size={18} className="text-slate-500" />}
            title="No validated cross-domain signals"
            body={
              state.hidden > 0
                ? `The coordinator produced ${state.hidden} candidate signal${
                    state.hidden === 1 ? "" : "s"
                  }, but none carried supporting evidence, so none can be shown as a finding. This is not an all-clear: single-domain status, KPI readings and alerts elsewhere on this page are unchanged.`
                : "The coordinator ran and no domain pair met its evidence threshold. This is not an all-clear: single-domain status, KPI readings and alerts elsewhere on this page are unchanged."
            }
          />
          <HiddenDisclosure hidden={state.hidden} />
        </>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {state.impacts.map((impact) => {
              const band = severityBand(impact.severity);
              return (
                <article
                  key={impact.type}
                  data-testid="risk-signal-card"
                  data-severity={impact.severity}
                  className={`glass-panel rounded-xl border border-slate-800 border-l-4 ${riskSignalBorder(
                    impact.severity
                  )} p-4 flex flex-col justify-between`}
                >
                  <div>
                    <div className="flex justify-between items-start mb-2 gap-2">
                      <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-400 min-w-0">
                        <Crosshair size={13} className="shrink-0" />
                        <span className="truncate">
                          {(impact.domains_involved ?? []).map(domainLabel).join(" + ") ||
                            DOMAIN_ICON[impact.type] ||
                            impact.type}
                        </span>
                      </div>
                      <span
                        data-testid="risk-signal-severity"
                        className={`text-[10px] font-bold px-2 py-0.5 rounded border shrink-0 ${
                          SEVERITY_PILL[band]
                        }`}
                      >
                        {SEVERITY_LABEL[band]}
                      </span>
                    </div>

                    <h4 className="font-bold text-slate-100 text-sm mb-1">
                      {signalTitle(impact)}
                    </h4>
                    <p data-testid="risk-signal-description" className="text-xs text-slate-300">
                      {impact.description}
                    </p>

                    {impact.evidence?.length > 0 && (
                      <ul
                        data-testid="risk-signal-evidence"
                        className="mt-2 space-y-1 text-[11px] text-slate-400 border-l border-slate-700 pl-2"
                      >
                        {impact.evidence.map((item, i) => (
                          <li key={i}>{item}</li>
                        ))}
                      </ul>
                    )}

                    {impact.affected_zones?.length > 0 && (
                      <p data-testid="risk-signal-zones" className="mt-2 text-[11px] text-slate-400">
                        Affected: {impact.affected_zones.join(", ")}
                      </p>
                    )}
                  </div>
                </article>
              );
            })}
          </div>

          {state.hidden > 0 && <HiddenDisclosure hidden={state.hidden} />}
        </>
      )}
    </section>
  );
}

/**
 * Centred, deliberately quiet empty state.
 *
 * Deliberately does not say "no risks" or "all clear". It states what is
 * missing - validated cross-domain signals - and points at what is still
 * trustworthy, so absence of evidence is never read as evidence of safety.
 */
function EmptyPanel({
  testId,
  icon,
  title,
  body,
}: {
  testId: string;
  icon: React.ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div
      data-testid={testId}
      className="border border-slate-800 border-dashed rounded-xl px-5 py-8 flex flex-col items-center text-center gap-2"
    >
      <span
        aria-hidden="true"
        className="flex h-9 w-9 items-center justify-center rounded-full border border-slate-700 bg-slate-800/50"
      >
        {icon}
      </span>
      <p className="text-sm font-semibold text-slate-300">{title}</p>
      <p className="text-xs leading-relaxed text-slate-500 max-w-md">{body}</p>
    </div>
  );
}

/**
 * Disclosure for impacts withheld for lack of evidence. Rendered in both the
 * populated and empty states: candidates the coordinator produced but could not
 * justify are never silently discarded.
 */
function HiddenDisclosure({ hidden }: { hidden: number }) {
  if (hidden <= 0) return null;
  return (
    <p data-testid="risk-signals-dropped" className="mt-3 text-[11px] text-slate-500">
      {hidden} unvalidated signal{hidden === 1 ? "" : "s"} hidden: the coordinator
      produced {hidden === 1 ? "it" : "them"} without supporting evidence.
    </p>
  );
}