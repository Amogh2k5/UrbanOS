"use client";

import type { WaterSeries } from "@/services/api";

const W = 560;
const H = 180;
const PAD = { l: 44, r: 12, t: 12, b: 24 };

function scale(values: number[], pad = 0.08) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || Math.abs(max) || 1;
  return { lo: Math.max(0, min - span * pad), hi: max + span * pad };
}

/** Multi-series line chart over years. Missing (null) values create gaps, never zeros. */
export function LineChart({ series, colors }: { series: WaterSeries[]; colors: string[] }) {
  const all = series.flatMap((s) => s.points.filter((p) => p.value != null).map((p) => ({ y: p.year, v: p.value as number })));
  if (all.length < 2) {
    return <div className="text-xs text-gray-600 py-8 text-center">Not enough data to chart.</div>;
  }
  const years = all.map((p) => p.y);
  const x0 = Math.min(...years);
  const x1 = Math.max(...years);
  const { lo, hi } = scale(all.map((p) => p.v));
  const x = (yr: number) => PAD.l + ((yr - x0) / (x1 - x0 || 1)) * (W - PAD.l - PAD.r);
  const y = (v: number) => PAD.t + (1 - (v - lo) / (hi - lo || 1)) * (H - PAD.t - PAD.b);
  const ticks = [lo, (lo + hi) / 2, hi];
  const xTicks = Array.from(new Set([x0, Math.round((x0 + x1) / 2), x1]));

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="Annual water series">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="#1f2937" strokeWidth={1} />
            <text x={PAD.l - 6} y={y(t) + 3} textAnchor="end" fontSize={9} fill="#6b7280">{t.toFixed(0)}</text>
          </g>
        ))}
        {xTicks.map((t) => (
          <text key={t} x={x(t)} y={H - 6} textAnchor="middle" fontSize={9} fill="#6b7280">{t}</text>
        ))}
        {series.map((s, i) => {
          const pts = s.points.filter((p) => p.value != null);
          // break the path where consecutive years are missing
          let d = "";
          let prev: number | null = null;
          for (const p of pts) {
            const cmd = prev !== null && p.year - prev === 1 ? "L" : "M";
            d += `${cmd}${x(p.year).toFixed(1)},${y(p.value as number).toFixed(1)} `;
            prev = p.year;
          }
          const last = pts[pts.length - 1];
          return (
            <g key={s.key}>
              <path d={d} fill="none" stroke={colors[i % colors.length]} strokeWidth={2} />
              {last && <circle cx={x(last.year)} cy={y(last.value as number)} r={3} fill={colors[i % colors.length]} />}
            </g>
          );
        })}
      </svg>
      <div className="flex flex-wrap gap-4 mt-1 text-[10px] text-gray-400">
        {series.map((s, i) => (
          <span key={s.key} className="flex items-center gap-1.5">
            <span className="w-3 h-0.5 inline-block" style={{ background: colors[i % colors.length] }} />
            {s.label} ({s.unit})
          </span>
        ))}
      </div>
    </div>
  );
}

/** Stacked domestic / non-domestic bars for years where both values exist. */
export function StackedBars({ domestic, nonDomestic }: { domestic: WaterSeries; nonDomestic: WaterSeries }) {
  const nd = new Map(nonDomestic.points.filter((p) => p.value != null).map((p) => [p.year, p.value as number]));
  const rows = domestic.points
    .filter((p) => p.value != null && nd.has(p.year))
    .map((p) => ({ year: p.year, dom: p.value as number, non: nd.get(p.year) as number }));
  if (rows.length === 0) {
    return <div className="text-xs text-gray-600 py-8 text-center">Not enough data to chart.</div>;
  }
  const max = Math.max(...rows.map((r) => r.dom + r.non));
  const bw = (W - PAD.l - PAD.r) / rows.length;
  const y = (v: number) => PAD.t + (1 - v / max) * (H - PAD.t - PAD.b);
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="Domestic and non-domestic potable water sales by year">
        {[0, max / 2, max].map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="#1f2937" strokeWidth={1} />
            <text x={PAD.l - 6} y={y(t) + 3} textAnchor="end" fontSize={9} fill="#6b7280">{t.toFixed(0)}</text>
          </g>
        ))}
        {rows.map((r, i) => {
          const x = PAD.l + i * bw + bw * 0.15;
          const w = bw * 0.7;
          return (
            <g key={r.year}>
              <rect x={x} y={y(r.dom)} width={w} height={y(0) - y(r.dom)} fill="#22d3ee" opacity={0.85}>
                <title>{`${r.year} domestic: ${r.dom}`}</title>
              </rect>
              <rect x={x} y={y(r.dom + r.non)} width={w} height={y(r.dom) - y(r.dom + r.non)} fill="#a78bfa" opacity={0.85}>
                <title>{`${r.year} non-domestic: ${r.non}`}</title>
              </rect>
              {(i % Math.ceil(rows.length / 8) === 0 || i === rows.length - 1) && (
                <text x={x + w / 2} y={H - 6} textAnchor="middle" fontSize={9} fill="#6b7280">{r.year}</text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="flex gap-4 mt-1 text-[10px] text-gray-400">
        <span className="flex items-center gap-1.5"><span className="w-3 h-2 inline-block bg-cyan-400" />Domestic (million m³)</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-2 inline-block bg-violet-400" />Non-domestic (million m³)</span>
      </div>
    </div>
  );
}
