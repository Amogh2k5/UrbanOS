"use client";

import type { WasteCategoryRow, WasteSeries } from "@/services/api";

const W = 560;
const H = 190;
const PAD = { l: 48, r: 14, t: 12, b: 24 };

/** Format a number with locale rounding (half-up on the shortest decimal; avoids toFixed(2) of 7.015 -> "7.01"). */
export function fmt(v: number | null | undefined, digits = 1): string {
  return v == null ? "—" : v.toLocaleString("en-SG", { minimumFractionDigits: 0, maximumFractionDigits: digits });
}

export function fmtMt(tonnes: number | null | undefined, digits = 2): string {
  return tonnes == null
    ? "—"
    : (tonnes / 1_000_000).toLocaleString("en-SG", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function niceMax(max: number) {
  if (max <= 0) return 1;
  const pow = Math.pow(10, Math.floor(Math.log10(max)));
  const n = max / pow;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return step * pow;
}

export interface LineSpec {
  series: WasteSeries;
  color: string;
  dashed?: boolean;
}

/**
 * Multi-series line chart over years. Missing (null) values create gaps, never zeros.
 * `divisor` rescales values for display (1e6: tonnes -> million tonnes); `yMin` fixes the axis floor.
 */
export function LineChart({
  lines,
  divisor = 1,
  unitLabel,
  yMin,
  yMax,
  digits = 0,
  label,
}: {
  lines: LineSpec[];
  divisor?: number;
  unitLabel: string;
  yMin?: number;
  yMax?: number;
  digits?: number;
  label: string;
}) {
  const pts = lines.flatMap((l) => l.series.points.filter((p) => p.value != null).map((p) => ({ y: p.year, v: (p.value as number) / divisor })));
  if (pts.length < 2) return <div className="text-xs text-slate-600 py-10 text-center">Not enough data to chart.</div>;
  const years = pts.map((p) => p.y);
  const x0 = Math.min(...years);
  const x1 = Math.max(...years);
  const vals = pts.map((p) => p.v);
  const lo = yMin ?? Math.min(0, Math.min(...vals));
  const hi = yMax ?? niceMax(Math.max(...vals) * 1.05);
  const x = (yr: number) => PAD.l + ((yr - x0) / (x1 - x0 || 1)) * (W - PAD.l - PAD.r);
  const y = (v: number) => PAD.t + (1 - (v - lo) / (hi - lo || 1)) * (H - PAD.t - PAD.b);
  const ticks = [lo, lo + (hi - lo) / 2, hi];
  const step = Math.max(1, Math.ceil((x1 - x0) / 6));
  const xTicks = Array.from(new Set([...Array.from({ length: Math.floor((x1 - x0) / step) + 1 }, (_, i) => x0 + i * step), x1]));

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label={label}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="#cbd5e1" strokeWidth={1} />
            <text x={PAD.l - 6} y={y(t) + 3} textAnchor="end" fontSize={9} fill="#475569">{fmt(t, digits)}</text>
          </g>
        ))}
        {xTicks.map((t) => (
          <text key={t} x={x(t)} y={H - 6} textAnchor="middle" fontSize={9} fill="#475569">{t}</text>
        ))}
        {lines.map((l) => {
          const present = l.series.points.filter((p) => p.value != null);
          let d = "";
          let prev: number | null = null;
          for (const p of present) {
            // break the path wherever a year is missing
            const cmd = prev !== null && p.year - prev === 1 ? "L" : "M";
            d += `${cmd}${x(p.year).toFixed(1)},${y((p.value as number) / divisor).toFixed(1)} `;
            prev = p.year;
          }
          const last = present[present.length - 1];
          return (
            <g key={l.series.key}>
              <path d={d} fill="none" stroke={l.color} strokeWidth={2} strokeDasharray={l.dashed ? "5 3" : undefined} />
              {present.map((p) => (
                <circle key={p.year} cx={x(p.year)} cy={y((p.value as number) / divisor)} r={last && p.year === last.year ? 3.5 : 1.8} fill={l.color}>
                  <title>{`${l.series.label} ${p.year}: ${fmt((p.value as number) / divisor, 2)} ${unitLabel}`}</title>
                </circle>
              ))}
            </g>
          );
        })}
      </svg>
      <div className="flex flex-wrap gap-4 mt-1 text-[10px] text-slate-600">
        {lines.map((l) => (
          <span key={l.series.key} className="flex items-center gap-1.5">
            <span className="w-3 h-0.5 inline-block" style={{ background: l.color }} />
            {l.series.label} ({unitLabel})
          </span>
        ))}
      </div>
    </div>
  );
}

/** Per year: recycled + disposed stacked (their sum is the year's total generated; gaps where either is missing). */
export function RecycledDisposedBars({ recycled, disposed, generated }: { recycled: WasteSeries; disposed: WasteSeries; generated: WasteSeries }) {
  const dMap = new Map(disposed.points.filter((p) => p.value != null).map((p) => [p.year, p.value as number]));
  const gMap = new Map(generated.points.filter((p) => p.value != null).map((p) => [p.year, p.value as number]));
  const rows = recycled.points
    .filter((p) => p.value != null && dMap.has(p.year))
    .map((p) => ({ year: p.year, rec: p.value as number, dis: dMap.get(p.year) as number, gen: gMap.get(p.year) }));
  if (rows.length === 0) return <div className="text-xs text-slate-600 py-10 text-center">Not enough data to chart.</div>;
  const hi = niceMax(Math.max(...rows.map((r) => r.rec + r.dis)) / 1e6 * 1.05);
  const bw = (W - PAD.l - PAD.r) / rows.length;
  const y = (v: number) => PAD.t + (1 - v / hi) * (H - PAD.t - PAD.b);
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="Waste recycled and disposed per year; stacked height is total generated">
        {[0, hi / 2, hi].map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="#cbd5e1" strokeWidth={1} />
            <text x={PAD.l - 6} y={y(t) + 3} textAnchor="end" fontSize={9} fill="#475569">{fmt(t, 1)}</text>
          </g>
        ))}
        {rows.map((r, i) => {
          const bx = PAD.l + i * bw + bw * 0.15;
          const w = bw * 0.7;
          const rec = r.rec / 1e6;
          const dis = r.dis / 1e6;
          return (
            <g key={r.year}>
              <rect x={bx} y={y(rec)} width={w} height={y(0) - y(rec)} fill="#4ade80" opacity={0.85}>
                <title>{`${r.year} recycled: ${fmt(rec, 2)} Mt`}</title>
              </rect>
              <rect x={bx} y={y(rec + dis)} width={w} height={y(rec) - y(rec + dis)} fill="#fb923c" opacity={0.85}>
                <title>{`${r.year} disposed: ${fmt(dis, 2)} Mt · generated: ${fmt(r.gen != null ? r.gen / 1e6 : null, 2)} Mt`}</title>
              </rect>
              {(i % Math.ceil(rows.length / 9) === 0 || i === rows.length - 1) && (
                <text x={bx + w / 2} y={H - 6} textAnchor="middle" fontSize={9} fill="#475569">{r.year}</text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="flex gap-4 mt-1 text-[10px] text-slate-600">
        <span className="flex items-center gap-1.5"><span className="w-3 h-2 inline-block bg-green-400" />Recycled (million tonnes)</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-2 inline-block bg-orange-400" />Disposed (million tonnes)</span>
        <span className="text-slate-600">Bar height = total generated</span>
      </div>
    </div>
  );
}

/** Horizontal bars: tonnes generated per waste type, split into recycled (green) and disposed (orange). */
export function CategoryBars({ rows }: { rows: WasteCategoryRow[] }) {
  const usable = rows.filter((r) => r.generated != null);
  if (usable.length === 0) return <div className="text-xs text-slate-600 py-10 text-center">Waste-type breakdown unavailable.</div>;
  const max = Math.max(...usable.map((r) => r.generated as number));
  return (
    <div className="space-y-1.5" role="img" aria-label="Waste generated by type, split into recycled and disposed">
      {usable.map((r) => {
        const gen = r.generated as number;
        const rec = r.recycled != null ? Math.min(r.recycled, gen) : null;
        const dis = r.disposed != null ? Math.min(r.disposed, gen) : null;
        const rate = r.recycling_rate_computed;
        return (
          <div key={r.key} className="grid grid-cols-[130px_1fr_92px] items-center gap-2 text-[11px]">
            <span className="text-slate-700 truncate" title={r.label}>{r.label}</span>
            <div className="h-4 bg-slate-100 rounded-sm overflow-hidden" style={{ width: `${(gen / max) * 100}%`, minWidth: 2 }}
              title={`${r.label}: ${fmtMt(gen, 3)} Mt generated · ${fmtMt(rec, 3)} Mt recycled · ${fmtMt(dis, 3)} Mt disposed`}>
              <div className="h-full flex">
                {rec != null && <div className="h-full bg-green-400/85" style={{ width: `${(rec / gen) * 100}%` }} />}
                {dis != null && <div className="h-full bg-orange-400/85" style={{ width: `${(dis / gen) * 100}%` }} />}
              </div>
            </div>
            <span className="font-mono text-slate-600 text-right">
              {fmtMt(gen)} <span className="text-slate-600">· {rate == null ? "—" : `${fmt(rate, 0)}%`}</span>
            </span>
          </div>
        );
      })}
      <div className="flex flex-wrap gap-4 pt-1 text-[10px] text-slate-600">
        <span className="flex items-center gap-1.5"><span className="w-3 h-2 inline-block bg-green-400" />Recycled</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-2 inline-block bg-orange-400" />Disposed</span>
        <span className="text-slate-600">Right column: million tonnes generated · recycling rate</span>
      </div>
    </div>
  );
}
