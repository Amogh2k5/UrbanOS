"use client";

/** Structured, concise presentation of the City Coordinator report. */
import { Info, Sparkles, TriangleAlert } from "lucide-react";
import React from "react";
import type { CitySituationReport, DomainStatus } from "@/types/intelligence";
import { cityStatusBadgeClass, statusBadgeClass, substantiveFindings } from "./presentation";

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

function cleanDisplayText(value?: string | null): string {
  if (!value) return "Data currently unavailable";
  const text = value
    .replace(/\b[\w]*_?(?:id|uuid|debug|metadata|source_status)\s*[:=]\s*[^,;\s]+/gi, "")
    .replace(/\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b/gi, "")
    .replaceAll("_", " ").replace(/\s+/g, " ").trim();
  if (!text || text.startsWith("{") || text.startsWith("[") || /"\w+"\s*:/.test(text)) return "Data currently unavailable";
  return text;
}

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
  return cleanDisplayText(value)
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

function generateDomainNarrative(domain: string, status: DomainStatus): string {
  if (!status.available) {
    return `${DOMAIN_NAMES[domain] || domain} status could not be assessed with the available data.`;
  }

  const risk = (status.overall_risk ?? status.risk_level ?? "").toUpperCase();
  const statusText = (status.overall_status ?? "").toUpperCase();
  const domainName = DOMAIN_NAMES[domain] || domain;

  // Check for findings with evidence
  const findings = status.findings ?? [];
  const substantive = substantiveFindings(status.findings);
  const hasEvidence = substantive.length > 0;

  // Build narrative based on risk level and available information
  let narrative = "";

  if (risk === "CRITICAL" || risk === "HIGH") {
    narrative = `${domainName} risk is ${readable(risk).toLowerCase()}. `;
    if (status.primary_risk_factors?.length > 0) {
      narrative += `Key factors: ${status.primary_risk_factors.map(cleanDisplayText).join(", ")}. `;
    }
    if (substantive.length > 0) {
      const firstFinding = substantive[0];
      narrative += `${cleanDisplayText(firstFinding.answer)} `;
    }
    narrative += "Review live data and consider mitigation measures.";
  } else if (risk === "MODERATE" || risk === "ELEVATED") {
    narrative = `${domainName} conditions are ${readable(risk).toLowerCase()}. `;
    if (substantive.length > 0) {
      const firstFinding = substantive[0];
      narrative += `${cleanDisplayText(firstFinding.answer)} `;
    }
    narrative += "Monitor conditions and review latest data.";
  } else if (risk === "LOW" || risk === "NORMAL") {
    narrative = `${domainName} conditions are normal according to the available assessment.`;
    if (substantive.length > 0) {
      const firstFinding = substantive[0];
      narrative += ` ${cleanDisplayText(firstFinding.answer)}.`;
    }
  } else if (status.available) {
    narrative = `${domainName} status is ${readable(status.overall_status || "unknown").toLowerCase()}. `;
    if (substantive.length > 0) {
      const firstFinding = substantive[0];
      narrative += ` ${cleanDisplayText(firstFinding.answer)}.`;
    }
    if (status.primary_risk_factors?.length > 0) {
      narrative += `Factors to monitor: ${status.primary_risk_factors.map(cleanDisplayText).join(", ")}.`;
    }
  } else {
    return `${domainName} status could not be assessed with the available data.`;
  }

  return narrative;
}

function DomainAssessments({ report }: { report: CitySituationReport }) {
  const entries = CANONICAL_DOMAINS
    .filter((domain) => report.domain_status?.[domain])
    .map((domain) => {
      const status = report.domain_status[domain];
      const narrative = generateDomainNarrative(domain, status);
      return {
        id: domain,
        name: DOMAIN_NAMES[domain],
        label: riskLabel(status),
        narrative,
      };
    });
  if (!entries.length) return null;

  return (
    <section className="mt-5" data-testid="city-domain-assessments">
      <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500">Domain assessments</h3>
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {entries.map((entry) => (
          <li
            key={entry.id}
            className="rounded-lg border border-slate-200 bg-white p-4 text-sm"
          >
            <div className="flex items-start justify-between gap-3 mb-2">
              <span className="font-medium text-slate-800">{entry.name}</span>
              <span className={statusBadgeClass(entry.label)}>{entry.label}</span>
            </div>
            <p className="text-slate-600 text-sm leading-relaxed">{entry.narrative}</p>
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
  const cleaned = cleanDisplayText(text);
  return cleaned.replace(/^([A-Z][A-Z+ -]+):\s*/, (_match, prefix: string) => {
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
    return [{ label: DOMAIN_NAMES[domain], value: status.available ? "Assessment available" : "Data currently unavailable" }];
  });
  const items = [
    ...(report.confidence ? [{ label: "Coordinator confidence", value: readable(report.confidence) }] : []),
    ...domainRows,
    ...(report.data_gaps ?? []).map((value) => ({ label: "Data gap", value: cleanDisplayText(value) })),
    ...(report.limitations ?? []).map((value) => ({ label: "Limitation", value: cleanDisplayText(value) })),
    ...(report.warnings ?? []).map((value) => ({ label: "Note", value: cleanDisplayText(value) })),
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
          <span className="mr-2.5 flex h-7 w-7 items-center justify-center rounded-lg bg-obsidian text-white"><Sparkles size={14} /></span>
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
            <p>City assessment is temporarily unavailable. Cached domain summaries remain available.</p>
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
            <p>Data currently unavailable. Domain cards show cached information where available.</p>
          </div>
        )}

        {!report && onRequestReport ? (
          <button type="button" data-testid="request-city-report" onClick={onRequestReport} className="mt-5 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-obsidian hover:bg-primary-dim">
            Run full city assessment
          </button>
        ) : null}
      </div>
    </section>
  );
}
