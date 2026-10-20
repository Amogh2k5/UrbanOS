"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, Sun, Zap, RefreshCw, AlertTriangle, Database } from "lucide-react";
import { fetchEnergyReport } from "@/services/api";

type Report = {
  generated_at: string; status: string; summary: string; key_metrics: Record<string, unknown>;
  peak_demand: Array<{period: string; value_mw: number | null}>;
  consumption: {year: string; sector: string; energy_product: string; consumption_ktoe: number | null}[];
  solar_by_region: {year: string; region: string; residential_status: string; installations: number | null; capacity_kwac: number | null; share_percent: number | null}[];
  solar_capacity: {year: string; residential_status: string; user_type: string; capacity_mwp: number | null; capacity_mwac: number | null}[];
  sources: Array<{ dataset_id: string; name: string; coverage: string; frequency: string; unit: string; records: number; latest_period: string | null; error: string | null; status: string; url: string }>;
  limitations: string[]; forecast: {available: boolean; reason: string};
};
const fmt = (v: unknown, digits = 1) => typeof v === "number" && Number.isFinite(v) ? v.toLocaleString("en-SG", { maximumFractionDigits: digits }) : "Unavailable";
const card = "rounded-2xl border border-slate-200 bg-white p-5 shadow-sm";
const heading = "text-base font-semibold text-slate-900";
const sub = "text-sm text-slate-500";

export default function EnergyPage() {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const load = useCallback(async (refresh = false) => {
    if (refresh) setRefreshing(true);
    setError("");
    try { setReport(await fetchEnergyReport(refresh) as unknown as Report); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not load Energy report"); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);
  useEffect(() => {
    let cancelled = false;
    fetchEnergyReport().then((data) => { if (!cancelled) setReport(data as unknown as Report); })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : "Could not load Energy report"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const demand = useMemo(() => (report?.peak_demand ?? []).filter(x => x.value_mw !== null).slice(-24), [report]);
  const maxDemand = Math.max(1, ...demand.map(x => x.value_mw ?? 0));
  const solarYears = useMemo(() => {
    const map = new Map<string, number>();
    (report?.solar_capacity ?? []).forEach(x => {
      if (x.capacity_mwp !== null) map.set(x.year, (map.get(x.year) ?? 0) + x.capacity_mwp);
    });
    return [...map.entries()].sort((a,b) => a[0].localeCompare(b[0])).slice(-12);
  }, [report]);
  const maxSolar = Math.max(1, ...solarYears.map(x => x[1]));
  const metrics = report?.key_metrics ?? {};

  return <main className="mx-auto max-w-7xl space-y-6 px-4 py-6 md:px-8">
    <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
      <div>
        <div className="mb-2 flex items-center gap-2 text-sm font-medium text-amber-700"><Zap size={16} /> INFRASTRUCTURE / ENERGY</div>
        <h1 className="text-3xl font-bold tracking-tight text-slate-950">Energy Intelligence</h1>
        <p className="mt-2 max-w-3xl text-slate-600">Singapore electricity demand, energy consumption and solar indicators from historical datasets.</p>
      </div>
      <button onClick={() => void load(true)} disabled={loading || refreshing} className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"><RefreshCw size={16} className={refreshing ? "animate-spin" : ""} /> Refresh data</button>
    </header>

    {error && <section className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800"><div className="flex items-center gap-2 font-semibold"><AlertTriangle size={18} /> Energy data unavailable</div><p className="mt-1 text-sm">{error}. Check that the UrbanOS backend is running, then refresh.</p></section>}
    {loading && !report && <section className={card}><p className="animate-pulse text-slate-500">Loading energy data…</p></section>}
    {report && <>
      <section className={`rounded-2xl border p-4 ${report.status === "OK" ? "border-amber-200 bg-amber-50" : report.status === "PARTIAL" ? "border-amber-200 bg-amber-50" : "border-rose-200 bg-rose-50"}`}>
        <div className="flex items-start gap-3"><Database size={20} className="mt-0.5 shrink-0" /><div><p className="font-semibold text-slate-900">Data status: {report.status}</p><p className="mt-1 text-sm text-slate-700">{report.summary}</p><p className="mt-2 text-xs text-slate-500">Report generated {new Date(report.generated_at).toLocaleString("en-SG", { timeZone: "Asia/Singapore" })} · Historical/latest-available statistics, not live telemetry.</p></div></div>
      </section>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Metric icon={<Activity size={19} />} label="Latest peak system demand" value={metrics.latest_peak_demand_mw == null ? "Unavailable" : `${fmt(metrics.latest_peak_demand_mw)} MW`} note={String(metrics.latest_peak_demand_period ?? "No period available")} />
        <Metric icon={<Activity size={19} />} label="Historical peak demand" value={metrics.max_peak_demand_mw == null ? "Unavailable" : `${fmt(metrics.max_peak_demand_mw)} MW`} note="Maximum in verified monthly dataset" />
        <Metric icon={<Sun size={19} />} label="Solar capacity" value={metrics.latest_solar_capacity_mwp == null ? "Unavailable" : `${fmt(metrics.latest_solar_capacity_mwp, 2)} MWp`} note={`Historical year: ${metrics.latest_solar_capacity_year ?? "unavailable"}`} />
        <Metric icon={<Zap size={19} />} label="Consumption records" value={fmt(metrics.consumption_records, 0)} note="Annual sector/product records (2009–2019)" />
      </section>

    <section className="grid min-w-0 gap-5 lg:grid-cols-2">
        <div className={`${card} min-w-0 bg-amber-50/70`}>
          <div className="mb-1 flex items-center justify-between"><h2 className={heading}>Monthly peak system demand</h2><span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600">MW</span></div>
          <p className={`${sub} mb-5`}>Latest 24 available monthly observations; dataset ends July 2021.</p>
          {demand.length ? <div role="list" aria-label="Monthly peak system demand observations" className="max-h-72 space-y-2 overflow-y-auto pr-2">
            {demand.map(x => <div role="listitem" key={x.period} className="grid min-w-0 grid-cols-[minmax(6.5rem,auto)_1fr_auto] items-center gap-3 text-xs sm:text-sm" title={`${x.period}: ${fmt(x.value_mw)} MW`}><span className="whitespace-nowrap text-slate-700">{x.period}</span><div className="h-3 min-w-0 overflow-hidden rounded-full bg-white"><div className="h-full rounded-full bg-amber-500" style={{width:`${Math.max(1, (x.value_mw ?? 0) / maxDemand * 100)}%`}} /></div><span className="whitespace-nowrap text-right font-medium text-slate-800">{fmt(x.value_mw)} MW</span></div>)}
          </div> : <Empty>No peak-demand observations are currently available.</Empty>}
        </div>
        <div className={`${card} min-w-0 bg-amber-50/70`}>
          <div className="mb-1 flex items-center justify-between"><h2 className={heading}>Solar capacity history</h2><span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600">MWp</span></div>
          <p className={`${sub} mb-5`}>Historical installed grid-connected solar PV capacity by user type.</p>
          {solarYears.length ? <div className="space-y-3">{solarYears.map(([year, value]) => <div key={year} className="grid grid-cols-[44px_1fr_72px] items-center gap-3 text-sm"><span className="text-slate-500">{year}</span><div className="h-3 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-amber-400" style={{width:`${value/maxSolar*100}%`}}/></div><span className="text-right font-medium text-slate-700">{fmt(value, 1)}</span></div>)}</div> : <Empty>Solar capacity records are currently unavailable.</Empty>}
        </div>
      </section>

      <section className={`${card} bg-amber-50/50`}>
        <h2 className={heading}>Energy consumption by sector and product</h2>
        <p className={`${sub} mb-4`}>Annual total final energy consumption, 2009–2019. Values are in ktoe; this is not electricity-only consumption.</p>
        {report.consumption.length ? <div className="max-h-[380px] overflow-auto"><table className="w-full min-w-[600px] text-left text-sm"><thead className="sticky top-0 bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th className="p-3">Year</th><th className="p-3">Sector</th><th className="p-3">Energy product</th><th className="p-3 text-right">Consumption (ktoe)</th></tr></thead><tbody>{report.consumption.map((x,i)=><tr key={`${x.year}-${x.sector}-${x.energy_product}-${i}`} className="border-t border-slate-100"><td className="p-3">{x.year}</td><td className="p-3">{x.sector ?? "—"}</td><td className="p-3">{x.energy_product ?? "—"}</td><td className="p-3 text-right font-medium">{fmt(x.consumption_ktoe, 2)}</td></tr>)}</tbody></table></div> : <Empty>Consumption records are currently unavailable.</Empty>}
      </section>

      <section className="grid gap-5 lg:grid-cols-2">
        <div className={card}>
          <h2 className={heading}>Solar installations by planning region</h2><p className={`${sub} mb-4`}>Historical regional coverage through March 2021.</p>
          {report.solar_by_region.length ? <div className="max-h-80 overflow-auto"><table className="w-full text-left text-sm"><thead className="sticky top-0 bg-slate-50 text-xs text-slate-500"><tr><th className="p-3">Year</th><th className="p-3">Region</th><th className="p-3">Type</th><th className="p-3 text-right">Installations</th></tr></thead><tbody>{report.solar_by_region.slice(-80).map((x,i)=><tr key={`${x.year}-${x.region}-${x.residential_status}-${i}`} className="border-t border-slate-100"><td className="p-3">{x.year}</td><td className="p-3">{x.region}</td><td className="p-3">{x.residential_status}</td><td className="p-3 text-right">{fmt(x.installations,0)}</td></tr>)}</tbody></table></div> : <Empty>Regional solar data is currently unavailable.</Empty>}
        </div>
        <div className={card}>
          <h2 className={heading}>Demand forecast</h2><p className={`${sub} mb-4`}>Forecast availability is gated by data quality and frequency.</p>
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4"><p className="font-semibold text-amber-950">Forecast not available</p><p className="mt-1 text-sm text-amber-900">{report.forecast?.reason ?? "No verified half-hourly system demand series is available to train and evaluate a model."}</p></div>
          <p className="mt-4 text-sm text-slate-600">The public peak-demand dataset is monthly and ends in July 2021. Training a short-horizon model from it would produce unsupported predictions, so this dashboard does not invent a forecast.</p>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-slate-50 p-5"><h2 className={heading}>Data limitations</h2><ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-slate-600">{report.limitations.map((x,i)=><li key={i}>{x}</li>)}</ul></section>
    </>}
  </main>;
}

function Metric({icon,label,value,note}:{icon:React.ReactNode;label:string;value:string;note:string}) {
  return <div className="rounded-2xl border border-amber-700 bg-amber-700 p-5 shadow-sm"><div className="mb-3 flex items-center justify-between"><span className="text-sm text-white/90">{label}</span><span className="text-white">{icon}</span></div><p className="text-2xl font-bold tracking-tight text-white">{value}</p><p className="mt-2 text-xs text-white/90">{note}</p></div>;
}
function Empty({children}:{children:React.ReactNode}) { return <div className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">{children}</div>; }
