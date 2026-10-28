"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, Home, Building2, TrendingUp, Database, AlertCircle, Zap, ArrowRight } from "lucide-react";
import { fetchHousingReport, fetchHousingForecast, type HousingSource, type HousingForecast, type HousingForecastPoint } from "@/services/api";

type TownPrice = { town: string; [key: string]: string | number | null };
type HousingBlock = { block: string; street: string; town: string | null; year_completed: number | null; total_dwelling_units: number | null };
type TownUnitCount = { town: string; units: number };
type HousingSection = { note: string | null };
type Report = {
  generated_at: string; status: string;
  kpis: Record<string, string | number | null>;
  resale_trend: { period: string; mean_of_town_flat_medians: number; observations: number }[];
  town_prices: TownPrice[];
  resale_by_flat_type: { flat_type: string; median_price_across_towns: number; towns_with_data: number }[];
  housing_stock: { hdb_property_records: number | null; total_dwelling_units_in_records: number | null; note: string | null; town_unit_counts: TownUnitCount[]; sample_blocks: HousingBlock[] };
  rental_market: HousingSection; private_residential: HousingSection & { official_release_url: string };
  supply_pipeline: HousingSection; household_context: HousingSection;
  sources: HousingSource[]; errors: string[]; warnings: string[]; limitations: string[];
  insights: { question: string; answer: string; data_kind: string }[];
};

const money = (value: unknown) => typeof value === "number" && Number.isFinite(value)
  ? new Intl.NumberFormat("en-SG", { style: "currency", currency: "SGD", maximumFractionDigits: 0 }).format(value)
  : "Unavailable";
const integer = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? new Intl.NumberFormat("en-SG").format(value) : "Unavailable";

export default function HousingPage() {
  const [report, setReport] = useState<Report | null>(null);
  const [forecast, setForecast] = useState<HousingForecast | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [error, setError] = useState("");
  const [townSearch, setTownSearch] = useState("");
  const load = useCallback(async (refresh = false) => {
    if (refresh) setRefreshing(true); else setLoading(true);
    setError("");
    try { setReport(await fetchHousingReport(refresh) as unknown as Report); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to load housing data."); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);
  const loadForecast = useCallback(async (refresh = false) => {
    setForecastLoading(true);
    try { setForecast(await fetchHousingForecast(refresh) as unknown as HousingForecast); }
    catch (e) { console.error("Failed to load forecast:", e); setForecast(null); }
    finally { setForecastLoading(false); }
  }, []);
  useEffect(() => { void load(); void loadForecast(); }, [load, loadForecast]);
  const towns = useMemo(() => (report?.town_prices || []).filter((r) => String(r.town).toLowerCase().includes(townSearch.toLowerCase())), [report, townSearch]);
  const trend = report?.resale_trend || [];
  const maxTrend = Math.max(1, ...trend.map((r) => r.mean_of_town_flat_medians || 0));
  const forecastPoints = forecast?.forecasts || [];
  const forecastMethod = forecast?.method || "—";
  const forecastPeriod = forecast?.target_period || "—";

  return <main className="min-h-screen bg-background px-4 py-6 text-slate-900 md:px-8">
    <div className="mx-auto max-w-[1600px] space-y-6">
      <header className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.22em] text-primary"><Home size={15} /> Planning / Housing</div>
          <h1 className="text-3xl font-bold text-slate-900 md:text-4xl">Singapore Housing Intelligence</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-500">A view of resale prices, housing stock and market data availability. Periodic statistics, not a property-search service.</p>
        </div>
        <button onClick={() => void load(true)} disabled={loading || refreshing} className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm hover:bg-slate-50 disabled:opacity-50">
          <RefreshCw size={15} className={refreshing ? "animate-spin" : ""} /> Refresh data
        </button>
      </header>

      {error && <div className="flex gap-3 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700"><AlertCircle size={18} className="shrink-0" /><div><b>Housing data unavailable.</b><div className="mt-1">{error}</div><button className="mt-2 underline" onClick={() => void load(true)}>Retry</button></div></div>}
      {loading && !report && <div className="rounded-xl border border-slate-200 bg-white p-8 text-slate-500">Loading housing data…</div>}

      {report && <>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className={`rounded-full px-3 py-1 ${report.status === "AVAILABLE" ? "bg-emerald-100 text-emerald-700" : report.status === "PARTIAL" ? "bg-amber-100 text-amber-700" : "bg-rose-100 text-rose-700"}`}>{report.status}</span>
          <span className="text-slate-500">Report generated {new Date(report.generated_at).toLocaleString("en-SG", { timeZone: "Asia/Singapore" })} · Singapore time</span>
          <span className="text-slate-500">Quarterly and reference datasets; not live market data</span>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <section className="solid-card metric-card bg-white border border-line p-5">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-600 mb-1">Latest resale median period</div>
            <div className="text-2xl font-bold text-slate-900">{report.kpis.latest_median_resale_period || "Unavailable"}</div>
            <div className="mt-1 text-xs text-slate-500">From the town and flat-type dataset</div>
          </section>
          <section className="solid-card metric-card bg-white border border-line p-5">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-600 mb-1">Town / flat-type observations</div>
            <div className="text-2xl font-bold text-slate-900">{integer(report.kpis.town_flat_type_median_price_rows)}</div>
            <div className="mt-1 text-xs text-slate-500">Rows with numeric prices in latest period</div>
          </section>
          <section className="solid-card metric-card bg-white border border-line p-5">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-600 mb-1">Latest resale application period</div>
            <div className="text-2xl font-bold text-slate-900">{report.kpis.latest_resale_applications_period || "Unavailable"}</div>
            <div className="mt-1 text-xs text-slate-500">Resale applications dataset</div>
          </section>
          <section className="solid-card metric-card bg-white border border-line p-5">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-600 mb-1">Public-housing property records</div>
            <div className="text-2xl font-bold text-slate-900">{integer(report.kpis.hdb_property_records)}</div>
            <div className="mt-1 text-xs text-slate-500">Reference inventory; through Dec 2025</div>
          </section>
        </div>

        {(report.errors.length > 0 || report.warnings.length > 0) && (
          <section className="card-panel rounded-xl p-5">
            <header className="card-panel-header"><h2 className="font-semibold text-slate-900">Data quality and availability</h2></header>
            <div className="mt-3 space-y-2">
              {[...report.errors, ...report.warnings].map((w, i) => <p key={i} className="text-sm text-amber-700">• {w}</p>)}
            </div>
          </section>
        )}

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          <section className="card-panel rounded-xl p-5 xl:col-span-2">
            <header className="card-panel-header"><h2 className="font-semibold text-slate-900">Resale trend</h2></header>
            <p className="mt-3 mb-4 text-xs text-slate-500">Unweighted mean of available town/flat-type medians by quarter. This is an analytical summary, not a published price index.</p>
            {trend.length ? <div className="space-y-2">
              {trend.slice(-16).map((r) => <div key={r.period} className="grid grid-cols-[68px_1fr_100px] items-center gap-3 text-xs">
                <span className="text-slate-600">{r.period}</span>
                <div className="h-5 rounded bg-slate-100"><div className="h-5 rounded bg-purple-500" style={{ width: `${Math.max(2, (r.mean_of_town_flat_medians / maxTrend) * 100)}%` }}/></div>
                <span className="text-right tabular-nums text-slate-700">{money(r.mean_of_town_flat_medians)}</span>
              </div>)}
            </div> : <p className="text-sm text-slate-500">No usable resale trend rows were returned.</p>}
          </section>
          <section className="card-panel rounded-xl p-5">
            <header className="card-panel-header"><h2 className="font-semibold text-slate-900">Market indicators</h2></header>
            <div className="mt-3 space-y-4">
              <div className="flex gap-3"><TrendingUp className="text-secondary" size={20} /><div><div className="text-sm font-medium text-slate-900">Resale market</div><p className="mt-1 text-xs text-slate-500">{report.kpis.latest_median_resale_period ? `Latest available data: ${report.kpis.latest_median_resale_period}` : "Data unavailable"}</p></div></div>
          <div className="flex gap-3"><Building2 className="text-secondary" size={20} /><div><div className="text-sm font-medium text-slate-900">Private residential</div><p className="mt-1 text-xs text-slate-500">{report.private_residential.note}</p></div></div>
              <div className="flex gap-3"><Database className="text-secondary" size={20} /><div><div className="text-sm font-medium text-slate-900">Rental / household context</div><p className="mt-1 text-xs text-slate-500">Unavailable unless a verified structured source is accessible. No stale values are substituted.</p></div></div>
            </div>
          </section>
        </div>

        {/* Resale Price Forecast Section */}
        <section className="card-panel rounded-xl p-5">
          <header className="card-panel-header">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-slate-900">Resale Price Forecast</h2>
              <span className="rounded-full px-2.5 py-1 text-xs font-medium bg-amber-100 text-amber-700">
                {forecastMethod === "persistence" ? "Last-Quarter Persistence" : 
                 forecastMethod === "seasonal_persistence" ? "Seasonal Persistence" : 
                 "Statistical Baseline"}
              </span>
            </div>
          </header>
          <p className="mt-3 mb-4 text-xs text-slate-500">
            Next-quarter median resale price forecast by town and flat type. Target period: <strong>{forecastPeriod}</strong>.
            Method: <strong>{forecastMethod === "persistence" ? "Last-quarter persistence (baseline)" : 
              forecastMethod === "seasonal_persistence" ? "Same-quarter-last-year persistence (baseline)" : 
              "Statistical baseline"}</strong>. Not an official HDB price index.
          </p>

          {forecastLoading ? (
            <div className="rounded-xl border border-slate-200 bg-white p-8 text-slate-500 text-center">
              Loading forecast…
            </div>
          ) : forecastPoints.length > 0 ? (
            <div className="space-y-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {forecastPoints.map((fp: HousingForecastPoint) => (
                  <div key={`${fp.town}|${fp.flat_type}`} className="rounded-xl border border-slate-200 bg-white p-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-semibold uppercase tracking-wider text-purple-600">{fp.town}</span>
                      <span className="text-xs text-slate-500">{fp.flat_type}</span>
                    </div>
                    <div className="text-2xl font-bold text-slate-900">{money(fp.predicted_price)}</div>
                    <div className="mt-1 text-xs text-slate-500">Forecast for {fp.forecast_period}</div>
<div className="mt-2 text-[10px] text-slate-600">
                      Method: {fp.method} � MAE: {fp.baseline_comparison?.mae ? `${integer(fp.baseline_comparison.mae)} SGD` : "-"}
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-4 p-3 rounded-lg bg-amber-50 border border-amber-200">
                <p className="text-xs text-amber-800"><strong>Limitations:</strong></p>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-xs text-amber-700">
                  {forecast?.limitations.map((lim, i) => <li key={i}>{lim}</li>)}
                </ul>
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">
              Forecast unavailable. Insufficient historical data for the selected period.
            </div>
          )}
        </section>

        <section className="card-panel rounded-xl p-5">
          <header className="card-panel-header"><h2 className="font-semibold text-slate-900">Resale median prices by town and flat type</h2></header>
          <div className="mt-4 flex flex-col justify-between gap-3 md:flex-row md:items-center">
            <p className="text-xs text-slate-500">Period: {report.kpis.latest_median_resale_period || "unavailable"} · &quot;—&quot; means no numeric value was published.</p>
            <input value={townSearch} onChange={(e) => setTownSearch(e.target.value)} placeholder="Filter town…" className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-primary" />
          </div>
          {towns.length ? <div className="mt-4 max-h-[520px] overflow-auto rounded-lg border border-slate-200">
            <table className="w-full min-w-[720px] text-left text-sm"><thead className="sticky top-0 bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="p-3">Town</th>{report.resale_by_flat_type.map((x) => <th key={x.flat_type} className="p-3">{x.flat_type}</th>)}</tr></thead>
              <tbody>{towns.map((r) => <tr key={r.town} className="border-t border-slate-100"><td className="p-3 font-medium">{r.town}</td>{report.resale_by_flat_type.map((x) => <td key={x.flat_type} className="p-3 tabular-nums">{r[x.flat_type] == null ? "—" : money(r[x.flat_type])}</td>)}</tr>)}</tbody>
            </table>
          </div> : <p className="mt-4 text-sm text-slate-500">No town/flat-type rows are available for the selected period.</p>}
        </section>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <section className="card-panel rounded-xl p-5">
            <header className="card-panel-header"><h2 className="font-semibold text-slate-900">Housing stock and dwelling composition</h2></header>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <div className="rounded-lg bg-slate-50 p-4"><div className="text-xs text-slate-500">Property inventory rows</div><div className="mt-2 text-xl font-semibold text-slate-900">{integer(report.housing_stock.hdb_property_records)}</div></div>
              <div className="rounded-lg bg-slate-50 p-4"><div className="text-xs text-slate-500">Units summed in returned records</div><div className="mt-2 text-xl font-semibold text-slate-900">{integer(report.housing_stock.total_dwelling_units_in_records)}</div></div>
            </div>
            <p className="mt-3 text-xs text-slate-500">{report.housing_stock.note || "Source status unavailable."}</p>
            <h3 className="mb-2 mt-5 text-sm font-medium text-slate-900">Inventory units by source town label</h3>
            <div className="mt-3 max-h-64 space-y-2 overflow-auto">{report.housing_stock.town_unit_counts.slice().sort((a, b) => b.units - a.units).slice(0, 15).map((r) => <div key={r.town} className="grid grid-cols-[120px_1fr_70px] items-center gap-2 text-xs"><span className="truncate text-slate-500">{r.town}</span><div className="h-3 rounded bg-slate-100"><div className="h-3 rounded bg-purple-500" style={{ width: `${Math.max(1, r.units / Math.max(1, ...report.housing_stock.town_unit_counts.map((x) => x.units)) * 100)}%` }} /></div><span className="text-right">{integer(r.units)}</span></div>)}</div>
          </section>
          <section className="card-panel rounded-xl p-5">
            <header className="card-panel-header"><h2 className="font-semibold text-slate-900">Rental, private market, vacancy & supply</h2></header>
            <div className="mt-3 space-y-3">{
              [
                { label: "Rental market", section: report.rental_market },
                { label: "Private residential", section: report.private_residential },
                { label: "Supply pipeline", section: report.supply_pipeline },
                { label: "Household context", section: report.household_context },
              ].map(({ label, section }) => <div key={label} className="border-b border-slate-100 py-3 last:border-0"><div className="text-sm font-medium text-slate-900">{label}</div><p className="mt-1 text-xs leading-relaxed text-slate-500">{section.note || "Unavailable"}</p></div>)}
            </div>
          </section>
        </div>

        <section className="card-panel rounded-xl p-5">
          <header className="card-panel-header"><h2 className="font-semibold text-slate-900">Housing stock reference records</h2></header>
          <p className="mt-3 text-xs text-slate-500">A sample of block/street records. Verified coordinates are unavailable, so the module does not fabricate map points.</p>
          <div className="mt-4 max-h-64 overflow-auto"><table className="w-full min-w-[600px] text-left text-xs"><thead className="sticky top-0 bg-slate-50 text-xs text-slate-500"><tr><th className="p-2">Block</th><th className="p-2">Street</th><th className="p-2">Town label</th><th className="p-2">Year completed</th><th className="p-2">Dwelling units</th></tr></thead><tbody>{report.housing_stock.sample_blocks.slice(0, 40).map((r, i) => <tr key={`${r.block}-${r.street}-${i}`} className="border-t border-slate-100"><td className="p-2">{r.block}</td><td className="p-2">{r.street}</td><td className="p-2">{r.town || "—"}</td><td className="p-2">{r.year_completed ?? "—"}</td><td className="p-2">{integer(r.total_dwelling_units)}</td></tr>)}</tbody></table></div>
        </section>

        <section className="card-panel rounded-xl p-5">
          <header className="card-panel-header"><h2 className="font-semibold text-slate-900">Housing Intelligence</h2></header>
          <p className="mt-3 mb-4 text-sm text-slate-500">Source-grounded prompts. Answers below are derived from the structured HousingReport; unavailable data is identified explicitly.</p>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">{report.insights.map((x) => <div key={x.question} className="rounded-lg border border-slate-200 bg-slate-50 p-4"><div className="text-sm font-semibold text-secondary">{x.question}</div><p className="mt-2 text-sm text-slate-600">{x.answer}</p><div className="mt-1 text-xs text-slate-600">Data kind: {x.data_kind}</div></div>)}</div>
        </section>

        <section className="card-panel rounded-xl p-5">
          <header className="card-panel-header"><h2 className="font-semibold text-slate-900">Data limitations</h2></header>
          <ul className="mt-4 list-disc space-y-1 pl-5 text-xs leading-relaxed text-slate-500">{report.limitations.map((x, i) => <li key={i}>{x}</li>)}</ul>
        </section>
      </>}
    </div>
  </main>;
}
