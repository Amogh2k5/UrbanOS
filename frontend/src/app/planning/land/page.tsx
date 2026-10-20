"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import dynamic from "next/dynamic";
import { AlertTriangle, Building2, Factory, Info, Layers, MapPin, RefreshCw, ShieldAlert } from "lucide-react";
import { domainCardClass } from "@/components/city/presentation";
import { GroupBars, GroupShareBar, YearBars } from "./LandCharts";
import { DATA_KIND_STYLE, GROUP_COLOR, GROUP_LABEL, SOURCE_STATUS_STYLE } from "./landConstants";
import {
  fetchLandGls,
  fetchLandIndustrial,
  fetchLandMap,
  fetchLandOverview,
  fetchLandPlanningAreas,
  fetchLandSources,
  fetchLandUse,
  type LandDataKind,
  type LandOverview,
  type LandPlanningArea,
  type LandPlanningResponse,
  type LandGlsResponse,
  type LandIndustrialResponse,
  type LandMapResponse,
  type LandSourcesResponse,
  type LandUseResponse,
} from "@/services/api";

const LandMap = dynamic(() => import("./LandMap"), {
  ssr: false,
  loading: () => (
    <div className="h-full min-h-[460px] flex items-center justify-center text-xs text-slate-600">Loading map…</div>
  ),
});

const SOLID_KIND_STYLE: Record<LandDataKind, string> = {
  live: "bg-white text-green-900 border-white/80",
  latest_available: "bg-white text-cyan-900 border-white/80",
  historical: "bg-white text-violet-900 border-white/80",
  forecast: "bg-white text-amber-900 border-white/80",
  unavailable: "bg-white text-slate-700 border-white/80",
};

function KindBadge({ kind, onSolidCard = false }: { kind: LandDataKind; onSolidCard?: boolean }) {
  const s = DATA_KIND_STYLE[kind] ?? DATA_KIND_STYLE.unavailable;
  const cls = onSolidCard ? SOLID_KIND_STYLE[kind] : s.cls;
  return (
    <span className={`text-[9px] font-bold tracking-[0.14em] px-2 py-0.5 rounded border ${cls}`}>
      {s.label}
    </span>
  );
}

function fmtNum(v?: number | null, digits = 0): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toLocaleString("en-SG", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function fmtKm2(v?: number | null, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `${v.toLocaleString("en-SG", { maximumFractionDigits: digits })} km²`;
}

function fmtTime(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-SG", {
    timeZone: "Asia/Singapore",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtMoney(v?: number | null): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  return `$${fmtNum(v)}`;
}

/**
 * Neutral by default, because most of this page is dense numeric content where
 * a colour wash would hurt readability. Pass `tint` for the headline card only.
 */
function Card({
  children,
  className = "",
  tint = false,
}: {
  children: ReactNode;
  className?: string;
  tint?: boolean;
}) {
  return (
    <div
      className={
        tint
          ? `${domainCardClass("land", "rounded-xl p-4")} ${className}`
          : `glass-panel rounded-xl border border-slate-200 p-4 ${className}`
      }
    >
      {children}
    </div>
  );
}

function Section({
  id,
  title,
  icon,
  kind,
  children,
}: {
  id: string;
  title: string;
  icon: ReactNode;
  kind?: LandDataKind;
  children: ReactNode;
}) {
  return (
    <section id={id} className="mb-8 scroll-mt-4">
      <div className="flex items-center gap-2 mb-3">
        {icon}
        <h2 className="text-sm font-bold tracking-[0.2em] text-slate-700">{title}</h2>
        {kind && <KindBadge kind={kind} />}
      </div>
      {children}
    </section>
  );
}

function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "error"; children: ReactNode }) {
  const cls =
    tone === "error"
      ? "border-red-500/25 bg-red-50 text-red-800"
      : tone === "warn"
        ? "border-yellow-500/25 bg-yellow-50 text-yellow-800/80"
        : "border-slate-200 bg-slate-50 text-slate-500";
  return (
    <div className={`rounded-lg border p-3 text-xs leading-5 flex gap-2 ${cls}`}>
      <Info size={14} className="shrink-0 mt-0.5" />
      <div>{children}</div>
    </div>
  );
}

/** Group keys come from the API as strings; fall back to the raw key. */
function groupLabel(g: string): string {
  return GROUP_LABEL[g as keyof typeof GROUP_LABEL] ?? g;
}

/** Renders "unavailable" for null, so a missing value is never shown as 0. */
function Metric({
  label,
  value,
  unit = "",
  kind,
  hint,
}: {
  label: string;
  value: number | null | undefined;
  unit?: string;
  kind?: LandDataKind;
  hint?: string;
}) {
  const has = value !== null && value !== undefined && Number.isFinite(value);
  return (
    <Card tint>
      <div className="flex items-center justify-between gap-2">
        <div className="text-[10px] font-bold tracking-[0.16em] text-white/90">{label.toUpperCase()}</div>
        {kind && <KindBadge kind={has ? kind : "unavailable"} onSolidCard />}
      </div>
      <div className={`text-2xl font-mono font-bold mt-2 ${has ? "text-white" : "text-white/90"}`}>
        {has ? `${fmtNum(value, Number.isInteger(value) ? 0 : 1)} ` : "— "}
        <span className="text-xs text-white/90 font-normal">{unit}</span>
      </div>
      <div className="text-[10px] text-white/90 mt-1">{has ? (hint ?? "") : "Not reported by the source"}</div>
    </Card>
  );
}

const ENDPOINTS = [
  ["overview", fetchLandOverview],
  ["use", fetchLandUse],
  ["planning", fetchLandPlanningAreas],
  ["gls", fetchLandGls],
  ["industrial", fetchLandIndustrial],
  ["sources", fetchLandSources],
  ["map", fetchLandMap],
] as const;

type LandResults = PromiseSettledResult<unknown>[];

/**
 * Fetch every Land endpoint. Each is settled independently so a single failure
 * degrades one section rather than blanking the page.
 */
async function fetchAllLand(refresh: boolean): Promise<LandResults> {
  return Promise.allSettled(ENDPOINTS.map(([, fn]) => fn(refresh)));
}

export default function LandPage() {
  const [overview, setOverview] = useState<LandOverview | null>(null);
  const [use, setUse] = useState<LandUseResponse | null>(null);
  const [planning, setPlanning] = useState<LandPlanningResponse | null>(null);
  const [gls, setGls] = useState<LandGlsResponse | null>(null);
  const [industrial, setIndustrial] = useState<LandIndustrialResponse | null>(null);
  const [sources, setSources] = useState<LandSourcesResponse | null>(null);
  const [map, setMap] = useState<LandMapResponse | null>(null);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selected, setSelected] = useState<LandPlanningArea | null>(null);
  const [sortKey, setSortKey] = useState<"land_use_area_sqm" | "name" | "dominant_category_pct">(
    "land_use_area_sqm",
  );
  const [regionFilter, setRegionFilter] = useState<string>("all");

  const applyResults = useCallback((results: LandResults) => {
    const [o, u, p, g, i, s, m] = results;
    if (o?.status === "fulfilled") setOverview(o.value as LandOverview);
    if (u?.status === "fulfilled") setUse(u.value as LandUseResponse);
    if (p?.status === "fulfilled") setPlanning(p.value as LandPlanningResponse);
    if (g?.status === "fulfilled") setGls(g.value as LandGlsResponse);
    if (i?.status === "fulfilled") setIndustrial(i.value as LandIndustrialResponse);
    if (s?.status === "fulfilled") setSources(s.value as LandSourcesResponse);
    if (m?.status === "fulfilled") setMap(m.value as LandMapResponse);

    const failed = results
      .map((r, idx) => ({ r, name: ENDPOINTS[idx][0] }))
      .filter(({ r }) => r.status === "rejected");
    setError(
      failed.length
        ? `${failed.length} Land endpoint(s) failed — ${failed
            .map(({ r, name }) => `${name}: ${String((r as PromiseRejectedResult).reason)}`)
            .join("; ")}`
        : null,
    );
    setLoading(false);
    setRefreshing(false);
  }, []);

  const load = useCallback(
    async (refresh: boolean) => {
      if (refresh) setRefreshing(true);
      applyResults(await fetchAllLand(refresh));
    },
    [applyResults],
  );

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      const results = await fetchAllLand(false);
      if (!cancelled) applyResults(results);
    };
    void run();
    const timer = setInterval(() => void run(), 15 * 60_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [applyResults]);

  const regions = planning?.planning.regions ?? [];
  const allAreas = useMemo(
    () => (planning?.planning.planning_areas ?? []).filter((p) => p.land_use_area_sqm !== null),
    [planning],
  );

  const visibleAreas = useMemo(() => {
    let rows = allAreas;
    if (regionFilter !== "all") rows = rows.filter((r) => r.region === regionFilter);
    const sorted = [...rows];
    if (sortKey === "name") sorted.sort((a, b) => a.name.localeCompare(b.name));
    else sorted.sort((a, b) => (b[sortKey] ?? 0) - (a[sortKey] ?? 0));
    return sorted;
  }, [allAreas, regionFilter, sortKey]);

  const status = overview?.source_status ?? use?.source_status ?? "unavailable";
  const degradedComponentCount = sources?.sources.filter((item) => item.status !== "ok").length;
  const statusStyle = SOURCE_STATUS_STYLE[status];

  if (loading) {
    return (
      <div className="p-6 space-y-4">
        <div className="animate-pulse bg-slate-200 h-8 w-64 rounded" />
        <div className="grid gap-4 md:grid-cols-4">
          {[1, 2, 3, 4].map((k) => (
            <div key={k} className="animate-pulse bg-slate-200 h-24 rounded-lg" />
          ))}
        </div>
        <div className="animate-pulse bg-slate-200 h-72 rounded-lg" />
      </div>
    );
  }

  const lu = use?.land_use;
  const pl = planning?.planning;
  const g = gls?.gls;
  const cad = gls?.cadastral;
  const ind = industrial?.industrial;
  const nothingLoaded = !overview && !use && !planning && !gls && !industrial;

  return (
    <div className="flex flex-col h-full overflow-y-auto bg-[var(--color-background)] text-[var(--color-foreground)]">
      <div className="w-full max-w-[1920px] mx-auto px-4 md:px-6 lg:px-8 pb-10 pt-5">
        {/* ------------------------------------------------------- header */}
        <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4 mb-5">
          <div>
            <div className="text-[10px] uppercase tracking-[0.25em] text-cyan-700 font-bold">
              Planning domain
            </div>
            <h1 className="text-2xl md:text-3xl font-heading font-bold text-slate-900 mt-1">
              Singapore land-use, planning &amp; development intelligence
            </h1>
            <p className="text-sm text-slate-500 mt-1">
              Master Plan 2025 zoning, planning areas, cadastral parcels and Government Land Sales.
            </p>
          </div>
          <div className="flex items-center gap-3 self-start lg:self-auto">
            <nav className="hidden md:flex gap-3 text-xs text-slate-500">
              <a href="#use" className="text-slate-600 hover:text-slate-900">Land use</a>
              <a href="#planning" className="text-slate-600 hover:text-slate-900">Planning</a>
              <a href="#gls" className="text-slate-600 hover:text-slate-900">GLS</a>
              <a href="#industrial" className="text-slate-600 hover:text-slate-900">Industrial</a>
              <a href="#map" className="text-slate-600 hover:text-slate-900">Map</a>
            </nav>
            <button
              type="button"
              onClick={() => void load(true)}
              disabled={refreshing}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-50"
            >
              <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} /> Refresh
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-5 glass-panel p-4 rounded-xl border border-red-500/30 bg-red-50 text-red-800 text-sm flex gap-3">
            <ShieldAlert size={18} className="shrink-0" />
            <div>
              <div className="font-semibold">Some Land data could not be loaded</div>
              <div className="text-xs text-red-800/70 mt-1 break-words">{error}</div>
            </div>
          </div>
        )}

        {nothingLoaded && (
          <Card>
            <div className="text-sm text-slate-500">
              Land data is temporarily unavailable. The data services could not be reached and no cached copy
              is available, so nothing is shown rather than reporting zeros.
            </div>
          </Card>
        )}

        {/* --------------------------------------------------- status bar */}
        {!nothingLoaded && (
          <>
            <div className="mb-5 glass-panel p-3 rounded-xl border border-slate-200 text-xs text-slate-500 flex flex-wrap items-center gap-x-5 gap-y-2">
              <span className={`px-2 py-0.5 rounded border text-[10px] font-bold tracking-[0.14em] ${statusStyle.cls}`}>
                {statusStyle.label}
              </span>
              <span>Generated {fmtTime(overview?.generated_at)}</span>
              <span>
                Confidence: <strong className="text-slate-700">{overview?.confidence ?? "—"}</strong>
              </span>
              <span className="text-slate-600">ML: not used</span>
            </div>

            {status !== "available" && (
              <div className="mb-5">
                <Notice tone={status === "partial" ? "warn" : "error"}>
                  {status === "partial" ? (
                    <>
                      <strong>Partial data.</strong> {degradedComponentCount != null ? `${degradedComponentCount} data component(s) are unavailable or stale. ` : "Some data components could not be retrieved. "}Missing
                      datasets are left blank throughout this page — they are never shown as a zero value.
                    </>
                  ) : (
                    <>
                      <strong>Land data is temporarily unavailable.</strong> None of the configured datasets could be
                      retrieved and no cached copy is available.
                    </>
                  )}
                </Notice>
              </div>
            )}

            {/* ------------------------------------------------------ KPI */}
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5 mb-8">
              <Metric
                label="Land-use area"
                value={lu?.total_area_km2 ?? null}
                unit="km²"
                kind="latest_available"
                hint={`${fmtNum(lu?.total_zones ?? null)} Master Plan zones`}
              />
              <Metric
                label="Land-use categories"
                value={lu?.distinct_categories ?? null}
                kind="latest_available"
                hint="Planning designations"
              />
              <Metric
                label="Planning areas"
                value={pl?.planning_area_count ?? overview?.headline.planning_area_count ?? null}
                kind="latest_available"
                hint={`${fmtNum(pl?.region_count ?? overview?.headline.region_count ?? null)} regions`}
              />
              <Metric
                label="Cadastral parcels"
                value={cad?.parcel_count ?? overview?.headline.cadastral_parcel_count ?? null}
                kind="latest_available"
                hint="surveyed land lots"
              />
              <Metric
                label="GLS sites (awarded)"
                value={g?.site_count ?? overview?.headline.gls_site_count ?? null}
                kind="historical"
                hint={g?.award_year_min ? `${g.award_year_min}–${g.award_year_max}` : "recorded awards"}
              />
            </div>

            {/* ------------------------------------------------- land use */}
            <Section
              id="use"
              title="LAND-USE DISTRIBUTION"
              icon={<Layers size={16} className="text-cyan-700" />}
              kind={lu?.data_kind}
            >
              {!lu || lu.data_kind === "unavailable" ? (
                <Card>
                  <div className="text-sm text-slate-500">
                    Master Plan land-use layer unavailable. No zoning figures can be shown.
                  </div>
                </Card>
              ) : (
                <>
                  <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
                    <Card>
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="text-xs font-bold tracking-[0.18em] text-slate-600">AREA BY GROUP</h3>
                        <KindBadge kind={lu.data_kind} />
                      </div>
                      <GroupBars byGroup={lu.by_group} />
                    </Card>
                    <Card>
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="text-xs font-bold tracking-[0.18em] text-slate-600">COMPOSITION</h3>
                        <span className="text-[10px] text-slate-600">{lu.source_layer}</span>
                      </div>
                      <GroupShareBar byGroup={lu.by_group} />
                    </Card>
                  </div>

                  <Card className="mt-4">
                    <div className="text-xs font-bold tracking-[0.18em] text-slate-600 mb-2">
                      OFFICIAL DESIGNATIONS
                    </div>
                    <div className="overflow-x-auto max-h-[320px] overflow-y-auto">
                      <table className="w-full text-xs">
                        <thead className="sticky top-0 bg-white backdrop-blur">
                          <tr className="text-left text-[10px] tracking-[0.14em] text-slate-500">
                            <th className="py-2 pr-4">DESIGNATION</th>
                            <th className="pr-4">GROUP</th>
                            <th className="pr-4 text-right">AREA (km²)</th>
                            <th className="pr-4 text-right">SHARE</th>
                            <th className="text-right">ZONES</th>
                          </tr>
                        </thead>
                        <tbody>
                          {lu.categories.map((c) => (
                            <tr key={c.code} className="border-b border-slate-200 text-slate-600">
                              <td className="py-1.5 pr-4">{c.label}</td>
                              <td className="pr-4 text-slate-500">{groupLabel(c.group)}</td>
                              <td className="pr-4 text-right font-mono">
                                {c.area_sqm === null ? "—" : (c.area_sqm / 1e6).toFixed(2)}
                              </td>
                              <td className="pr-4 text-right font-mono">
                                {c.area_pct === null ? "—" : `${c.area_pct.toFixed(2)}%`}
                              </td>
                              <td className="text-right font-mono">{fmtNum(c.zone_count)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </Card>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                    <Card>
                      <div className="flex items-center justify-between mb-2">
                        <h3 className="text-xs font-bold tracking-[0.18em] text-slate-600">GROSS PLOT RATIO</h3>
                        <KindBadge kind={lu.gpr.data_kind} />
                      </div>
                      {lu.gpr.data_kind === "unavailable" ? (
                        <div className="text-sm text-slate-600">No numeric GPR reported.</div>
                      ) : (
                        <>
                          <div className="grid grid-cols-4 gap-3 text-center">
                            {(
                              [
                                ["p25", lu.gpr.p25],
                                ["Median", lu.gpr.median],
                                ["p75", lu.gpr.p75],
                                ["Max", lu.gpr.max],
                              ] as [string, number | null][]
                            ).map(([label, v]) => (
                              <div key={String(label)}>
                                <div className="text-[9px] tracking-[0.12em] text-slate-500">{label}</div>
                                <div className="text-lg font-mono font-bold text-slate-900">
                                  {v === null ? "—" : v.toFixed(2)}
                                </div>
                              </div>
                            ))}
                          </div>
                          <div className="text-[11px] text-slate-500 mt-3">
                            {fmtNum(lu.gpr.reported_numeric?.zone_count ?? null)} zones report a numeric GPR.
                            {Object.keys(lu.gpr.special_codes).length > 0 && (
                              <>
                                {" "}Non-numeric planning codes:{" "}
                                {Object.entries(lu.gpr.special_codes)
                                  .filter(([, n]) => (n ?? 0) > 0)
                                  .map(([code, n]) => `${code} × ${n}`)
                                  .join(", ")}
                                .
                              </>
                            )}
                          </div>
                        </>
                      )}
                      <div className="mt-3 space-y-1">
                        {lu.gpr.limitations.map((l) => (
                          <div key={l} className="text-[10px] text-slate-600 leading-4">{l}</div>
                        ))}
                      </div>
                    </Card>

                    <Card>
                      <div className="text-xs font-bold tracking-[0.18em] text-slate-600 mb-2">
                        DATA VALIDATION
                      </div>
                      <div className="grid grid-cols-2 gap-3 text-center">
                        <div>
                          <div className="text-[9px] tracking-[0.12em] text-slate-500">FEATURES INSPECTED</div>
                          <div className="text-lg font-mono font-bold text-slate-900">{fmtNum(lu.zones_inspected)}</div>
                        </div>
                        <div>
                          <div className="text-[9px] tracking-[0.12em] text-slate-500">REJECTED</div>
                          <div className="text-lg font-mono font-bold text-slate-900">{fmtNum(lu.invalid_zones)}</div>
                        </div>
                      </div>
                      <div className="mt-3 space-y-1">
                        {lu.limitations.map((l) => (
                          <div key={l} className="text-[10px] text-slate-600 leading-4">{l}</div>
                        ))}
                      </div>
                    </Card>
                  </div>
                </>
              )}
            </Section>

            {/* ------------------------------------------------ planning */}
            <Section
              id="planning"
              title="PLANNING STRUCTURE"
              icon={<MapPin size={16} className="text-cyan-700" />}
              kind={pl?.data_kind}
            >
              {!pl || pl.data_kind === "unavailable" ? (
                <Card><div className="text-sm text-slate-500">Planning-area boundaries unavailable.</div></Card>
              ) : (
                <>
                  <div className="grid gap-4 mb-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
                    {regions.map((r) => (
                      <Card key={r.name} className="!p-3">
                        <div className="text-[10px] font-bold tracking-[0.14em] text-slate-500">{r.name}</div>
                        <div className="text-lg font-mono font-bold text-slate-900 mt-1">
                          {r.area_sqm === null ? "—" : (r.area_sqm / 1e6).toFixed(1)}
                          <span className="text-[10px] text-slate-500 ml-1">km²</span>
                        </div>
                      </Card>
                    ))}
                  </div>

                  <Card>
                    <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
                      <h3 className="text-xs font-bold tracking-[0.18em] text-slate-600">LAND USE BY PLANNING AREA</h3>
                      <div className="flex items-center gap-2">
                        <select
                          value={regionFilter}
                          onChange={(e) => setRegionFilter(e.target.value)}
                          className="bg-slate-200 border border-slate-200 text-xs text-slate-700 rounded px-2 py-1"
                        >
                          <option value="all">All regions</option>
                          {regions.map((r) => (
                            <option key={r.name} value={r.name}>{r.name}</option>
                          ))}
                        </select>
                        <select
                          value={sortKey}
                          onChange={(e) => setSortKey(e.target.value as typeof sortKey)}
                          className="bg-slate-200 border border-slate-200 text-xs text-slate-700 rounded px-2 py-1"
                        >
                          <option value="land_use_area_sqm">Sort: land-use area</option>
                          <option value="dominant_category_pct">Sort: dominant share</option>
                          <option value="name">Sort: name</option>
                        </select>
                      </div>
                    </div>

                    <p className="text-[10px] text-slate-600 mb-3">{pl.method}</p>

                    <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
                      <table className="w-full text-xs">
                        <thead className="sticky top-0 bg-white backdrop-blur">
                          <tr className="text-left text-[10px] tracking-[0.12em] text-slate-500">
                            <th className="py-2 pr-3">PLANNING AREA</th>
                            <th className="pr-3">REGION</th>
                            <th className="pr-3 text-right">LAND USE (km²)</th>
                            <th className="pr-3 text-right">COVERAGE</th>
                            <th className="pr-3">DOMINANT</th>
                            <th className="text-right">ZONES</th>
                          </tr>
                        </thead>
                        <tbody>
                          {visibleAreas.map((p) => (
                            <tr
                              key={p.name}
                              onClick={() => setSelected(p)}
                              className={`border-b border-slate-200 text-slate-600 cursor-pointer hover:bg-slate-50 ${
                                selected?.name === p.name ? "bg-white" : ""
                              }`}
                            >
                              <td className="py-1.5 pr-3">{p.name}</td>
                              <td className="pr-3 text-slate-500">{p.region ?? "—"}</td>
                              <td className="pr-3 text-right font-mono">
                                {p.land_use_area_sqm === null ? "—" : (p.land_use_area_sqm / 1e6).toFixed(2)}
                              </td>
                              <td className="pr-3 text-right font-mono">
                                {p.land_use_coverage_pct === null ? "—" : `${p.land_use_coverage_pct.toFixed(1)}%`}
                              </td>
                              <td className="pr-3 text-slate-500">
                                {p.dominant_category ?? "—"}
                                {p.dominant_category_pct !== null && (
                                  <span className="text-slate-600"> {p.dominant_category_pct.toFixed(0)}%</span>
                                )}
                              </td>
                              <td className="text-right font-mono">{fmtNum(p.zone_count)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div className="text-[10px] text-slate-600 mt-2">
                      Showing {visibleAreas.length} of {allAreas.length} planning areas with attributed land-use zones.
                    </div>
                  </Card>

                  {selected && (
                    <Card className="mt-4">
                      <div className="flex items-center gap-2 mb-2">
                        <MapPin size={15} className="text-cyan-700" />
                        <h3 className="text-xs font-bold tracking-[0.18em] text-slate-600">
                          {selected.name.toUpperCase()} — LAND USE BREAKDOWN
                        </h3>
                      </div>
                      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
                        {Object.entries(selected.group_area_sqm ?? {})
                          .filter(([, v]) => typeof v === "number" && v > 0)
                          .sort((a, b) => (b[1] as number) - (a[1] as number))
                          .map(([g, v]) => (
                            <div key={g} className="flex items-center gap-2 text-xs">
                              <span
                                className="w-2.5 h-2.5 inline-block rounded-sm"
                                style={{ background: GROUP_COLOR[g as keyof typeof GROUP_COLOR] ?? "#64748b" }}
                              />
                              <span className="text-slate-500">{groupLabel(g)}</span>
                              <span className="ml-auto font-mono text-slate-900">
                                {((v as number) / 1e6).toFixed(2)} km²
                              </span>
                            </div>
                          ))}
                        {Object.keys(selected.group_area_sqm ?? {}).length === 0 && (
                          <div className="text-xs text-slate-600">No land-use zone attributed to this area.</div>
                        )}
                      </div>
                    </Card>
                  )}
                </>
              )}
              <div className="mt-3 space-y-1">
                {(pl?.limitations ?? []).map((l) => (
                  <div key={l} className="text-[11px] text-slate-600">{l}</div>
                ))}
              </div>
            </Section>

            {/* ------------------------------------------------------ GLS */}
            <Section id="gls" title="GOVERNMENT LAND SALES" icon={<Building2 size={16} className="text-cyan-700" />} kind={g?.data_kind}>
              {!g || g.data_kind === "unavailable" ? (
                <Card><div className="text-sm text-slate-500">GLS site records unavailable.</div></Card>
              ) : (
                <>
                  <div className="mb-4">
                    <Notice tone="warn">{g.current_program_note}</Notice>
                  </div>
                  <div className="grid gap-4 md:grid-cols-4 mb-4">
                    <Metric label="Sites recorded" value={g.site_count} kind="historical" />
                    <Metric label="Total site area" value={g.total_site_area_sqm} unit="m²" kind="historical" />
                    <Metric label="Award years" value={g.award_year_max ? g.award_year_max : null} kind="historical" hint={g.award_year_min ? `from ${g.award_year_min}` : ""} />
                    <Metric label="Housing units" value={g.total_housing_units} kind="historical" hint="summed across sites" />
                  </div>

                  <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                    <Card>
                      <h3 className="text-xs font-bold tracking-[0.18em] text-slate-600 mb-2">SITES AWARDED PER YEAR</h3>
                      <YearBars byYear={g.by_year} />
                    </Card>
                    <Card>
                      <h3 className="text-xs font-bold tracking-[0.18em] text-slate-600 mb-2">BY DEVELOPMENT CODE</h3>
                      <div className="overflow-y-auto max-h-[190px] space-y-1 pr-1">
                        {Object.entries(g.by_development_code)
                          .filter(([, n]) => (n ?? 0) > 0)
                          .sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0))
                          .map(([code, n]) => (
                            <div key={code} className="flex items-center justify-between text-xs gap-3">
                              <span className="text-slate-500 truncate">{code}</span>
                              <span className="font-mono text-slate-900">{fmtNum(n)}</span>
                            </div>
                          ))}
                      </div>
                    </Card>
                  </div>

                  <Card className="mt-4">
                    <h3 className="text-xs font-bold tracking-[0.18em] text-slate-600 mb-2">
                      MOST RECENTLY AWARDED SITES
                    </h3>
                    <div className="overflow-x-auto max-h-[360px] overflow-y-auto">
                      <table className="w-full text-xs">
                        <thead className="sticky top-0 bg-white backdrop-blur">
                          <tr className="text-left text-[10px] tracking-[0.12em] text-slate-500">
                            <th className="py-2 pr-3">AWARDED</th>
                            <th className="pr-3">LOCATION</th>
                            <th className="pr-3">USE</th>
                            <th className="pr-3">PLANNING AREA</th>
                            <th className="pr-3 text-right">AREA (m²)</th>
                            <th className="pr-3 text-right">GPR</th>
                            <th className="pr-3 text-right">UNITS</th>
                            <th className="text-right">PRICE</th>
                          </tr>
                        </thead>
                        <tbody>
                          {g.latest_sites.map((s, i) => (
                            <tr key={`${s.location}-${i}`} className="border-b border-slate-200 text-slate-600">
                              <td className="py-1.5 pr-3 font-mono">{s.award_year ?? "—"}</td>
                              <td className="pr-3">{s.location ?? "—"}</td>
                              <td className="pr-3 text-slate-500">{s.development_code ?? "—"}</td>
                              <td className="pr-3 text-slate-500">{s.planning_area ?? "—"}</td>
                              <td className="pr-3 text-right font-mono">{fmtNum(s.site_area_sqm)}</td>
                              <td className="pr-3 text-right font-mono">{s.gross_plot_ratio ?? "—"}</td>
                              <td className="pr-3 text-right font-mono">{fmtNum(s.housing_units)}</td>
                              <td className="text-right font-mono">{fmtMoney(s.successful_price)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div className="text-[10px] text-slate-600 mt-2">
                      {g.scope} Showing the {g.latest_sites.length} most recent awards in the source.
                    </div>
                  </Card>

                  {cad && (
                    <Card className="mt-4">
                      <div className="flex items-center justify-between mb-2">
                        <h3 className="text-xs font-bold tracking-[0.18em] text-slate-600">CADASTRAL PARCELS</h3>
                        <KindBadge kind={cad.data_kind} />
                      </div>
                      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
                        <div>
                          <div className="text-[9px] tracking-[0.12em] text-slate-500">PARCELS</div>
                          <div className="text-lg font-mono font-bold text-slate-900">{fmtNum(cad.parcel_count)}</div>
                        </div>
                        <div>
                          <div className="text-[9px] tracking-[0.12em] text-slate-500">TOTAL AREA</div>
                          <div className="text-lg font-mono font-bold text-slate-900">
                            {cad.total_area_sqm === null ? "—" : (cad.total_area_sqm / 1e6).toFixed(1)}
                            <span className="text-[10px] text-slate-500 ml-1">km²</span>
                          </div>
                        </div>
                        <div>
                          <div className="text-[9px] tracking-[0.12em] text-slate-500">MEDIAN PARCEL</div>
                          <div className="text-lg font-mono font-bold text-slate-900">
                            {cad.median_area_sqm === null ? "—" : (cad.median_area_sqm / 1e3).toFixed(1)}
                            <span className="text-[10px] text-slate-500 ml-1">k m²</span>
                          </div>
                        </div>
                        <div>
                          <div className="text-[9px] tracking-[0.12em] text-slate-500">REJECTED / DUPES</div>
                          <div className="text-lg font-mono font-bold text-slate-900">
                            {fmtNum(cad.invalid_features)} / {fmtNum(cad.duplicate_lot_keys)}
                          </div>
                        </div>
                      </div>
                      <div className="text-[10px] text-slate-600 mt-3">{cad.ownership_note}</div>
                      <div className="mt-2 space-y-1">
                        {cad.limitations.map((l) => (
                          <div key={l} className="text-[10px] text-slate-600 leading-4">{l}</div>
                        ))}
                      </div>
                    </Card>
                  )}
                </>
              )}
            </Section>

            {/* ------------------------------------------------ industrial */}
            <Section id="industrial" title="INDUSTRIAL LAND" icon={<Factory size={16} className="text-cyan-700" />} kind={ind?.data_kind}>
              {!ind || ind.data_kind === "unavailable" ? (
                <Card><div className="text-sm text-slate-500">Industrial land data unavailable.</div></Card>
              ) : (
                <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                  <div className="grid gap-4">
                    <Metric
                      label="Industrial land (zoned)"
                      value={ind.industrial_land_use_area_sqm === null ? null : ind.industrial_land_use_area_sqm / 1e6}
                      unit="km²"
                      kind="latest_available"
                      hint="Master Plan BUSINESS 1 / BUSINESS 2"
                    />
                    <Metric
                      label="JTC estates"
                      value={ind.estate_count}
                      kind="latest_available"
                      hint={ind.total_estate_area_km2 === null ? undefined : `${ind.total_estate_area_km2} km² combined`}
                    />
                    {ind.source_data_date && (
                      <div className="text-[10px] text-slate-600">
                        JTC estate layer revision date: {ind.source_data_date}
                      </div>
                    )}
                    <div className="space-y-1">
                      {ind.limitations.map((l) => (
                        <div key={l} className="text-[10px] text-slate-600 leading-4">{l}</div>
                      ))}
                    </div>
                  </div>
                  <Card>
                    <h3 className="text-xs font-bold tracking-[0.18em] text-slate-600 mb-2">LARGEST JTC ESTATES</h3>
                    <div className="overflow-y-auto max-h-[320px] space-y-1 pr-1">
                      {ind.largest_estates.map((e, idx) => (
                        <div key={`${e.estate_name}-${idx}`} className="flex items-center justify-between text-xs gap-3">
                          <span className="text-slate-500 truncate">{e.estate_name}</span>
                          <span className="font-mono text-slate-900 shrink-0">{e.area_km2} km²</span>
                        </div>
                      ))}
                      {ind.largest_estates.length === 0 && (
                        <div className="text-xs text-slate-600">No estate geometries reported.</div>
                      )}
                    </div>
                  </Card>
                </div>
              )}
            </Section>

            {/* ------------------------------------------------------ map */}
            <Section id="map" title="LAND INTELLIGENCE MAP" icon={<MapPin size={16} className="text-cyan-700" />}>
              <div className="grid grid-cols-1 xl:grid-cols-[1.7fr_0.9fr] gap-6">
                <div className="glass-panel rounded-xl border border-slate-200 overflow-hidden min-h-[480px]">
                  <LandMap
                    layers={map?.layers ?? []}
                    planningAreas={pl?.planning_areas ?? []}
                    selected={selected}
                    onSelect={setSelected}
                    showSensors
                  />
                </div>
                <Card>
                  <h3 className="text-xs font-bold tracking-[0.18em] text-slate-600 mb-2">LAYERS</h3>
                  <div className="space-y-2 text-xs">
                    {(map?.layers ?? []).map((l) => (
                      <div key={l.id} className="flex items-center justify-between gap-2">
                        <span className="text-slate-500">{l.label}</span>
                        <span className="flex items-center gap-2">
                          <span className="font-mono text-slate-900">{l.data.features.length}</span>
                          <KindBadge kind={l.data_kind} />
                        </span>
                      </div>
                    ))}
                    {(map?.layers ?? []).length === 0 && (
                      <div className="text-slate-600">No map layers returned.</div>
                    )}
                  </div>
                  {map && Object.keys(map.layers_unavailable).length > 0 && (
                    <div className="mt-4 border-t border-slate-200 pt-3 space-y-2">
                      <div className="text-[10px] font-bold tracking-[0.14em] text-slate-500">
                        NOT SERVED AS MAP LAYERS
                      </div>
                      {Object.entries(map.layers_unavailable).map(([k, v]) => (
                        <div key={k} className="text-[10px] text-slate-600 leading-4">
                          <span className="text-slate-500">{k}:</span> {v}
                        </div>
                      ))}
                    </div>
                  )}
                  {selected && (
                    <div className="mt-4 border-t border-slate-200 pt-3">
                      <div className="text-[10px] font-bold tracking-[0.14em] text-slate-500">SELECTED AREA</div>
                      <div className="text-sm font-semibold text-slate-800 mt-1">{selected.name}</div>
                      <div className="text-xs text-slate-500 mt-1">
                        {selected.region ?? "—"} · {fmtKm2(selected.area_sqm)}
                      </div>
                      <div className="text-xs text-slate-500">
                        Dominant: {selected.dominant_category ?? "—"}
                      </div>
                    </div>
                  )}
                </Card>
              </div>
            </Section>

            {/* ---------------------------------------- land intelligence */}
            <Section id="insight" title="LAND INTELLIGENCE" icon={<Info size={16} className="text-cyan-700" />}>
              {(overview?.insights ?? []).length === 0 ? (
                <Card><div className="text-sm text-slate-500">No land insights available.</div></Card>
              ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                  {overview?.insights.map((i) => (
                    <Card key={i.question}>
                      <div className="flex items-start justify-between gap-2">
                        <div className="text-xs font-semibold text-slate-700">{i.question}</div>
                        <KindBadge kind={i.data_kind} />
                      </div>
                      <div className="text-xs text-slate-500 mt-2 leading-5">{i.answer}</div>
                    </Card>
                  ))}
                </div>
              )}

              {(overview?.alerts ?? []).length > 0 && (
                <div className="mt-4 grid gap-2">
                  {overview?.alerts.map((a) => (
                    <div
                      key={a.id}
                      className={`rounded-lg border p-3 text-xs flex gap-2 ${
                        a.severity === "HIGH"
                          ? "border-red-500/30 bg-red-50 text-red-800"
                          : a.severity === "MODERATE"
                            ? "border-yellow-500/30 bg-yellow-50 text-yellow-800"
                            : "border-slate-200 bg-slate-50 text-slate-600"
                      }`}
                    >
                      <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                      <div>
                        <span className="font-bold mr-2">{a.severity}</span>
                        {a.message}
                        {a.evidence.length > 0 && (
                          <div className="text-[10px] opacity-70 mt-0.5">{a.evidence.join(" · ")}</div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {overview && overview.limitations.length > 0 && (
                <div className="mt-4">
                  <Notice>
                    <div className="font-semibold text-slate-600 mb-1">How to read this page</div>
                    <ul className="list-disc list-inside space-y-0.5">
                      {overview.limitations.map((l) => (
                        <li key={l}>{l}</li>
                      ))}
                    </ul>
                  </Notice>
                </div>
              )}
            </Section>


          </>
        )}
      </div>
    </div>
  );
}
