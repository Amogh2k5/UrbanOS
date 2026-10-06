"use client";

import { useEffect, useState } from "react";

interface CrimeReport {
  generated_at: string;
  source_status: string;
  data_period: string;
  data_sources: string[];
  total_physical_crime_2025: number | null;
  total_scams_cybercrime_2025: number | null;
  total_scams_2025: number | null;
  physical_crime_rate_2025: number | null;
  arrests_2025_total_selected_offences: number | null;
  overview: Array<{
    name: string;
    values: Record<string, number | null>;
    unit: string;
  }>;
  major_offences: Array<{
    name: string;
    values: Record<string, number | null>;
    unit: string;
  }>;
  arrests: Array<{
    offence: string;
    values: Record<string, number | null>;
  }>;
  npc_geography: Array<{
    npc: string;
    offence: string;
    values: Record<string, number | null>;
  }>;
  scam_types: Array<{
    name: string;
    cases: number;
    loss_sgd_million: number;
    average_loss_sgd: number;
  }>;
  geographic_scope: string;
  limitations: string[];
  warnings: string[];
  errors: string[];
  is_ml_prediction: boolean;
}

interface CrimeClientProps {
  initialData?: CrimeReport | null;
}

function formatNumber(num: number | null): string {
  if (num === null || num === undefined) return "—";
  return new Intl.NumberFormat().format(num);
}

function formatRate(rate: number | null): string {
  if (rate === null || rate === undefined) return "—";
  return `${rate.toFixed(1)} per 100k`;
}

export default function CrimeClient({ initialData }: CrimeClientProps) {
  const [data, setData] = useState<CrimeReport | null>(initialData ?? null);
  const [loading, setLoading] = useState(!initialData);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialData) return;

    async function fetchCrimeReport() {
      try {
        const res = await fetch("/api/crime/report");
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        }
        const json = await res.json();
        setData(json);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load crime data");
      } finally {
        setLoading(false);
      }
    }

    fetchCrimeReport();
  }, [initialData]);

  if (loading) {
    return (
      <div className="p-6 space-y-4">
        <div className="flex items-center gap-4">
          <div className="animate-pulse bg-slate-800 h-8 w-48 rounded" />
          <div className="animate-pulse bg-slate-800 h-4 w-64 rounded" />
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {[1, 2, 3].map(i => (
            <div key={i} className="animate-pulse bg-slate-800 h-24 rounded-lg p-4" />
          ))}
        </div>
        <div className="animate-pulse bg-slate-800 h-64 rounded-lg" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 text-center text-red-400">
        <h2 className="text-lg font-semibold mb-2">Unable to load crime data</h2>
        <p className="text-sm text-gray-500">{error}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="p-6 text-center text-gray-500">
        No crime data available.
      </div>
    );
  }

  const isUnavailable = data.source_status === "unavailable";
  const isPartial = data.source_status === "partial";

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Safety – Crime</h1>
          <p className="text-sm text-gray-500 mt-1">
            Official Singapore crime statistics from Singapore Police Force (SPF) via data.gov.sg / SINGSTAT
          </p>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <span className={`px-3 py-1 rounded-full text-xs font-medium ${
            isUnavailable ? "bg-red-900/30 text-red-400" :
            isPartial ? "bg-amber-900/30 text-amber-400" :
            "bg-green-900/30 text-green-400"
          }`}>
            {data.source_status === "available" ? "Data Available" :
             data.source_status === "partial" ? "Partial Data" : "Unavailable"}
          </span>
          <time className="text-gray-500 font-mono">
            {new Date(data.generated_at).toLocaleString("en-SG", {
              timeZone: "Asia/Singapore",
              year: "numeric", month: "short", day: "numeric",
              hour: "2-digit", minute: "2-digit"
            })} SGT
          </time>
        </div>
      </div>

      {/* Status banner for partial/unavailable */}
      {(isUnavailable || isPartial || data.warnings.length > 0) && (
        <div className={`p-4 rounded-lg border text-sm ${
          isUnavailable ? "bg-red-900/20 border-red-800 text-red-300" :
          "bg-amber-900/20 border-amber-800 text-amber-300"
        }`}>
          {isUnavailable && (
            <>
              <p className="font-medium">Crime data is temporarily unavailable.</p>
              <p className="mt-1">The official data.gov.sg API is currently rate-limited (HTTP 429). Please try again later.</p>
            </>
          )}
          {isPartial && (
            <>
              <p className="font-medium">Partial crime data loaded.</p>
              <p className="mt-1">One or more official datasets could not be retrieved; missing datasets are not represented as zero.</p>
            </>
          )}
          {data.warnings.length > 0 && !isUnavailable && !isPartial && (
            <ul className="list-disc list-inside space-y-1">
              {data.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          )}
        </div>
      )}

      {/* Summary KPIs */}
      {!isUnavailable && (
        <div className="grid gap-4 md:grid-cols-3">
          <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Physical Crime (2025)</p>
            <p className="text-3xl font-bold tabular-nums">{formatNumber(data.total_physical_crime_2025)}</p>
            <p className="text-xs text-gray-500 mt-1">Rate: {formatRate(data.physical_crime_rate_2025)}</p>
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Scams & Cybercrime (2025)</p>
            <p className="text-3xl font-bold tabular-nums">{formatNumber(data.total_scams_cybercrime_2025)}</p>
            <p className="text-xs text-gray-500 mt-1">Scams only: {formatNumber(data.total_scams_2025)}</p>
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Arrests (2025)</p>
            <p className="text-3xl font-bold tabular-nums">
              {data.arrests_2025_total_selected_offences !== null
                ? formatNumber(data.arrests_2025_total_selected_offences)
                : "—"}
            </p>
            <p className="text-xs text-gray-500 mt-1">Selected offences total</p>
          </div>
        </div>
      )}

      {/* Overview Table */}
      {!isUnavailable && data.overview.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold mb-4">Crime Overview by Category (Annual)</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm border border-slate-800">
              <thead>
                <tr className="bg-slate-900 border-b border-slate-800">
                  <th className="p-3 text-left font-medium">Category</th>
                  <th className="p-3 text-right font-medium">2022</th>
                  <th className="p-3 text-right font-medium">2023</th>
                  <th className="p-3 text-right font-medium">2024</th>
                  <th className="p-3 text-right font-medium">2025</th>
                  <th className="p-3 text-left font-medium text-gray-500">Unit</th>
                </tr>
              </thead>
              <tbody>
                {data.overview.map((row, idx) => (
                  <tr key={idx} className="border-b border-slate-800/50 hover:bg-slate-900/50">
                    <td className="p-3 font-medium">{row.name}</td>
                    <td className="p-3 text-right tabular-nums">{formatNumber(row.values["2022"])}</td>
                    <td className="p-3 text-right tabular-nums">{formatNumber(row.values["2023"])}</td>
                    <td className="p-3 text-right tabular-nums">{formatNumber(row.values["2024"])}</td>
                    <td className="p-3 text-right tabular-nums font-medium">{formatNumber(row.values["2025"])}</td>
                    <td className="p-3 text-left text-gray-500">{row.unit}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-gray-500 mt-2">Source: {data.data_sources[0]}</p>
        </section>
      )}

      {/* Scam Types */}
      {!isUnavailable && data.scam_types.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold mb-4">Top Scam Types (2025)</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm border border-slate-800">
              <thead>
                <tr className="bg-slate-900 border-b border-slate-800">
                  <th className="p-3 text-left font-medium">Scam Type</th>
                  <th className="p-3 text-right font-medium">Cases</th>
                  <th className="p-3 text-right font-medium">Total Loss (SGD M)</th>
                  <th className="p-3 text-right font-medium">Avg Loss (SGD)</th>
                </tr>
              </thead>
              <tbody>
                {data.scam_types.map((row, idx) => (
                  <tr key={idx} className="border-b border-slate-800/50 hover:bg-slate-900/50">
                    <td className="p-3 font-medium">{row.name}</td>
                    <td className="p-3 text-right tabular-nums">{formatNumber(row.cases)}</td>
                    <td className="p-3 text-right tabular-nums">{row.loss_sgd_million.toFixed(1)}</td>
                    <td className="p-3 text-right tabular-nums">{formatNumber(row.average_loss_sgd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-gray-500 mt-2">
            Source: Singapore Police Force Annual Scam and Cybercrime Brief 2025 Infographic (official PDF release).
          </p>
        </section>
      )}

      {/* Data Period & Sources */}
      <section className="pt-4 border-t border-slate-800">
        <h3 className="text-sm font-medium mb-2">Data Information</h3>
        <dl className="grid gap-2 sm:grid-cols-2 text-sm">
          <dt className="text-gray-500">Data Period</dt>
          <dd className="text-white">{data.data_period}</dd>
          <dt className="text-gray-500">Geographic Scope</dt>
          <dd className="text-white">{data.geographic_scope}</dd>
          <dt className="text-gray-500">Generated</dt>
          <dd className="text-white font-mono">
            {new Date(data.generated_at).toLocaleString("en-SG", { timeZone: "Asia/Singapore" })} SGT
          </dd>
          <dt className="text-gray-500">ML Prediction</dt>
          <dd className="text-white">{data.is_ml_prediction ? "Yes" : "No"}</dd>
        </dl>

        {data.data_sources.length > 0 && (
          <div className="mt-4">
            <h4 className="text-sm font-medium mb-2 text-gray-400">Data Sources</h4>
            <ul className="text-sm text-gray-300 list-disc list-inside space-y-1">
              {data.data_sources.map((src, i) => <li key={i}>{src}</li>)}
            </ul>
          </div>
        )}

        {data.limitations.length > 0 && (
          <div className="mt-4">
            <h4 className="text-sm font-medium mb-2 text-gray-400">Limitations</h4>
            <ul className="text-sm text-gray-300 list-disc list-inside space-y-1">
              {data.limitations.map((lim, i) => <li key={i}>{lim}</li>)}
            </ul>
          </div>
        )}

        {data.errors.length > 0 && (
          <div className="mt-4">
            <h4 className="text-sm font-medium mb-2 text-red-400">Errors</h4>
            <ul className="text-sm text-red-300 list-disc list-inside space-y-1">
              {data.errors.map((err, i) => <li key={i}>{err}</li>)}
            </ul>
          </div>
        )}
      </section>
    </div>
  );
}