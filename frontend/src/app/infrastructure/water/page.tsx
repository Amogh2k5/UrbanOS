"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Activity, AlertTriangle, Droplets, Info, MapPin, RefreshCw, ShieldAlert, Waves } from "lucide-react";
import dynamic from "next/dynamic";
import { CONDITION_COLOR } from "./waterConstants";
import { LineChart, StackedBars } from "./WaterCharts";

// The map library is large; load it on the client only, after the rest of the page is visible.
const WaterMap = dynamic(() => import("./WaterMap"), {
  ssr: false,
  loading: () => <div className="h-full min-h-[460px] flex items-center justify-center text-xs text-gray-600">Loading map…</div>,
});
import {
  fetchWaterReport,
  type WaterDataKind,
  type WaterDrainSensorStatus,
  type WaterIndicator,
  type WaterReport,
} from "@/services/api";

const KIND_STYLE: Record<WaterDataKind, { label: string; cls: string }> = {
  live: { label: "LIVE", cls: "text-green-400 bg-green-500/10 border-green-500/30" },
  latest_available: { label: "LATEST AVAILABLE", cls: "text-cyan-400 bg-cyan-500/10 border-cyan-500/30" },
  historical: { label: "HISTORICAL", cls: "text-violet-300 bg-violet-500/10 border-violet-500/30" },
  forecast: { label: "FORECAST", cls: "text-amber-300 bg-amber-500/10 border-amber-500/30" },
  unavailable: { label: "UNAVAILABLE", cls: "text-gray-400 bg-gray-500/10 border-gray-500/30" },
};

function KindBadge({ kind }: { kind: WaterDataKind }) {
  const s = KIND_STYLE[kind];
  return <span className={`text-[9px] font-bold tracking-[0.14em] px-2 py-0.5 rounded border ${s.cls}`}>{s.label}</span>;
}

function fmtTime(value?: string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-SG", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function fmtNum(v?: number | null, digits = 1) {
  return v == null ? "—" : v.toLocaleString("en-SG", { maximumFractionDigits: digits });
}

function Section({ id, title, icon, kind, children }: { id: string; title: string; icon: ReactNode; kind?: WaterDataKind; children: ReactNode }) {
  return (
    <section id={id} className="mb-8 scroll-mt-4">
      <div className="flex items-center gap-2 mb-3">
        {icon}
        <h2 className="text-sm font-bold tracking-[0.2em] text-gray-200">{title}</h2>
        {kind && <KindBadge kind={kind} />}
      </div>
      {children}
    </section>
  );
}

function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`glass-panel rounded-xl border border-gray-800/60 p-4 ${className}`}>{children}</div>;
}

function IndicatorCard({ ind, fallbackLabel }: { ind?: WaterIndicator | null; fallbackLabel: string }) {
  if (!ind || ind.value == null) {
    return (
      <Card>
        <div className="text-[10px] font-bold tracking-[0.16em] text-gray-500">{fallbackLabel.toUpperCase()}</div>
        <div className="text-2xl font-mono font-bold text-gray-600 mt-2">—</div>
        <div className="text-[10px] text-gray-600 mt-1">Not available from the source</div>
      </Card>
    );
  }
  const change = ind.change_pct;
  return (
    <Card>
      <div className="flex items-center justify-between">
        <div className="text-[10px] font-bold tracking-[0.16em] text-gray-400">{ind.label.toUpperCase()}</div>
        <KindBadge kind={ind.data_kind} />
      </div>
      <div className="text-2xl font-mono font-bold text-white mt-2">
        {fmtNum(ind.value)} <span className="text-xs text-gray-500 font-normal">{ind.unit}</span>
      </div>
      <div className="text-[10px] text-gray-500 mt-1">
        Annual, {ind.period}
        {change != null && (
          <span className={`ml-2 font-mono ${change > 0 ? "text-amber-300" : "text-cyan-300"}`}>
            {change > 0 ? "+" : ""}{change.toFixed(1)}% vs {ind.previous_period}
          </span>
        )}
      </div>
    </Card>
  );
}

function Notice({ tone = "info", children }: { tone?: "info" | "warn"; children: ReactNode }) {
  const cls = tone === "warn" ? "border-yellow-500/25 bg-yellow-950/10 text-yellow-200/80" : "border-gray-700 bg-gray-900/40 text-gray-400";
  return (
    <div className={`rounded-lg border p-3 text-xs leading-5 flex gap-2 ${cls}`}>
      <Info size={14} className="shrink-0 mt-0.5" />
      <div>{children}</div>
    </div>
  );
}

const COMPLIANCE_STYLE: Record<string, string> = {
  WITHIN_LIMIT: "text-green-400",
  EXCEEDS_LIMIT: "text-red-400",
  NO_LIMIT_PUBLISHED: "text-gray-500",
  UNKNOWN: "text-gray-500",
};

export default function WaterPage() {
  const [report, setReport] = useState<WaterReport | null>(null);
  const [selected, setSelected] = useState<WaterDrainSensorStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Manual refresh button (bypasses the server-side report cache).
  const refresh = async () => {
    setLoading(true);
    try {
      setReport(await fetchWaterReport(true));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Water data unavailable");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        const next = await fetchWaterReport(false);
        if (!cancelled) {
          setReport(next);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Water data unavailable");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void run();
    // Upstream datasets are annual/periodic; a slow refresh is enough.
    const timer = setInterval(() => void run(), 10 * 60_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const usageSeries = report?.usage.series ?? [];
  const dom = usageSeries.find((s) => s.key === "domestic");
  const non = usageSeries.find((s) => s.key === "non_domestic");
  const total = usageSeries.find((s) => s.key === "potable_total");
  const conditionOrder = ["NORMAL", "ELEVATED", "HIGH", "CRITICAL", "UNAVAILABLE"] as const;
  const stressed = useMemo(
    () => (report?.drain.sensors ?? []).filter((s) => s.condition === "ELEVATED" || s.condition === "HIGH" || s.condition === "CRITICAL"),
    [report],
  );

  return (
    <div className="flex flex-col h-full overflow-y-auto bg-[var(--color-background)] text-[var(--color-foreground)]">
      <div className="w-full max-w-[1920px] mx-auto px-4 md:px-6 lg:px-8 pb-10 pt-5">
        <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4 mb-5">
          <div>
            <div className="text-[10px] uppercase tracking-[0.25em] text-cyan-400 font-bold">Infrastructure domain</div>
            <h1 className="text-2xl md:text-3xl font-heading font-bold text-white mt-1">Water</h1>
            <p className="text-sm text-gray-500 mt-1">
              Supply context, drain infrastructure and water usage from official Singapore sources. Rainfall and flood risk live in Flood &amp; Rainfall.
            </p>
          </div>
          <div className="flex items-center gap-3 self-start lg:self-auto">
            <nav className="hidden md:flex gap-3 text-xs text-gray-400">
              <a href="#supply" className="hover:text-white">Supply</a>
              <a href="#drain" className="hover:text-white">Drain</a>
              <a href="#usage" className="hover:text-white">Usage</a>
              <a href="#sources" className="hover:text-white">Sources</a>
            </nav>
            <button type="button" onClick={() => void refresh()}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-700 text-xs text-gray-300 hover:bg-gray-800">
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} /> Refresh
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-5 glass-panel p-4 rounded-xl border border-red-500/30 bg-red-950/20 text-red-300 text-sm flex gap-3">
            <ShieldAlert size={18} className="shrink-0" />
            <div>
              <div className="font-semibold">Water data unavailable</div>
              <div className="text-xs text-red-300/70 mt-1">{error}</div>
            </div>
          </div>
        )}

        {report && (
          <>
            <div className="mb-5 glass-panel p-3 rounded-xl border border-gray-800/60 text-xs text-gray-400 flex flex-wrap items-center gap-x-5 gap-y-2">
              <span>Report generated {fmtTime(report.generated_at)}</span>
              <span>Confidence: <strong className="text-gray-200">{report.confidence}</strong></span>
              <span>Sources OK: <strong className="text-gray-200">{report.sources.filter((s) => s.status === "ok").length}/{report.sources.length}</strong></span>
              <span className="text-gray-600">ML: not used</span>
              <span className="flex items-center gap-1.5 ml-auto">
                <KindBadge kind="live" /><KindBadge kind="latest_available" /><KindBadge kind="historical" /><KindBadge kind="forecast" />
              </span>
            </div>

            {(report.errors.length > 0 || report.warnings.length > 0) && (
              <div className="mb-5">
                <Notice tone="warn">
                  {[...report.errors, ...report.warnings].map((m) => <div key={m}>{m}</div>)}
                </Notice>
              </div>
            )}

            {report.alerts.length > 0 && (
              <div className="mb-6 grid gap-2">
                {report.alerts.map((a) => (
                  <div key={a.id} className={`rounded-lg border p-3 text-xs flex gap-2 ${a.severity === "HIGH" ? "border-red-500/30 bg-red-950/20 text-red-300" : a.severity === "MODERATE" ? "border-yellow-500/30 bg-yellow-950/10 text-yellow-200" : "border-gray-700 bg-gray-900/40 text-gray-300"}`}>
                    <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                    <div>
                      <span className="font-bold mr-2">{a.severity}</span>{a.message}
                      <span className="ml-2"><KindBadge kind={a.data_kind} /></span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* ------------------------------------------------------ SUPPLY */}
            <Section id="supply" title="WATER SUPPLY" icon={<Droplets size={16} className="text-cyan-400" />} kind={report.supply.data_kind}>
              <Notice tone="warn">{report.supply.reservoir_storage_note} The figures below are annual water <em>sales</em>, not storage or live availability.</Notice>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
                {report.supply.indicators.length === 0 && <Card><div className="text-sm text-gray-600">Supply indicators unavailable.</div></Card>}
                {report.supply.indicators.map((i) => <IndicatorCard key={i.key} ind={i} fallbackLabel={i.label} />)}
              </div>
              {report.supply.newater_share_of_water_sales_pct != null && (
                <Card className="mt-4">
                  <div className="text-[10px] font-bold tracking-[0.16em] text-gray-400">NEWATER SHARE OF WATER SALES</div>
                  <div className="text-2xl font-mono font-bold text-white mt-2">{fmtNum(report.supply.newater_share_of_water_sales_pct)}%</div>
                  <div className="text-[10px] text-gray-500 mt-1">Derived from annual sales volumes — not a share of total supply or demand. {report.newater.limitations.find((l) => l.includes("industrial")) ?? ""}</div>
                </Card>
              )}
              {report.supply.limitations.map((l) => <div key={l} className="text-[11px] text-gray-600 mt-2">{l}</div>)}
            </Section>

            {/* ------------------------------------------------------- DRAIN */}
            <Section id="drain" title="DRAIN CONDITION" icon={<Waves size={16} className="text-cyan-400" />} kind={report.drain.data_kind}>
              <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-4">
                {conditionOrder.map((c) => (
                  <Card key={c} className="!p-3">
                    <div className="flex items-center gap-2 text-[10px] font-bold tracking-[0.14em] text-gray-400">
                      <span className="w-2 h-2 rounded-full" style={{ background: CONDITION_COLOR[c] }} />
                      {c === "UNAVAILABLE" ? "NO READING" : c}
                    </div>
                    <div className="text-xl font-mono font-bold text-white mt-1">{report.drain.condition_counts[c] ?? 0}</div>
                  </Card>
                ))}
              </div>
              <div className="grid grid-cols-1 xl:grid-cols-[1.6fr_0.9fr] gap-6">
                <div className="glass-panel rounded-xl border border-gray-800/60 overflow-hidden min-h-[480px]">
                  <WaterMap sensors={report.drain.sensors} readingsAvailable={report.drain.readings_available}
                    onSelect={setSelected} selectedId={selected?.sensor.id} />
                </div>
                <Card>
                  <div className="flex items-center gap-2 mb-3">
                    <MapPin size={15} className="text-cyan-400" />
                    <h3 className="text-xs font-bold tracking-[0.18em] text-gray-300">SENSOR DETAILS</h3>
                  </div>
                  {selected ? (
                    <div className="space-y-2 text-xs text-gray-400">
                      <div className="text-white font-semibold text-sm">{selected.sensor.name || selected.sensor.id}</div>
                      <div>Location: {selected.sensor.latitude.toFixed(5)}, {selected.sensor.longitude.toFixed(5)}</div>
                      <div>Condition: <strong style={{ color: CONDITION_COLOR[selected.condition] }}>{selected.condition === "UNAVAILABLE" ? "No official reading" : selected.condition}</strong></div>
                      {selected.percentage != null && <div>Level: {selected.water_level_m} m of {selected.reference_depth_m} m ({selected.percentage}%)</div>}
                      {selected.observed_at && <div>Observed: {fmtTime(selected.observed_at)} · trend {selected.trend}</div>}
                    </div>
                  ) : (
                    <div className="text-sm text-gray-600">Select a sensor on the map.</div>
                  )}
                  {stressed.length > 0 && (
                    <div className="mt-4 border-t border-gray-800 pt-3 space-y-1.5">
                      <div className="text-[10px] font-bold tracking-[0.14em] text-gray-500">ELEVATED OR WORSE</div>
                      {stressed.slice(0, 8).map((s) => (
                        <button key={s.sensor.id} type="button" onClick={() => setSelected(s)} className="w-full text-left text-xs text-gray-300 hover:text-white flex justify-between">
                          <span>{s.sensor.name || s.sensor.id}</span>
                          <span style={{ color: CONDITION_COLOR[s.condition] }}>{s.percentage}%</span>
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="mt-4 border-t border-gray-800 pt-3 text-[10px] leading-4 text-gray-600 space-y-1">
                    {Object.entries(report.drain.thresholds).map(([k, v]) => <div key={k}><strong className="text-gray-500">{k}</strong>: {v}</div>)}
                    <div>Source: {report.drain.threshold_source}</div>
                  </div>
                </Card>
              </div>
              <div className="mt-3 space-y-1">
                {report.drain.limitations.map((l) => <div key={l} className="text-[11px] text-gray-600">{l}</div>)}
                {report.drain.invalid_sensor_records > 0 && (
                  <div className="text-[11px] text-gray-600">{report.drain.invalid_sensor_records} sensor record(s) with invalid coordinates were excluded.</div>
                )}
              </div>
            </Section>

            {/* -------------------------------------------------------- USAGE */}
            <Section id="usage" title="WATER USAGE" icon={<Activity size={16} className="text-cyan-400" />} kind={report.usage.data_kind}>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                <IndicatorCard ind={report.usage.potable_total} fallbackLabel="Potable water (total)" />
                <IndicatorCard ind={report.usage.domestic} fallbackLabel="Domestic potable" />
                <IndicatorCard ind={report.usage.non_domestic} fallbackLabel="Non-domestic potable" />
              </div>
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <Card>
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-xs font-bold tracking-[0.18em] text-gray-300">DOMESTIC vs NON-DOMESTIC</h3>
                    <KindBadge kind="historical" />
                  </div>
                  {dom && non ? <StackedBars domestic={dom} nonDomestic={non} /> : <div className="text-xs text-gray-600 py-8 text-center">Unavailable.</div>}
                  {report.usage.domestic_share_pct != null && (
                    <div className="text-[11px] text-gray-500 mt-2">
                      {report.usage.latest_year}: domestic {report.usage.domestic_share_pct}% · non-domestic {report.usage.non_domestic_share_pct}%
                    </div>
                  )}
                </Card>
                <Card>
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-xs font-bold tracking-[0.18em] text-gray-300">POTABLE SALES TREND (TOTAL)</h3>
                    <KindBadge kind="historical" />
                  </div>
                  {total ? <LineChart series={[total]} colors={["#22d3ee"]} /> : <div className="text-xs text-gray-600 py-8 text-center">Unavailable.</div>}
                  {report.usage.cagr_pct_since_2015 != null && (
                    <div className="text-[11px] text-gray-500 mt-2">Compound annual growth since 2015: {report.usage.cagr_pct_since_2015}%/yr</div>
                  )}
                </Card>
                <Card>
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-xs font-bold tracking-[0.18em] text-gray-300">NEWATER SALES</h3>
                    <KindBadge kind={report.newater.data_kind} />
                  </div>
                  {report.newater.series.length > 0 ? <LineChart series={report.newater.series} colors={["#4ade80"]} /> : <div className="text-xs text-gray-600 py-8 text-center">Unavailable.</div>}
                  <div className="text-[11px] text-gray-500 mt-2">{report.newater.long_run_source_note}</div>
                  {report.newater.limitations.slice(0, 1).map((l) => <div key={l} className="text-[11px] text-gray-600 mt-1">{l}</div>)}
                </Card>
                <Card>
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-xs font-bold tracking-[0.18em] text-gray-300">USAGE FORECAST</h3>
                    <KindBadge kind={report.forecast.available ? "forecast" : "unavailable"} />
                  </div>
                  <Notice>{report.forecast.reason}</Notice>
                  <div className="text-[11px] text-gray-600 mt-2">
                    Observations: {report.forecast.observations} ({report.forecast.frequency}) · required: {report.forecast.minimum_observations_required}
                  </div>
                </Card>
              </div>
              <div className="mt-3 space-y-1">
                {report.usage.limitations.map((l) => <div key={l} className="text-[11px] text-gray-600">{l}</div>)}
              </div>
            </Section>

            {/* ------------------------------------------------------ QUALITY */}
            <Section id="quality" title="WATER QUALITY (SUPPORTING)" icon={<Droplets size={16} className="text-gray-400" />} kind={report.quality.data_kind}>
              {report.quality.parameters.length === 0 ? (
                <Card><div className="text-sm text-gray-600">Drinking-water quality data unavailable.</div></Card>
              ) : (
                <Card className="overflow-x-auto">
                  <div className="text-xs text-gray-500 mb-3">{report.quality.reporting_period} · {report.quality.frequency}</div>
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-left text-[10px] tracking-[0.14em] text-gray-500 border-b border-gray-800">
                        <th className="py-2 pr-4">PARAMETER</th><th className="pr-4">AVERAGE</th><th className="pr-4">RANGE</th><th className="pr-4">PUB LIMIT</th><th>STATUS</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.quality.parameters.map((p) => (
                        <tr key={p.key} className="border-b border-gray-900 text-gray-300">
                          <td className="py-2 pr-4">{p.parameter} <span className="text-gray-600">({p.unit})</span></td>
                          <td className="pr-4 font-mono">{p.average ?? "—"}</td>
                          <td className="pr-4 font-mono">{p.range ?? "—"}</td>
                          <td className="pr-4 text-gray-500">{p.regulatory_limit ?? "—"}</td>
                          <td className={COMPLIANCE_STYLE[p.compliance]}>{p.compliance.replaceAll("_", " ").toLowerCase()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="text-[10px] text-gray-600 mt-3">{report.quality.other_parameter_count} further parameters are in the PUB dataset. {report.quality.limit_source}</div>
                </Card>
              )}
            </Section>

            {/* ------------------------------------------------------ AGENT */}
            <Section id="agent" title="WATER AGENT" icon={<Info size={16} className="text-gray-400" />}>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {report.insights.map((i) => (
                  <Card key={i.question}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="text-xs font-semibold text-gray-200">{i.question}</div>
                      <KindBadge kind={i.data_kind} />
                    </div>
                    <div className="text-xs text-gray-400 mt-2 leading-5">{i.answer}</div>
                  </Card>
                ))}
              </div>
            </Section>

            {/* ------------------------------------------------------ SOURCES */}
            <Section id="sources" title="DATA SOURCES" icon={<Info size={16} className="text-gray-400" />}>
              <Card className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-[10px] tracking-[0.14em] text-gray-500 border-b border-gray-800">
                      <th className="py-2 pr-4">SOURCE</th><th className="pr-4">COMPONENT</th><th className="pr-4">FREQUENCY</th><th className="pr-4">LATEST DATA</th><th className="pr-4">FETCHED</th><th>STATUS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.sources.map((s) => (
                      <tr key={s.key} className="border-b border-gray-900 text-gray-300 align-top">
                        <td className="py-2 pr-4">
                          <a href={s.url} target="_blank" rel="noreferrer" className="text-cyan-400 hover:text-cyan-300">{s.name}</a>
                          <div className="text-[10px] text-gray-600">{s.organization} · {s.identifier}</div>
                        </td>
                        <td className="pr-4">{s.component}</td>
                        <td className="pr-4 text-gray-500">{s.update_frequency}</td>
                        <td className="pr-4 font-mono">{s.latest_data_period ?? "—"}</td>
                        <td className="pr-4 text-gray-500">{fmtTime(s.last_fetched_at)}</td>
                        <td className={s.status === "ok" ? "text-green-400" : s.status === "stale_cache" ? "text-yellow-400" : "text-red-400"}>
                          {s.status.replace("_", " ")}{s.error ? <div className="text-[10px] text-gray-600 max-w-[260px]">{s.error}</div> : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
              <div className="mt-3 space-y-1">{report.limitations.map((l) => <div key={l} className="text-[11px] text-gray-600">{l}</div>)}</div>
            </Section>
          </>
        )}

        {!report && !error && <div className="text-sm text-gray-600 py-16 text-center">Loading water data…</div>}
      </div>
    </div>
  );
}
