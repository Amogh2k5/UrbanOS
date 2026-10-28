"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Building2,
  RefreshCw,
  AlertCircle,
  Database,
  HardHat,
  Award,
  MapPin,
  TrendingUp,
  Search,
  Filter,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import {
  fetchConstructionReport,
  fetchConstructionGreenmark,
  fetchConstructionPipeline,
  fetchConstructionMap,
  fetchConstructionSources,
  type ConstructionReport,
  type GreenMarkBuilding,
  type PipelineRecord,
} from "@/services/api";

const money = (value: unknown) => typeof value === "number" && Number.isFinite(value)
  ? new Intl.NumberFormat("en-SG", { style: "currency", currency: "SGD", maximumFractionDigits: 0 }).format(value)
  : "Unavailable";

const integer = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? new Intl.NumberFormat("en-SG").format(value) : "Unavailable";

const cardPanel = "rounded-2xl border border-slate-200 bg-white p-5 shadow-sm";
const cardHeader = "font-semibold text-slate-900";
const subText = "text-sm text-slate-500";
const kpiCard = "rounded-2xl border border-purple-600 bg-purple-600 p-5 shadow-sm";

function Metric({ icon, label, value, note }: { icon: React.ReactNode; label: string; value: string; note: string }) {
  return (
    <div className={kpiCard}>
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm text-white/90">{label}</span>
        <span className="text-white">{icon}</span>
      </div>
      <p className="text-2xl font-bold tracking-tight text-white">{value}</p>
      <p className="mt-2 text-xs text-white/90">{note}</p>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">{children}</div>;
}

export default function ConstructionPage() {
  const [report, setReport] = useState<ConstructionReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  // Greenmark table state
  const [gmBuildings, setGmBuildings] = useState<GreenMarkBuilding[]>([]);
  const [gmLoading, setGmLoading] = useState(false);
  const [gmError, setGmError] = useState("");
  const [gmTotal, setGmTotal] = useState(0);
  const [gmPage, setGmPage] = useState(1);
  const [gmPageSize] = useState(50);
  const [gmFilters, setGmFilters] = useState({ rating: "", projectType: "", search: "" });
  const [gmRatings, setGmRatings] = useState<string[]>([]);
  const [gmTypes, setGmTypes] = useState<string[]>([]);

  const load = useCallback(async (refresh = false) => {
    if (refresh) setRefreshing(true); else setLoading(true);
    setError("");
    try {
      const data = await fetchConstructionReport(refresh);
      setReport(data);
      // Populate filter options
      if (data.greenmark_by_rating) {
        setGmRatings(data.greenmark_by_rating.map((r: any) => r.rating).filter(Boolean));
      }
      if (data.greenmark_by_type) {
        setGmTypes(data.greenmark_by_type.map((r: any) => r.project_type).filter(Boolean));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load construction data.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  const loadGreenmark = useCallback(async () => {
    setGmLoading(true);
    setGmError("");
    try {
      const data = await fetchConstructionGreenmark(
        gmFilters.rating || undefined,
        gmFilters.projectType || undefined,
        gmFilters.search || undefined,
        gmPageSize,
        (gmPage - 1) * gmPageSize
      );
      setGmBuildings(data.buildings);
      setGmTotal(data.total);
    } catch (e) {
      setGmError(e instanceof Error ? e.message : "Unable to load Green Mark buildings.");
    } finally {
      setGmLoading(false);
    }
  }, [gmFilters, gmPage, gmPageSize]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { void loadGreenmark(); }, [loadGreenmark]);

  const pipeline = report?.pipeline_trend || [];
  const gmSummary = report?.greenmark_summary || {};
  const kpis = report?.kpis || {};

  const latestPipeline = pipeline.length > 0 ? pipeline[pipeline.length - 1] : null;
  const latestYear = (latestPipeline?.year as number) ?? null;
  const latestApproval = (latestPipeline?.building_plan_approval as number) ?? null;
  const latestCommencement = (latestPipeline?.building_commencement as number) ?? null;
  const latestCompletion = (latestPipeline?.building_completion as number) ?? null;
  const mapFeatureCount = (report?.map_data?.feature_count as number) ?? 0;

  return (
    <main className="min-h-screen bg-background px-4 py-6 text-slate-900 md:px-8">
      <div className="mx-auto max-w-[1600px] space-y-6">
        {/* Header */}
        <header className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.22em] text-primary">
              <HardHat size={15} /> Planning / Construction
            </div>
            <h1 className="text-3xl font-bold text-slate-900 md:text-4xl">Construction Intelligence</h1>
            <p className="mt-2 max-w-3xl text-sm text-slate-500">
              Singapore construction activity monitoring, development pipeline statistics, and Green Mark-certified buildings.
              Periodic statistics from official sources, not live project tracking.
            </p>
          </div>
          <button
            onClick={() => void load(true)}
            disabled={loading || refreshing}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm hover:bg-slate-50 disabled:opacity-50"
          >
            <RefreshCw size={15} className={refreshing ? "animate-spin" : ""} /> Refresh data
          </button>
        </header>

        {/* Error / Loading */}
        {error && (
          <div className="flex gap-3 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
            <AlertCircle size={18} className="shrink-0" />
            <div>
              <b>Construction data unavailable.</b>
              <div className="mt-1">{error}</div>
              <button className="mt-2 underline" onClick={() => void load(true)}>Retry</button>
            </div>
          </div>
        )}
        {loading && !report && <div className="rounded-xl border border-slate-200 bg-white p-8 text-slate-500">Loading construction data…</div>}

        {report && <>
          {/* Status Bar */}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className={`rounded-full px-3 py-1 ${
              report.status === "available" ? "bg-emerald-100 text-emerald-700" :
              report.status === "partial" ? "bg-amber-100 text-amber-700" :
              "bg-rose-100 text-rose-700"
            }`}>{report.status}</span>
            <span className="text-slate-500">Report generated {new Date(report.generated_at).toLocaleString("en-SG", { timeZone: "Asia/Singapore" })} · Singapore time</span>
            <span className="text-slate-500">Historical datasets (2013–2017 pipeline; Green Mark ongoing); not live telemetry</span>
          </div>

          {/* Data Quality Warnings */}
          {(report.errors.length > 0 || report.warnings.length > 0) && (
            <section className={cardPanel}>
              <header className="card-panel-header"><h2 className={cardHeader}>Data quality and availability</h2></header>
              <div className="mt-3 space-y-2">
                {[...report.errors, ...report.warnings].map((w, i) => (
                  <p key={i} className="text-sm text-amber-700">• {w}</p>
                ))}
              </div>
            </section>
          )}

          {/* Overview KPI Cards */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <section className={kpiCard}>
              <div className="text-xs font-semibold uppercase tracking-wider text-white/80 mb-1">Green Mark Records</div>
              <div className="text-2xl font-bold text-white">{integer(gmSummary.total_records)}</div>
              <div className="mt-1 text-xs text-white/70">Certified buildings in dataset</div>
            </section>
            <section className={kpiCard}>
              <div className="text-xs font-semibold uppercase tracking-wider text-white/80 mb-1">Latest Pipeline Year</div>
              <div className="text-2xl font-bold text-white">{latestYear !== null ? latestYear.toString() : "Unavailable"}</div>
              <div className="mt-1 text-xs text-white/70">URA private residential pipeline</div>
            </section>
            <section className={kpiCard}>
              <div className="text-xs font-semibold uppercase tracking-wider text-white/80 mb-1">Building Plan Approvals</div>
              <div className="text-2xl font-bold text-white">{integer(latestApproval)}</div>
              <div className="mt-1 text-xs text-white/70">Units approved in latest year</div>
            </section>
            <section className={kpiCard}>
              <div className="text-xs font-semibold uppercase tracking-wider text-white/80 mb-1">Completions</div>
              <div className="text-2xl font-bold text-white">{integer(latestCompletion)}</div>
              <div className="mt-1 text-xs text-white/70">Units completed in latest year</div>
            </section>
          </div>

          {/* Green Mark Summary Cards */}
          <section className={cardPanel}>
            <header className="card-panel-header"><h2 className={cardHeader}>Green Mark Certification Summary</h2></header>
            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <div className="rounded-lg bg-slate-50 p-4">
                <div className="text-xs text-slate-500">By Rating</div>
                <div className="mt-2 space-y-2">
                  {Object.entries(gmSummary.by_rating || {}).map(([rating, count]) => (
                    <div key={rating} className="flex justify-between text-sm">
                      <span className="text-slate-700">{rating}</span>
                      <span className="font-medium text-slate-900">{integer(count)}</span>
                    </div>
                  ))}
                  {Object.keys(gmSummary.by_rating || {}).length === 0 && <p className="text-sm text-slate-500">No rating data</p>}
                </div>
              </div>
              <div className="rounded-lg bg-slate-50 p-4">
                <div className="text-xs text-slate-500">By Building Type</div>
                <div className="mt-2 space-y-2 max-h-48 overflow-auto">
                  {Object.entries(gmSummary.by_type || {}).slice(0, 8).map(([type, count]) => (
                    <div key={type} className="flex justify-between text-sm">
                      <span className="text-slate-700 truncate pr-2">{type}</span>
                      <span className="font-medium text-slate-900">{integer(count)}</span>
                    </div>
                  ))}
                  {Object.keys(gmSummary.by_type || {}).length === 0 && <p className="text-sm text-slate-500">No type data</p>}
                </div>
              </div>
              <div className="rounded-lg bg-slate-50 p-4">
                <div className="text-xs text-slate-500">Data Coverage</div>
                <div className="mt-2 space-y-2 text-sm">
                  <div className="flex justify-between"><span className="text-slate-700">With cert. date</span><span className="font-medium">{integer(gmSummary.records_with_cert_date)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-700">With expiry date</span><span className="font-medium">{integer(gmSummary.records_with_expiry)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-700">With postal code</span><span className="font-medium">{integer(gmSummary.records_with_postal)}</span></div>
                </div>
              </div>
            </div>
          </section>

          {/* Construction Pipeline Trends */}
          <section className={cardPanel}>
            <header className="card-panel-header"><h2 className={cardHeader}>Residential Construction Pipeline (Private, Annual)</h2></header>
            <p className={`${subText} mb-4`}>URA data: Provisional Permission → Written Permission → Building Plan Approval → Commencement → Completion. Coverage: 2013–2017.</p>
            {pipeline.length > 0 ? (
              <div className="overflow-auto">
                <table className="w-full min-w-[700px] text-left text-sm">
                  <thead className="sticky top-0 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="p-3">Year</th>
                      <th className="p-3 text-right">Provisional Permission</th>
                      <th className="p-3 text-right">Written Permission</th>
                      <th className="p-3 text-right">Building Plan Approval</th>
                      <th className="p-3 text-right">Commencement</th>
                      <th className="p-3 text-right">Completion</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pipeline.map((row: any) => (
                      <tr key={row.year} className="border-t border-slate-100">
                        <td className="p-3 font-medium">{row.year}</td>
                        <td className="p-3 text-right tabular-nums">{integer(row.provisional_permission)}</td>
                        <td className="p-3 text-right tabular-nums">{integer(row.written_permission)}</td>
                        <td className="p-3 text-right tabular-nums">{integer(row.building_plan_approval)}</td>
                        <td className="p-3 text-right tabular-nums">{integer(row.building_commencement)}</td>
                        <td className="p-3 text-right tabular-nums">{integer(row.building_completion)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty>No pipeline records available.</Empty>
            )}
          </section>

          {/* Pipeline Chart */}
          <section className={cardPanel}>
            <header className="card-panel-header"><h2 className={cardHeader}>Pipeline Trend (Units)</h2></header>
            <p className={`${subText} mb-4`}>Annual unit counts across pipeline stages. Not all stages are available for every year.</p>
            {pipeline.length > 0 ? (
              <div className="space-y-2">
                {pipeline.map((row: any) => (
                  <div key={row.year} className="grid grid-cols-[68px_1fr_1fr_1fr_1fr_1fr] items-center gap-3 text-xs">
                    <span className="text-slate-600">{row.year}</span>
                    {[
                      { label: "Prov. Perm.", value: row.provisional_permission, color: "bg-blue-500" },
                      { label: "Written", value: row.written_permission, color: "bg-indigo-500" },
                      { label: "Approval", value: row.building_plan_approval, color: "bg-purple-500" },
                      { label: "Commence", value: row.building_commencement, color: "bg-amber-500" },
                      { label: "Complete", value: row.building_completion, color: "bg-emerald-500" },
                    ].map((stage, i) => (
                      <div key={i} className="relative">
                        <div className="h-5 rounded bg-slate-100" title={`${stage.label}: ${integer(stage.value)}`}>
                          <div className="h-5 rounded" style={{
                            width: `${row.building_plan_approval && stage.value ? Math.max(2, (stage.value / row.building_plan_approval) * 100) : 0}%`,
                            backgroundColor: stage.color.replace("bg-", "")
                          }} />
                        </div>
                        <span className="absolute right-0 top-1/2 -translate-y-1/2 text-[10px] text-slate-700 whitespace-nowrap">{integer(stage.value)}</span>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            ) : (
              <Empty>No pipeline trend data available.</Empty>
            )}
          </section>

          {/* Green Mark Buildings Table */}
          <section className={cardPanel}>
            <header className="card-panel-header">
              <div className="flex items-center justify-between">
                <h2 className={cardHeader}>Green Mark Certified Buildings</h2>
                <span className="text-xs text-slate-500">{gmTotal} records total</span>
              </div>
            </header>
            <p className={`${subText} mb-4`}>Searchable, paginated directory. Filters apply server-side. Postal codes are not precise coordinates.</p>

            {/* Filters */}
            <div className="mb-4 flex flex-wrap gap-3">
              <div className="relative flex-1 min-w-[200px]">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" size={16} />
                <input
                  type="text"
                  placeholder="Search project name…"
                  value={gmFilters.search}
                  onChange={(e) => { setGmFilters(f => ({ ...f, search: e.target.value })); setGmPage(1); }}
                  className="w-full rounded-lg border border-slate-200 bg-white pl-10 pr-3 py-2 text-sm outline-none focus:border-primary"
                />
              </div>
              <select
                value={gmFilters.rating}
                onChange={(e) => { setGmFilters(f => ({ ...f, rating: e.target.value })); setGmPage(1); }}
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-primary"
              >
                <option value="">All Ratings</option>
                {gmRatings.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
              <select
                value={gmFilters.projectType}
                onChange={(e) => { setGmFilters(f => ({ ...f, projectType: e.target.value })); setGmPage(1); }}
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-primary"
              >
                <option value="">All Types</option>
                {gmTypes.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>

            {/* Table */}
            {gmLoading ? (
              <div className="rounded-xl border border-slate-200 bg-white p-8 text-slate-500 text-center">Loading buildings…</div>
            ) : gmError ? (
              <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{gmError}</div>
            ) : gmBuildings.length > 0 ? (
              <>
                <div className="max-h-[520px] overflow-auto rounded-lg border border-slate-200">
                  <table className="w-full min-w-[900px] text-left text-sm">
                    <thead className="sticky top-0 bg-slate-50 text-xs uppercase text-slate-500">
                      <tr>
                        <th className="p-3">Project Name</th>
                        <th className="p-3">Rating</th>
                        <th className="p-3">Type</th>
                        <th className="p-3">Postal Code</th>
                        <th className="p-3">Cert. Date</th>
                        <th className="p-3">Expiry</th>
                        <th className="p-3">GFA (sqm)</th>
                        <th className="p-3">Developer</th>
                      </tr>
                    </thead>
                    <tbody>
                      {gmBuildings.map((b, i) => (
                        <tr key={b.vault_id ?? i} className="border-t border-slate-100 hover:bg-slate-50">
                          <td className="p-3 font-medium truncate max-w-xs">{b.project_name ?? b.actual_project_name ?? "—"}</td>
                          <td className="p-3">
                            {b.rating && <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700">{b.rating}</span>}
                          </td>
                          <td className="p-3 text-slate-700 truncate max-w-xs">{b.project_type ?? "—"}</td>
                          <td className="p-3 text-slate-700">{b.postal_code ?? "—"}</td>
                          <td className="p-3 text-slate-700">{b.e_cert ?? "—"}</td>
                          <td className="p-3 text-slate-700">{b.expiry ?? "—"}</td>
                          <td className="p-3 text-slate-700 tabular-nums">{b.gfa ?? "—"}</td>
                          <td className="p-3 text-slate-700 truncate max-w-xs">{b.developer ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {/* Pagination */}
                <div className="mt-4 flex items-center justify-between">
                  <p className="text-sm text-slate-500">
                    Page {gmPage} of {Math.ceil(gmTotal / gmPageSize)} · {gmTotal} records
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setGmPage(p => Math.max(1, p - 1))}
                      disabled={gmPage === 1 || gmLoading}
                      className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm disabled:opacity-50"
                    ><ChevronLeft size={16} /> Prev</button>
                    <button
                      onClick={() => setGmPage(p => Math.min(Math.ceil(gmTotal / gmPageSize), p + 1))}
                      disabled={gmPage >= Math.ceil(gmTotal / gmPageSize) || gmLoading}
                      className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm disabled:opacity-50"
                    >Next <ChevronRight size={16} /></button>
                  </div>
                </div>
              </>
            ) : (
              <Empty>No Green Mark buildings match the current filters.</Empty>
            )}
          </section>

          {/* Map Data */}
          {report.map_data?.available && (
            <section className={cardPanel}>
              <header className="card-panel-header"><h2 className={cardHeader}>Green Mark Buildings Map</h2></header>
              <p className={`${subText} mb-4`}>{mapFeatureCount} buildings with valid geometry. Postal codes shown where coordinates unavailable.</p>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm">
                <p className="text-slate-600">Map visualization available via the GeoJSON endpoint. {mapFeatureCount} features with geometry.</p>
                <p className="mt-1 text-xs text-slate-500">Use /api/planning/construction/map for full GeoJSON FeatureCollection.</p>
              </div>
            </section>
          )}

          {/* Data Sources */}
          <section className={cardPanel}>
            <header className="card-panel-header"><h2 className={cardHeader}>Data Sources</h2></header>
            <div className="mt-4 overflow-auto">
              <table className="w-full min-w-[800px] text-left text-sm">
                <thead className="sticky top-0 bg-slate-50 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="p-3">Dataset</th>
                    <th className="p-3">Agency</th>
                    <th className="p-3">Status</th>
                    <th className="p-3 text-right">Records</th>
                    <th className="p-3">Coverage</th>
                    <th className="p-3">Last Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {report.sources.map((s, i) => (
                    <tr key={s.key} className="border-t border-slate-100">
                      <td className="p-3 font-medium">{s.name}</td>
                      <td className="p-3">{s.agency}</td>
                      <td className="p-3">
                        <span className={`rounded-full px-2 py-0.5 text-xs ${
                          s.status === "available" ? "bg-emerald-100 text-emerald-700" :
                          s.status === "empty" ? "bg-amber-100 text-amber-700" :
                          "bg-rose-100 text-rose-700"
                        }`}>{s.status}</span>
                      </td>
                      <td className="p-3 text-right">{integer(s.record_count)}</td>
                      <td className="p-3 text-xs text-slate-500">
                        {s.coverage_start && s.coverage_end ? `${s.coverage_start.slice(0,10)} to ${s.coverage_end.slice(0,10)}` : "—"}
                      </td>
                      <td className="p-3 text-xs text-slate-500">{s.last_updated_at?.slice(0,10) ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* Data Limitations */}
          <section className={cardPanel}>
            <header className="card-panel-header"><h2 className={cardHeader}>Data Limitations</h2></header>
            <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-slate-600">
              {report.limitations.map((x, i) => <li key={i}>{x}</li>)}
            </ul>
          </section>

          {/* Insights */}
          {report.insights.length > 0 && (
            <section className={cardPanel}>
              <header className="card-panel-header"><h2 className={cardHeader}>Construction Intelligence</h2></header>
              <p className="mt-3 mb-4 text-sm text-slate-500">Source-grounded observations. Unavailable data is identified explicitly.</p>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {report.insights.map((x) => (
                  <div key={x.question} className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                    <div className="text-sm font-semibold text-secondary">{x.question}</div>
                    <p className="mt-2 text-sm text-slate-600">{x.answer}</p>
                    <div className="mt-1 text-xs text-slate-600">Data kind: {x.data_kind}</div>
                  </div>
                ))}
              </div>
            </section>
          )}
        </>}
      </div>
    </main>
  );
}