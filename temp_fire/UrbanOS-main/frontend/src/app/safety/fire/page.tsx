"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Flame,
  MapPin,
  RefreshCw,
  ShieldAlert,
  History,
} from "lucide-react";
import FireMap from "./FireMap";
import { fetchFireReport, type FireIncident, type FireReport } from "@/services/api";

const REGIONS = ["Central", "East", "North", "South", "West"];

function KpiCard({
  label,
  value,
  icon,
  tone = "text-white",
  note,
}: {
  label: string;
  value: string;
  icon: ReactNode;
  tone?: string;
  note?: string;
}) {
  return (
    <div className="glass-panel rounded-xl p-4 border border-gray-800/60">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 text-gray-400">
          {icon}
          <span className="text-[10px] font-bold tracking-[0.18em]">{label}</span>
        </div>
      </div>
      <div className={`text-2xl font-mono font-bold ${tone}`}>{value}</div>
      {note && <div className="text-[10px] text-gray-500 mt-1">{note}</div>}
    </div>
  );
}

function formatTime(value?: string | null) {
  if (!value) return "Time not supplied";
  return new Date(value).toLocaleString("en-SG", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function severityClass(severity: FireIncident["severity"]) {
  if (severity === "CRITICAL") return "text-red-400 bg-red-500/10 border-red-500/20";
  if (severity === "HIGH") return "text-orange-400 bg-orange-500/10 border-orange-500/20";
  if (severity === "MODERATE") return "text-yellow-400 bg-yellow-500/10 border-yellow-500/20";
  return "text-gray-400 bg-gray-500/10 border-gray-500/20";
}

export default function FirePage() {
  const [report, setReport] = useState<FireReport | null>(null);
  const [selected, setSelected] = useState<FireIncident | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      setLoading(true);
      const next = await fetchFireReport();
      setReport(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fire data unavailable");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const timer = setInterval(load, 60_000);
    return () => clearInterval(timer);
  }, []);

  const mappedIncidents = useMemo(
    () => report?.recent_incidents ?? [],
    [report]
  );

  const sourceLabel =
    report?.source_status === "published_incidents"
      ? "SCDF published incident reports"
      : report?.source_status === "historical_only"
      ? "Historical fire statistics only"
      : "Source unavailable";

  return (
    <div className="flex flex-col h-full overflow-y-auto bg-[var(--color-background)] text-[var(--color-foreground)]">
      <div className="w-full max-w-[1920px] mx-auto px-4 md:px-6 lg:px-8 pb-10 pt-5">
        <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4 mb-5">
          <div>
            <div className="text-[10px] uppercase tracking-[0.25em] text-red-400 font-bold">
              Safety domain
            </div>
            <h1 className="text-2xl md:text-3xl font-heading font-bold text-white mt-1">
              Fire & Safety
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              Current published fire-incident intelligence for Singapore — no fire prediction model.
            </p>
          </div>
          <button
            type="button"
            onClick={load}
            className="self-start lg:self-auto inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-700 text-xs text-gray-300 hover:bg-gray-800"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>

        {error && (
          <div className="mb-5 glass-panel p-4 rounded-xl border border-red-500/30 bg-red-950/20 text-red-300 text-sm flex gap-3">
            <ShieldAlert size={18} className="shrink-0" />
            <div>
              <div className="font-semibold">Fire data unavailable</div>
              <div className="text-xs text-red-300/70 mt-1">{error}</div>
            </div>
          </div>
        )}

        {report && (
          <>
            <div className="mb-5 glass-panel p-3 rounded-xl border border-gray-800/60 text-xs text-gray-400 flex flex-wrap items-center gap-x-5 gap-y-2">
              <span className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${report.source_status === "published_incidents" ? "bg-green-400" : "bg-yellow-400"}`} />
                Source: <strong className="text-gray-200">{sourceLabel}</strong>
              </span>
              <span>Updated {formatTime(report.generated_at)}</span>
              <span className="text-gray-600">ML: not used</span>
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
              <KpiCard
                label="ACTIVE"
                value={report.active_incident_count == null ? "—" : String(report.active_incident_count)}
                icon={<Flame size={16} className="text-red-400" />}
                tone="text-red-400"
                note={report.active_incident_count == null ? "Not established by source" : "Published active reports"}
              />
              <KpiCard
                label="CRITICAL"
                value={report.critical_incident_count == null ? "—" : String(report.critical_incident_count)}
                icon={<AlertTriangle size={16} className="text-orange-400" />}
                tone="text-orange-400"
                note="Source-supported classification"
              />
              <KpiCard
                label="TODAY"
                value={report.incidents_today == null ? "—" : String(report.incidents_today)}
                icon={<Clock3 size={16} className="text-cyan-400" />}
                tone="text-cyan-400"
                note="Published incident reports"
              />
              <KpiCard
                label="RESOLVED"
                value={report.resolved_recent_count == null ? "—" : String(report.resolved_recent_count)}
                icon={<CheckCircle2 size={16} className="text-green-400" />}
                tone="text-green-400"
                note="Within retrieved recent reports"
              />
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-[1.6fr_0.9fr] gap-6 mb-6">
              <div className="glass-panel rounded-xl border border-gray-800/60 overflow-hidden min-h-[560px]">
                <FireMap incidents={mappedIncidents} onSelect={setSelected} />
              </div>

              <div className="glass-panel rounded-xl border border-gray-800/60 p-5">
                <div className="flex items-center gap-2 mb-4">
                  <MapPin size={16} className="text-red-400" />
                  <h2 className="text-xs font-bold tracking-[0.18em] text-gray-300">
                    INCIDENT DETAILS
                  </h2>
                </div>
                {selected ? (
                  <div className="space-y-4">
                    <div>
                      <div className="text-white font-semibold">{selected.title}</div>
                      <div className="text-xs text-gray-500 mt-1">{selected.location || "Location not supplied"}</div>
                    </div>
                    <div className="flex gap-2 flex-wrap">
                      <span className={`text-[10px] px-2 py-1 rounded border ${severityClass(selected.severity)}`}>
                        {selected.severity}
                      </span>
                      <span className="text-[10px] px-2 py-1 rounded border border-gray-700 text-gray-400">
                        {selected.status}
                      </span>
                    </div>
                    <div className="text-xs text-gray-400">
                      <div><span className="text-gray-600">Type:</span> {selected.incident_type || "Not stated"}</div>
                      <div className="mt-2"><span className="text-gray-600">Reported:</span> {formatTime(selected.reported_at)}</div>
                      {selected.affected_area && (
                        <div className="mt-2"><span className="text-gray-600">Affected area:</span> {selected.affected_area}</div>
                      )}
                    </div>
                    {selected.summary && (
                      <div className="text-xs leading-5 text-gray-500 border-t border-gray-800 pt-3">
                        {selected.summary}
                      </div>
                    )}
                    {selected.source_url && (
                      <a
                        href={selected.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs text-cyan-400 hover:text-cyan-300"
                      >
                        View SCDF source report →
                      </a>
                    )}
                  </div>
                ) : (
                  <div className="text-sm text-gray-600">
                    Select a mapped incident to inspect its source-backed details.
                  </div>
                )}
              </div>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-[1.2fr_1fr] gap-6">
              <section className="glass-panel rounded-xl border border-gray-800/60 p-5">
                <div className="flex items-center gap-2 mb-4">
                  <Flame size={16} className="text-red-400" />
                  <h2 className="text-xs font-bold tracking-[0.18em] text-gray-300">
                    RECENT / ACTIVE INCIDENTS
                  </h2>
                </div>
                {report.recent_incidents.length === 0 ? (
                  <div className="text-sm text-gray-600 py-8 text-center">
                    No current SCDF-published fire incident records were retrieved.
                  </div>
                ) : (
                  <div className="space-y-2">
                    {report.recent_incidents.map((incident) => (
                      <button
                        key={incident.id}
                        type="button"
                        onClick={() => setSelected(incident)}
                        className="w-full text-left p-3 rounded-lg border border-gray-800 hover:border-gray-700 hover:bg-gray-900/60 transition-colors"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-sm text-gray-200 font-medium">{incident.title}</div>
                            <div className="text-[11px] text-gray-500 mt-1">
                              {incident.location || "Location not supplied"} · {formatTime(incident.reported_at)}
                            </div>
                          </div>
                          <span className={`shrink-0 text-[9px] px-2 py-1 rounded border ${severityClass(incident.severity)}`}>
                            {incident.severity}
                          </span>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </section>

              <section className="glass-panel rounded-xl border border-gray-800/60 p-5">
                <div className="flex items-center gap-2 mb-4">
                  <ShieldAlert size={16} className="text-orange-400" />
                  <h2 className="text-xs font-bold tracking-[0.18em] text-gray-300">
                    REGIONAL SITUATION
                  </h2>
                </div>
                <div className="grid grid-cols-5 gap-2">
                  {REGIONS.map((region) => {
                    const count = report.regional_counts[region];
                    return (
                      <div key={region} className="rounded-lg border border-gray-800 p-3 text-center">
                        <div className="text-[9px] text-gray-500 uppercase">{region}</div>
                        <div className="text-xl font-mono font-bold text-white mt-1">
                          {count == null ? "—" : count}
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="mt-4 text-[10px] text-gray-600">
                  Regional labels are conservative source-text classifications; unclassified incidents are not forced into a region.
                </div>

                <div className="flex items-center gap-2 mt-7 mb-3">
                  <History size={15} className="text-cyan-400" />
                  <h3 className="text-xs font-bold tracking-[0.18em] text-gray-300">RECENT HISTORY</h3>
                </div>
                <div className="space-y-1 max-h-64 overflow-y-auto pr-1">
                  {report.historical_fire_counts.slice(-8).reverse().map((point) => (
                    <div key={point.year} className="flex justify-between text-xs py-2 border-b border-gray-800/60">
                      <span className="text-gray-500">{point.year}</span>
                      <span className="font-mono text-gray-200">{point.fires ?? "—"}</span>
                    </div>
                  ))}
                </div>
              </section>
            </div>

            {(report.limitations.length > 0 || report.warnings.length > 0) && (
              <section className="mt-6 glass-panel rounded-xl border border-yellow-500/20 p-5">
                <div className="text-xs font-bold tracking-[0.18em] text-yellow-400 mb-3">
                  DATA LIMITATIONS
                </div>
                <ul className="space-y-1 text-xs text-gray-500 list-disc pl-4">
                  {[...report.limitations, ...report.warnings].map((item, idx) => (
                    <li key={`${idx}-${item}`}>{item}</li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}
