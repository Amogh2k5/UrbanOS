"use client";

/** Structured, concise presentation of the City Coordinator report. */
import { Info, Sparkles, TriangleAlert } from "lucide-react";
import React from "react";
import type { CitySituationReport, DomainStatus } from "@/types/intelligence";
import { cityStatusBadgeClass, formatTimestamp } from "./presentation";

interface Props {
  narrative: string | null;
  report: CitySituationReport | null;
  assessmentReady: boolean;
  loading?: boolean;
  error?: string | null;
  onRequestReport?: () => void;
}

const DOMAIN_NAMES: Record<string, string> = {
  traffic: "Traffic", roads: "Roads", transit: "Transit", pm25: "Air Quality",
  weather: "Weather", flood: "Flood", fire: "Fire", crime: "Crime",
  water: "Water", waste: "Waste", energy: "Energy", land: "Land Use",
  housing: "Housing", construction: "Construction",
};

const CANONICAL_DOMAINS = Object.keys(DOMAIN_NAMES);

function readable(value?: string | null): string {
  if (!value) return "Unassessed";
  const text = value.replaceAll("_", " ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function readableNarrative(value: string): string {
  const summary = value.match(/^City status ([A-Z_ ]+) \(risk ([A-Z_ ]+), confidence ([A-Z_]+)\)\.?$/i);
  if (summary) {
    return `${readable(summary[1])} city status with ${readable(summary[2]).toLowerCase()} overall risk. Coordinator confidence is ${readable(summary[3]).toLowerCase()}.`;
  }
  return value
    .replaceAll("_", " ")
    .replace(/\bUNASSESSED\b/gi, "not assessed")
    .replace(/\bUNKNOWN\b/gi, "unknown")
    .replace(/\s+/g, " ")
    .trim();
}

function riskLabel(status?: DomainStatus): string {
  if (!status?.available) return "Unassessed";
  const risk = (status.overall_risk ?? status.risk_level ?? "").toUpperCase();
  if (["LOW", "MODERATE", "HIGH", "CRITICAL"].includes(risk)) return `${readable(risk)} risk`;
  const outcome = (status.overall_status ?? "").toUpperCase();
  if (!outcome || outcome === "UNKNOWN" || outcome === "UNASSESSED") return "Unassessed";
  return readable(outcome);
}

function assessmentSummary(report: CitySituationReport): string {
  const statuses = report.domain_status ?? {};
  const available = CANONICAL_DOMAINS.filter((domain) => statuses[domain]?.available).length;
  const notAssessed = CANONICAL_DOMAINS.length - available;
  const status = (report.overall_city_status ?? "UNKNOWN").toUpperCase();
  const risk = (report.overall_risk_level ?? "UNKNOWN").toUpperCase();
  const conclusion = status === "UNKNOWN" || risk === "UNKNOWN"
    ? "The coordinator could not determine a complete citywide risk rating."
    : `The coordinator reports ${readable(status).toLowerCase()} city status and ${readable(risk).toLowerCase()} overall risk.`;
  return `${conclusion} ${available} of ${CANONICAL_DOMAINS.length} domain reports were available; ${notAssessed} could not be assessed.`;
}

function DomainAssessments({ report }: { report: CitySituationReport }) {
  const entries = CANONICAL_DOMAINS
    .filter((domain) => report.domain_status?.[domain])
    .map((domain) => ({
      id: domain,
      name: report.domain_status[domain].display_name || DOMAIN_NAMES[domain],
      label: riskLabel(report.domain_status[domain]),
    }));
  if (!entries.length) return null;

  return (
    <section className="mt-5" data-testid="city-domain-assessments">
      <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500">Domain assessments</h3>
      <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {entries.map((entry) => (
          <li key={entry.id} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
            <span className="font-medium text-slate-800">{entry.name}</span>
            <span className="text-slate-600">{entry.label}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function recommendationPriority(text: string): string {
  const value = text.toUpperCase();
  if (value.includes("CRITICAL")) return "Critical priority";
  if (value.includes("HIGH")) return "High priority";
  if (value.includes("MODERATE")) return "Moderate priority";
  return "Operational guidance";
}

function readableRecommendation(text: string): string {
  return text.replace(/^([A-Z][A-Z+ _-]+):\s*/, (_match, prefix: string) => {
    const label = prefix.toLowerCase().replace(/\b\w/g, (char) => char.toUpperCase());
    return `${label}: `;
  });
}

function RecommendedActions({ report }: { report: CitySituationReport }) {
  const actions = (report.city_level_recommendations ?? [])
    .filter((text) => !text.trim().toUpperCase().startsWith("CITY:"));
  const groups = ["Critical priority", "High priority", "Moderate priority", "Operational guidance"]
    .map((priority) => ({
      priority,
      items: actions.filter((text) => recommendationPriority(text) === priority),
    }))
    .filter((group) => group.items.length > 0);

  return (
    <section className="mt-5" data-testid="city-recommended-actions">
      <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500">Recommended actions</h3>
      {groups.length ? groups.map((group) => (
        <div key={group.priority} className="mb-3">
          <h4 className="mb-1 text-xs font-semibold text-slate-700">{group.priority}</h4>
          <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed text-slate-700">
            {group.items.map((item, index) => <li key={`${group.priority}-${index}`}>{readableRecommendation(item)}</li>)}
          </ul>
        </div>
      )) : <p className="text-sm text-slate-600">No priority actions were issued by this assessment.</p>}
    </section>
  );
}

function DataCoverageSection({ report }: { report: CitySituationReport }) {
  const domainRows = CANONICAL_DOMAINS.flatMap((domain) => {
    const status = report.domain_status?.[domain];
    if (!status) return [];
    const sources = (status.findings ?? []).flatMap((finding) => finding.sources ?? []);
    const observed = (status.findings ?? []).map((finding) => finding.observed_at).filter(Boolean);
    const metadata = [
      status.source_status ? `Source: ${status.source_status}` : null,
      status.generated_at ? `Report: ${formatTimestamp(status.generated_at)}` : null,
      observed.length ? `Observation: ${formatTimestamp(observed[0]!)}` : null,
      sources.length ? `Sources: ${[...new Set(sources)].join(", ")}` : null,
    ].filter(Boolean).join(" · ");
    return [{ label: DOMAIN_NAMES[domain], value: `${status.available ? "Available" : "Unavailable"}${metadata ? ` · ${metadata}` : ""}` }];
  });
  const items = [
    ...(report.generated_at ? [{ label: "Assessment generated", value: formatTimestamp(report.generated_at) }] : []),
    ...(report.confidence ? [{ label: "Coordinator confidence", value: readable(report.confidence) }] : []),
    ...domainRows,
    ...(report.data_gaps ?? []).map((value) => ({ label: "Data gap", value })),
    ...(report.limitations ?? []).map((value) => ({ label: "Limitation", value })),
    ...(report.warnings ?? []).map((value) => ({ label: "Warning", value })),
    ...(report.errors ?? []).map((value) => ({ label: "Error", value })),
  ];
  if (!items.length) return null;

  return (
    <details className="mt-5 border-t border-slate-200 pt-3" data-testid="city-data-coverage">
      <summary className="cursor-pointer text-xs font-bold uppercase tracking-wider text-slate-500">Data coverage and limitations</summary>
      <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
        {items.map((item, index) => (
          <div key={`${item.label}-${index}`} className="rounded bg-slate-50 p-2">
            <dt className="font-semibold text-slate-700">{item.label}</dt>
            <dd className="mt-1 break-words text-slate-600">{item.value}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

export default function CitySituationPanel({
  narrative,
  report,
  assessmentReady,
  loading,
  error,
  onRequestReport,
}: Props) {
  const assessed = Boolean(report) && assessmentReady;
  const status = report?.overall_city_status ?? "UNKNOWN";
  const risk = report?.overall_risk_level ?? "UNKNOWN";

  return (
    <section data-testid="city-situation" className="card-panel overflow-hidden">
      <div className="card-panel-header flex items-center justify-between gap-4 px-6 py-4">
        <h2 className="flex items-center font-heading text-lg font-bold tracking-tight text-slate-900">
          <span className="mr-2.5 flex h-7 w-7 items-center justify-center rounded-lg bg-slate-900 text-white"><Sparkles size={14} /></span>
          City Situation
        </h2>
        {report && assessed ? (
          <div className="flex items-center gap-2 text-xs font-semibold">
            <span data-testid="city-status-badge" className={cityStatusBadgeClass(status)}>{readable(status)}</span>
            <span data-testid="city-risk" className="text-slate-600">{risk === "UNKNOWN" ? "Risk unassessed" : `${readable(risk)} risk`}</span>
          </div>
        ) : report ? <span data-testid="city-assessment-pending" className="status-badge badge-unavailable">Assessment pending</span> : null}
      </div>

      <div className="p-6 md:p-8">
        {loading ? (
          <div data-testid="city-situation-loading" className="space-y-3 animate-pulse" aria-busy="true">
            <div className="h-4 w-full rounded bg-slate-200" /><div className="h-4 w-5/6 rounded bg-slate-200" />
          </div>
        ) : error ? (
          <div data-testid="city-situation-error" className="flex items-start gap-3 text-sm text-rose-700">
            <TriangleAlert size={18} className="mt-0.5 shrink-0" />
            <p>City assessment unavailable: {error}. Cached domain summaries remain available.</p>
          </div>
        ) : report && assessed ? (
          <div data-testid="city-situation-narrative" className="max-w-5xl">
            <p className="text-sm leading-relaxed text-slate-700">{assessmentSummary(report)}</p>
            <DomainAssessments report={report} />
            {report.affected_zones?.length ? (
              <section className="mt-5" data-testid="city-affected-zones">
                <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500">Affected areas</h3>
                <div className="flex flex-wrap gap-2">
                  {report.affected_zones.map((area) => <span key={area} className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-700">{area}</span>)}
                </div>
              </section>
            ) : null}
            <RecommendedActions report={report} />
            <DataCoverageSection report={report} />
          </div>
        ) : narrative ? (
          <div data-testid="city-situation-narrative" className="max-w-4xl text-sm leading-relaxed text-slate-700">{readableNarrative(narrative)}</div>
        ) : (
          <div data-testid="city-situation-unavailable" className="flex items-start gap-3 text-sm text-slate-600">
            <Info size={18} className="mt-0.5 shrink-0" />
            <p>No city assessment is loaded. Domain cards show cached data or clearly marked unavailable values.</p>
          </div>
        )}

        {!report && onRequestReport ? (
          <button type="button" data-testid="request-city-report" onClick={onRequestReport} className="mt-5 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-700">
            Run full city assessment
          </button>
        ) : null}
      </div>
    </section>
  );
}
