"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { AlertTriangle, BarChart3, Brain, Info, MapPin, Recycle, RefreshCw, ShieldAlert, Trash2, Truck, Utensils } from "lucide-react";
import { CategoryBars, LineChart, RecycledDisposedBars, fmt, fmtMt } from "./WasteCharts";
import { KIND_COLOR } from "./WasteMapColors";
import { formatSingaporeDateTime } from "@/services/time";
import { domainCardClass } from "@/components/city/presentation";
import {
  fetchWasteMap,
  fetchWasteReport,
  type WasteDataKind,
  type WasteFacilityKind,
  type WasteIndicator,
  type WasteMapCollection,
  type WasteMapFeature,
  type WasteReport,
} from "@/services/api";

// maplibre touches `window`; load the map client-side only.
const WasteMap = dynamic(() => import("./WasteMap"), {
  ssr: false,
  loading: () => <div className="h-full min-h-[420px] flex items-center justify-center text-xs text-slate-600">Loading map…</div>,
});

const KIND_STYLE: Record<WasteDataKind, { label: string; cls: string }> = {
  live: { label: "LIVE", cls: "text-green-700 bg-green-500/10 border-green-500/30" },
  latest_available: { label: "LATEST AVAILABLE", cls: "text-cyan-700 bg-cyan-500/10 border-cyan-500/30" },
  historical: { label: "HISTORICAL", cls: "text-violet-700 bg-violet-500/10 border-violet-500/30" },
  reference: { label: "REFERENCE", cls: "text-sky-700 bg-sky-500/10 border-sky-500/30" },
  forecast: { label: "FORECAST", cls: "text-amber-700 bg-amber-500/10 border-amber-500/30" },
  unavailable: { label: "UNAVAILABLE", cls: "text-gray-700 bg-gray-500/10 border-gray-500/30" },
};

function KindBadge({ kind }: { kind: WasteDataKind }) {
  const s = KIND_STYLE[kind];
  return <span className={`text-[9px] font-bold tracking-[0.14em] px-2 py-0.5 rounded border ${s.cls}`}>{s.label}</span>;
}

function fmtTime(value?: string | null) {
  if (!value) return "—";
  const formatted = formatSingaporeDateTime(value);
  return formatted === "—" ? "—" : `${formatted} SGT`;
}

function Section({ id, title, icon, kind, children }: { id: string; title: string; icon: ReactNode; kind?: WasteDataKind; children: ReactNode }) {
  return (
    <section id={id} className="mb-8 scroll-mt-4">
      <div className="flex items-center gap-2 mb-3">
        {icon}
        <h2 className="text-sm font-bold tracking-[0.2em] text-slate-800">{title}</h2>
        {kind && <KindBadge kind={kind} />}
      </div>
      {children}
    </section>
  );
}

function Panel({ title, children, className = "" }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <div className={`card-panel p-4 rounded-xl ${className}`}>
      {title && <div className="text-[10px] uppercase tracking-[0.18em] text-slate-600 mb-2">{title}</div>}
      {children}
    </div>
  );
}

function Notice({ tone, children }: { tone: "warn" | "info"; children: ReactNode }) {
  const cls = tone === "warn" ? "border-amber-300 bg-amber-50 text-amber-900" : "border-slate-200 bg-slate-50 text-slate-700";
  return (
    <div className={`rounded-lg border p-3 text-xs flex gap-2 ${cls}`}>
      {tone === "warn" ? <AlertTriangle size={14} className="shrink-0 mt-0.5" /> : <Info size={14} className="shrink-0 mt-0.5" />}
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function Unavailable({ children }: { children: ReactNode }) {
  return <div className="text-xs text-slate-600 py-8 text-center">{children}</div>;
}

function KpiCard({ k }: { k: WasteIndicator }) {
  const isRate = k.unit === "%";
  const value = isRate ? (k.value == null ? "—" : `${fmt(k.value, 1)}%`) : fmtMt(k.value);
  const change =
    k.change_abs == null
      ? null
      : isRate
        ? `${k.change_abs > 0 ? "+" : ""}${fmt(k.change_abs, 1)} pp`
        : k.change_pct == null
          ? null
          : `${k.change_pct > 0 ? "+" : ""}${fmt(k.change_pct, 1)}%`;
  return (
    <div className={domainCardClass("waste", "p-4 rounded-xl")} title={k.note ?? undefined}>
      <div className="text-[10px] uppercase tracking-[0.16em] text-white/90 leading-snug min-h-[26px]">{k.label}</div>
      <div className="mt-1 flex items-baseline gap-1.5">
        <span className="text-2xl font-heading font-bold text-white">{value}</span>
        {!isRate && k.value != null && <span className="text-[10px] text-white/90">million tonnes</span>}
      </div>
      <div className="mt-1 text-[11px] text-white/90 flex items-center gap-2">
        <span>{k.period ?? "—"}</span>
        {change && k.previous_period && (
          <span className="text-white/90">{change} vs {k.previous_period}</span>
        )}
        {k.published_value != null && isRate && <span className="text-white/90">Published value: {fmt(k.published_value, 0)}%</span>}
      </div>
    </div>
  );
}

function Skeleton() {
  return (
    <div aria-busy="true" aria-label="Loading waste data" className="animate-pulse space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-24 rounded-xl bg-slate-100" />)}
      </div>
      <div className="grid lg:grid-cols-2 gap-4"><div className="h-60 rounded-xl bg-slate-100" /><div className="h-60 rounded-xl bg-slate-100" /></div>
      <div className="h-72 rounded-xl bg-slate-100" />
    </div>
  );
}

const KIND_ORDER: WasteFacilityKind[] = ["recycling_bins", "ewaste", "lighting_waste", "disposal_sites"];

export default function WastePage() {
  const [report, setReport] = useState<WasteReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mapData, setMapData] = useState<WasteMapCollection | null>(null);
  const [mapState, setMapState] = useState<"idle" | "loading" | "error" | "ready">("idle");
  const [mapError, setMapError] = useState<string | null>(null);
  const [visible, setVisible] = useState<WasteFacilityKind[]>(KIND_ORDER);
  const [selected, setSelected] = useState<WasteMapFeature | null>(null);

  // total_locations the map was last loaded for: layers arrive one by one, so reload the map when the count changes.
  const mapCount = useRef<number | null>(null);

  const loadMap = useCallback(async () => {
    setMapState((s) => (s === "ready" ? s : "loading"));
    try {
      setMapData(await fetchWasteMap());
      setMapState("ready");
      setMapError(null);
    } catch (err) {
      setMapState("error");
      setMapError(err instanceof Error ? err.message : "Map data unavailable");
    }
  }, []);

  // Manual refresh button (bypasses the server-side report cache).
  const refresh = async () => {
    setLoading(true);
    try {
      const next = await fetchWasteReport(true);
      setReport(next);
      setError(null);
      if (next.infrastructure.map_available) {
        mapCount.current = next.infrastructure.total_locations;
        void loadMap();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Waste data unavailable");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const run = async () => {
      let wait = 10 * 60_000; // upstream data is annual / static: a slow refresh is enough
      try {
        const next = await fetchWasteReport(false);
        if (cancelled) return;
        setReport(next);
        setError(null);
        // The map is a separate, larger request: only made once the report says there is something to show.
        if (next.infrastructure.map_available && mapCount.current !== next.infrastructure.total_locations) {
          mapCount.current = next.infrastructure.total_locations;
          void loadMap();
        }
        // Location layers still downloading on the server (rate-limited): check back soon.
        if (next.sources.some((src) => src.status === "loading")) wait = 15_000;
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Waste data unavailable");
        wait = 60_000;
      } finally {
        if (!cancelled) {
          setLoading(false);
          timer = setTimeout(() => void run(), wait);
        }
      }
    };
    void run();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [loadMap]);

  const mapAvailable = report?.infrastructure.map_available ?? false;
  const layersLoading = report?.infrastructure.kinds.some((k) => k.status === "loading") ?? false;

  const g = report?.generation;
  const hasStats = !!report && report.kpis.length > 0;
  const toggleKind = (k: WasteFacilityKind) => setVisible((v) => (v.includes(k) ? v.filter((x) => x !== k) : [...v, k]));

  return (
    <div className="flex flex-col h-full overflow-y-auto bg-[var(--color-background)] text-[var(--color-foreground)]">
      <div className="w-full max-w-[1920px] mx-auto px-4 md:px-6 lg:px-8 pb-10 pt-5">
        {/* Header */}
        <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4 mb-5">
          <div>
            <div className="text-[10px] uppercase tracking-[0.25em] text-primary font-bold">Infrastructure domain</div>
            <h1 className="text-2xl md:text-3xl font-heading font-bold text-slate-900 mt-1">Waste Management</h1>
            <p className="text-sm text-slate-600 mt-1">
              Waste generation, recycling, disposal, food waste and recycling infrastructure. Annual statistics — not live.
            </p>
          </div>
          <div className="flex items-center gap-3 self-start lg:self-auto">
            <nav className="hidden md:flex gap-3 text-xs text-slate-600">
              <a href="#generation" className="hover:text-slate-900">Generation</a>
              <a href="#categories" className="hover:text-slate-900">Categories</a>
              <a href="#food" className="hover:text-slate-900">Food &amp; services</a>
              <a href="#infrastructure" className="hover:text-slate-900">Infrastructure</a>
              <a href="#intelligence" className="hover:text-slate-900">Intelligence</a>
            </nav>
            <button type="button" onClick={() => void refresh()}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-300 text-xs text-slate-700 hover:bg-slate-100">
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} /> Refresh
            </button>
          </div>
        </div>

        {/* API error state */}
        {error && (
          <div role="alert" className="mb-5 card-panel p-4 border-rose-300 bg-rose-50 text-rose-900 text-sm flex gap-3">
            <ShieldAlert size={18} className="shrink-0" />
            <div>
              <div className="font-semibold">Waste data unavailable</div>
              <div className="text-xs text-rose-800 mt-1">{error}</div>
              {report && <div className="text-xs text-rose-800 mt-1">Showing the last successfully loaded report.</div>}
            </div>
          </div>
        )}

        {/* Loading state */}
        {loading && !report && !error && <Skeleton />}

        {/* Empty state: request failed and nothing was ever loaded */}
        {!loading && !report && error && (
          <Panel><Unavailable>No waste report could be loaded. Check that the backend is running, then press Refresh.</Unavailable></Panel>
        )}

        {report && (
          <>
            <div className="mb-5 glass-panel p-3 rounded-xl border border-slate-200 text-xs text-slate-600 flex flex-wrap items-center gap-x-5 gap-y-2">
              <span>Report generated {fmtTime(report.generated_at)}</span>
              <span>Statistics year: <strong className="text-slate-800">{g?.latest_year ?? "—"}</strong></span>
              <span>Confidence: <strong className="text-slate-800">{report.confidence}</strong></span>
              <span className="text-slate-600">ML: not used (annual data)</span>
              <span className="flex items-center gap-1.5 ml-auto">
                <KindBadge kind="latest_available" /><KindBadge kind="historical" /><KindBadge kind="reference" />
              </span>
            </div>

            {/* Unavailable / partial-data states */}
            {report.status === "UNAVAILABLE" && (
              <div className="mb-5">
                <Notice tone="warn">
                  <div className="font-semibold">Waste data is currently unavailable.</div>
                  <div>No figures are shown rather than estimated ones. Press Refresh to retry.</div>
                </Notice>
              </div>
            )}
            {(report.errors.length > 0 || report.warnings.length > 0) && (
              <div className="mb-5">
                <Notice tone="warn">
                  {report.status === "PARTIAL" && <div className="font-semibold">Partial data: some sections are unavailable.</div>}
                  {[...report.errors, ...report.warnings].map((m) => <div key={m}>{m}</div>)}
                </Notice>
              </div>
            )}

            {report.alerts.length > 0 && (
              <div className="mb-6 grid gap-2">
                {report.alerts.map((a) => (
                  <div key={a.id} className={`rounded-lg border p-3 text-xs flex gap-2 ${a.severity === "MODERATE" ? "border-amber-300 bg-amber-50 text-amber-900" : "border-slate-300 bg-slate-50 text-slate-700"}`}>
                    <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                    <div>
                      <div className="font-semibold">{a.message}</div>
                      {a.evidence.length > 0 && <div className="text-[11px] opacity-70 mt-0.5">{a.evidence.join(" · ")}</div>}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Empty state: report loaded but no statistics */}
            {!hasStats && report.status !== "UNAVAILABLE" && (
              <Panel><Unavailable>The statistics table returned no usable rows.</Unavailable></Panel>
            )}

            {hasStats && g && (
              <>
                {/* KPI strip */}
                <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 mb-8">
                  {report.kpis.map((k) => <KpiCard key={k.key} k={k} />)}
                </div>

                {/* Generation + recycling rate */}
                <Section id="generation" title="WASTE GENERATION & RECYCLING RATE" icon={<BarChart3 size={16} className="text-primary" />} kind={g.data_kind}>
                  <div className="grid lg:grid-cols-2 gap-4">
                    <Panel title="Total waste generated — million tonnes">
                      {g.generated ? (
                        <>
                          <LineChart lines={[{ series: g.generated, color: "#22d3ee" }]} divisor={1e6} unitLabel="Mt" digits={1} label="Total waste generated per year" />
                          {g.peak_generated_year && (
                            <div className="text-[11px] text-slate-600 mt-2">
                              Peak {fmtMt(g.peak_generated_tonnes)} Mt in {g.peak_generated_year}
                              {g.generated_change_since_peak_pct != null && ` · ${g.generated_change_since_peak_pct > 0 ? "+" : ""}${fmt(g.generated_change_since_peak_pct, 1)}% since`}
                            </div>
                          )}
                        </>
                      ) : <Unavailable>Generation series unavailable.</Unavailable>}
                    </Panel>
                    <Panel title="Overall recycling rate — %">
                      {g.recycling_rate_computed ? (
                        <>
                          <LineChart
                            lines={[
                              { series: g.recycling_rate_computed, color: "#4ade80" },
                              ...(g.recycling_rate_excl_cd ? [{ series: g.recycling_rate_excl_cd, color: "#facc15", dashed: true }] : []),
                            ]}
                            unitLabel="%" yMin={0} yMax={100} label="Overall recycling rate per year"
                          />
                          {g.peak_recycling_rate_year && (
                            <div className="text-[11px] text-slate-600 mt-2">Published peak {fmt(g.peak_recycling_rate_pct, 0)}% in {g.peak_recycling_rate_year}. Rates are computed from tonnes and rounded to a whole percentage point.</div>
                          )}
                        </>
                      ) : <Unavailable>Recycling-rate series unavailable.</Unavailable>}
                    </Panel>
                  </div>
                </Section>

                {/* Waste by category */}
                <Section id="categories" title={`WASTE BY TYPE (${report.categories.latest_year ?? "—"})`} icon={<Trash2 size={16} className="text-primary" />} kind={report.categories.data_kind}>
                  <Panel>
                    <CategoryBars rows={report.categories.rows} />
                    {report.categories.limitations.length > 0 && (
                      <div className="mt-3 text-[11px] text-slate-600 space-y-1">{report.categories.limitations.map((l) => <div key={l}>{l}</div>)}</div>
                    )}
                  </Panel>
                </Section>

                {/* Generated vs recycled vs disposed */}
                <Section id="disposal" title="GENERATED VS RECYCLED VS DISPOSED" icon={<Recycle size={16} className="text-primary" />} kind={g.data_kind}>
                  <Panel>
                    {g.generated && g.recycled && g.disposed
                      ? <RecycledDisposedBars generated={g.generated} recycled={g.recycled} disposed={g.disposed} />
                      : <Unavailable>Recycled / disposed series unavailable.</Unavailable>}
                    {g.limitations.length > 0 && <div className="mt-3 text-[11px] text-slate-600 space-y-1">{g.limitations.map((l) => <div key={l}>{l}</div>)}</div>}
                  </Panel>
                </Section>

                {/* Food waste + services */}
                <div id="food" className="grid xl:grid-cols-2 gap-4 mb-8 scroll-mt-4">
                  <section>
                    <div className="flex items-center gap-2 mb-3">
                      <Utensils size={16} className="text-primary" />
                      <h2 className="text-sm font-bold tracking-[0.2em] text-slate-800">FOOD WASTE</h2>
                      <KindBadge kind={report.food.data_kind} />
                    </div>
                    <Panel>
                      {report.food.generated ? (
                        <>
                          <div className="grid grid-cols-3 gap-3 mb-3 text-center">
                            <div><div className="text-lg font-heading font-bold text-slate-900">{fmtMt(report.food.generated.value)}</div><div className="text-[10px] text-slate-600">Mt generated {report.food.latest_year}</div></div>
                            <div><div className="text-lg font-heading font-bold text-slate-900">{fmt(report.food.recycling_rate?.value, 0)}%</div><div className="text-[10px] text-slate-600">recycled</div></div>
                            <div><div className="text-lg font-heading font-bold text-slate-900">{report.food.share_of_total_disposed_pct == null ? "—" : `${fmt(report.food.share_of_total_disposed_pct, 1)}%`}</div><div className="text-[10px] text-slate-600">of all waste disposed</div></div>
                          </div>
                          {report.food.series_generated && report.food.series_disposed && report.food.series_recycled && (
                            <LineChart
                              lines={[
                                { series: report.food.series_generated, color: "#22d3ee" },
                                { series: report.food.series_disposed, color: "#fb923c" },
                                { series: report.food.series_recycled, color: "#4ade80" },
                              ]}
                              divisor={1e6} unitLabel="Mt" digits={2} label="Food waste generated, disposed and recycled per year"
                            />
                          )}
                          {report.food.limitations.length > 0 && <div className="mt-3 text-[11px] text-slate-600 space-y-1">{report.food.limitations.map((l) => <div key={l}>{l}</div>)}</div>}
                        </>
                      ) : <Unavailable>Food-waste data unavailable.</Unavailable>}
                    </Panel>
                  </section>

                  <section>
                    <div className="flex items-center gap-2 mb-3">
                      <Truck size={16} className="text-primary" />
                      <h2 className="text-sm font-bold tracking-[0.2em] text-slate-800">WASTE SERVICES</h2>
                      <KindBadge kind={report.services.data_kind} />
                    </div>
                    <Panel>
                      {report.services.licensee_count != null ? (
                        <>
                          <div className="flex items-baseline gap-2 mb-3">
                            <span className="text-2xl font-heading font-bold text-slate-900">{fmt(report.services.licensee_count, 0)}</span>
                            <span className="text-xs text-slate-600">Licensed general waste collectors · {report.services.dataset_period}</span>
                          </div>
                          <div className="grid sm:grid-cols-2 gap-2">
                            {report.services.classes.map((c) => (
                              <div key={c.key} className="rounded-lg border border-slate-200 p-3">
                                <div className="flex items-baseline justify-between">
                                  <span className="text-xs font-semibold text-slate-800">{c.label}</span>
                                  <span className="text-lg font-heading font-bold text-slate-900">{fmt(c.licensees, 0)}</span>
                                </div>
                                <div className="text-[11px] text-slate-600 mt-1 leading-snug">{c.description}</div>
                              </div>
                            ))}
                          </div>
                          {report.services.limitations.length > 0 && <div className="mt-3 text-[11px] text-slate-600 space-y-1">{report.services.limitations.map((l) => <div key={l}>{l}</div>)}</div>}
                        </>
                      ) : <Unavailable>Licensed-collector listing unavailable.</Unavailable>}
                    </Panel>
                  </section>
                </div>
              </>
            )}

            {/* Infrastructure map (only when real coordinates were loaded) */}
            <Section id="infrastructure" title="WASTE INFRASTRUCTURE" icon={<MapPin size={16} className="text-primary" />} kind={report.infrastructure.data_kind}>
              <Notice tone="info">
                <div>Static location listings (record dates {report.infrastructure.kinds.map((k) => k.record_date_max).filter(Boolean).sort()[0]?.slice(0, 4) ?? "—"}–{report.infrastructure.kinds.map((k) => k.record_date_max).filter(Boolean).sort().slice(-1)[0]?.slice(0, 4) ?? "—"}). Locations may be out of date; no fill levels or collection activity are available.</div>
              </Notice>
              {layersLoading && (
                <div className="mt-2">
                  <Notice tone="info">
                    <div>Downloading location layers ({report.infrastructure.kinds.filter((k) => k.status === "loading").map((k) => k.label.toLowerCase()).join(", ")}). Anonymous access allows only about 5 file downloads a minute, so they appear one by one and this page updates automatically.</div>
                  </Notice>
                </div>
              )}
              <div className="grid lg:grid-cols-[1fr_320px] gap-4 mt-3">
                <Panel className="p-2">
                  <div className="h-[460px]">
                    {mapState === "ready" && mapData && mapData.features.length > 0 ? (
                      <WasteMap data={mapData} visibleKinds={visible} onSelect={setSelected} />
                    ) : mapState === "loading" || (mapState === "idle" && mapAvailable) ? (
                      <div className="h-full flex items-center justify-center text-xs text-slate-600">Loading map data…</div>
                    ) : mapState === "error" ? (
                      <div className="h-full flex flex-col items-center justify-center gap-2 text-xs text-rose-800">
                        <span>Map data unavailable{mapError ? `: ${mapError}` : ""}</span>
                        <button type="button" onClick={() => void loadMap()} className="px-3 py-1 rounded border border-slate-300 text-slate-700 hover:bg-slate-100">Retry</button>
                      </div>
                    ) : layersLoading ? (
                      <div className="h-full flex items-center justify-center text-xs text-slate-600">Location layers are still downloading…</div>
                    ) : (
                      <Unavailable>No infrastructure locations could be loaded, so no map is shown.</Unavailable>
                    )}
                  </div>
                </Panel>
                <div className="space-y-3">
                  <Panel title="Layers">
                    <div className="space-y-2">
                      {report.infrastructure.kinds.map((k) => (
                        <label key={k.key} className={`flex items-start gap-2 text-xs ${k.count === 0 ? "opacity-50" : "cursor-pointer"}`}>
                          <input type="checkbox" className="mt-0.5" disabled={k.count === 0} checked={visible.includes(k.key)} onChange={() => toggleKind(k.key)} />
                          <span className="w-2.5 h-2.5 rounded-full mt-0.5 shrink-0" style={{ background: KIND_COLOR[k.key as WasteFacilityKind] }} />
                          <span className="flex-1">
                            <span className="text-slate-800">{k.label}</span>{" "}
                            <span className="font-mono text-slate-600">{k.status === "unavailable" ? "unavailable" : k.status === "loading" ? "loading…" : fmt(k.count, 0)}</span>
                            <span className="block text-[10px] text-slate-600">
                              {k.record_date_max ? `records dated ${k.record_date_min?.slice(0, 4)}${k.record_date_min?.slice(0, 4) !== k.record_date_max.slice(0, 4) ? `–${k.record_date_max.slice(0, 4)}` : ""}` : "no record dates"}
                              {k.status === "stale_cache" && " · cached copy"}
                            </span>
                          </span>
                        </label>
                      ))}
                    </div>
                  </Panel>
                  <Panel title="Selected location">
                    {selected ? (
                      <div className="text-xs space-y-1">
                        <div className="text-slate-800 font-semibold">{String(selected.properties.name ?? "")}</div>
                        <div className="text-slate-600">{report.infrastructure.kinds.find((k) => k.key === (selected.properties.kind as string))?.label ?? ""}</div>
                        {String(selected.properties.address ?? "") && <div className="text-slate-600">{String(selected.properties.address)}</div>}
                        {String(selected.properties.description ?? "") && <div className="text-slate-600">{String(selected.properties.description)}</div>}
                        {String(selected.properties.record_date ?? "") && <div className="text-slate-600">Record dated {String(selected.properties.record_date)}</div>}
                      </div>
                    ) : <div className="text-xs text-slate-600">Click a point on the map.</div>}
                  </Panel>
                </div>
              </div>
            </Section>

            {/* Intelligence entry point */}
            <Section id="intelligence" title="WASTE INTELLIGENCE" icon={<Brain size={16} className="text-primary" />}>
              <div className="grid lg:grid-cols-2 gap-3">
                {report.insights.map((i) => (
                  <Panel key={i.question}>
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-[11px] font-semibold text-slate-700">{i.question}</div>
                      <KindBadge kind={i.data_kind} />
                    </div>
                    <p className="text-xs text-slate-600 mt-2 leading-relaxed">{i.answer}</p>
                  </Panel>
                ))}
              </div>
              <div className="mt-3 grid lg:grid-cols-2 gap-3">
                <Panel title="Not available in current datasets">
                  <ul className="text-[11px] text-slate-600 space-y-1">
                    {report.unavailable_metrics.map((m) => <li key={m.key}><span className="text-slate-700">{m.label}:</span> {m.reason}</li>)}
                  </ul>
                </Panel>
                <Panel title="Data quality checks">
                  <ul className="text-[11px] space-y-1">
                    {report.data_quality.checks.map((c) => (
                      <li key={c.key} className={c.passed ? "text-slate-600" : "text-amber-800"}>
                        {c.passed ? "✓" : "✗"} {c.description} <span className="text-slate-600">({c.checked} years)</span>
                        {!c.passed && c.failures[0] && <span className="block text-[10px] opacity-80">{c.failures[0]}</span>}
                      </li>
                    ))}
                  </ul>
                  <div className="text-[10px] text-slate-600 mt-2">Missing cells reported as &lsquo;na&rsquo;: {report.data_quality.missing_cells} · unparseable: {report.data_quality.unparseable_cells}</div>
                </Panel>
              </div>
            </Section>

            {/* Sources */}
          </>
        )}
      </div>
    </div>
  );
}
