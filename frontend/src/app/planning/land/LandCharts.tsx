"use client";

import { GROUP_COLOR, GROUP_LABEL, GROUP_ORDER } from "./landConstants";
import type { LandGroup } from "@/services/api";

const W = 560;
const H = 210;
const PAD = { l: 120, r: 40, t: 10, b: 24 };

/**
 * Land-use area per analytical group, as a horizontal bar chart.
 *
 * Groups with a null area are rendered as an explicit "no data" row rather
 * than as a zero-length bar, so an unavailable dataset can never be mistaken
 * for a category with no land.
 */
export function GroupBars({ byGroup }: { byGroup: Record<string, number | null> }) {
  const groups = GROUP_ORDER.filter((g) => byGroup[g] !== undefined);
  if (!groups.length) {
    return <div className="text-xs text-gray-600 py-8 text-center">Land-use area unavailable.</div>;
  }

  const values = groups.map((g) => byGroup[g]);
  const reported = values.filter((v): v is number => typeof v === 'number' && v > 0);
  if (!reported.length) {
    return <div className="text-xs text-gray-600 py-8 text-center">No land-use area reported by the source.</div>;
  }
  const max = Math.max(...reported);
  const total = reported.reduce((a, b) => a + b, 0);
  const rowH = (H - PAD.t - PAD.b) / groups.length;
  const barH = Math.min(rowH - 6, 16);

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="Land use area by group">
        {groups.map((g, i) => {
          const v = byGroup[g];
          const y = PAD.t + i * rowH + (rowH - barH) / 2;
          const w = typeof v === 'number' && v > 0 ? ((W - PAD.l - PAD.r) * v) / max : 0;
          const unavailable = typeof v !== 'number';
          return (
            <g key={g}>
              <text x={PAD.l - 8} y={y + barH / 2 + 3} textAnchor="end" fontSize={10} fill="#9ca3af">
                {GROUP_LABEL[g]}
              </text>
              {unavailable ? (
                <text x={PAD.l + 4} y={y + barH / 2 + 3} fontSize={9} fill="#6b7280">
                  no data reported
                </text>
              ) : (
                <>
                  <rect x={PAD.l} y={y} width={w} height={barH} fill={GROUP_COLOR[g as LandGroup]} opacity={0.85} />
                  <text x={PAD.l + w + 6} y={y + barH / 2 + 3} fontSize={9} fill="#d1d5db">
                    {(v / 1e6).toFixed(1)} km²
                  </text>
                </>
              )}
            </g>
          );
        })}
      </svg>
      <div className="text-[10px] text-gray-500 mt-1">
        Sum of the Master Plan land-use zones carrying a published SHAPE.AREA ({total / 1e6 < 0 ? 0 : (total / 1e6).toFixed(1)} km²
        across groups). Zones with overlapping designations can be counted in more than one group.
      </div>
    </div>
  );
}

/**
 * Share of total land-use area per group, as a single stacked bar.
 * Segments with no reported area are simply absent from the stack.
 */
export function GroupShareBar({ byGroup }: { byGroup: Record<string, number | null> }) {
  const entries = GROUP_ORDER
    .map((g) => ({ g, v: byGroup[g] }))
    .filter((e): e is { g: LandGroup; v: number } => typeof e.v === 'number' && e.v > 0);
  if (!entries.length) {
    return <div className="text-xs text-gray-600 py-8 text-center">Land-use composition unavailable.</div>;
  }
  const total = entries.reduce((a, e) => a + e.v, 0);
  const WIDE = 560;
  const BAR = 34;
  const inner = WIDE - 2;

  // Cumulative offsets computed up front so render never mutates shared state.
  const segs = entries.reduce<{ g: LandGroup; v: number; x: number; w: number }[]>((acc, e) => {
    const prev = acc.length ? acc[acc.length - 1] : null;
    const x = prev ? prev.x + prev.w : 0;
    acc.push({ g: e.g, v: e.v, x, w: Math.max((inner * e.v) / total, 0.5) });
    return acc;
  }, []);

  return (
    <div>
      <svg viewBox={`0 0 ${WIDE} ${BAR + 8}`} className="w-full h-auto" role="img" aria-label="Land use composition">
        {segs.map((s) => (
          <rect key={s.g} x={s.x} y={4} width={s.w} height={BAR} fill={GROUP_COLOR[s.g]} opacity={0.9}>
            <title>{`${GROUP_LABEL[s.g]}: ${((s.v / total) * 100).toFixed(1)}%`}</title>
          </rect>
        ))}
      </svg>
      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[10px] text-gray-400">
        {entries.map((e) => (
          <span key={e.g} className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 inline-block" style={{ background: GROUP_COLOR[e.g] }} />
            {GROUP_LABEL[e.g]} {((e.v / total) * 100).toFixed(1)}%
          </span>
        ))}
      </div>
    </div>
  );
}

/**
 * GLS awards per year as a column chart, using only the years the source
 * actually reported. Years with no award are omitted rather than drawn as 0.
 */
export function YearBars({ byYear }: { byYear: Record<string, number | null> }) {
  const entries = Object.entries(byYear)
    .map(([year, v]) => ({ year, v }))
    .filter((e): e is { year: string; v: number } => typeof e.v === 'number');
  if (!entries.length) {
    return <div className="text-xs text-gray-600 py-8 text-center">GLS award history unavailable.</div>;
  }
  const max = Math.max(...entries.map((e) => e.v));
  const cw = (W - PAD.l - PAD.r) / entries.length;
  const y = (v: number) => PAD.t + (1 - v / max) * (H - PAD.t - PAD.b);
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="GLS sites awarded per year">
        {[0, max / 2, max].map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="#1f2937" strokeWidth={1} />
            <text x={PAD.l - 6} y={y(t) + 3} textAnchor="end" fontSize={9} fill="#6b7280">
              {t.toFixed(0)}
            </text>
          </g>
        ))}
        {entries.map((e, i) => {
          const x = PAD.l + i * cw + cw * 0.2;
          const w = cw * 0.6;
          return (
            <g key={e.year}>
              <rect x={x} y={y(e.v)} width={w} height={Math.max(y(0) - y(e.v), 1)} fill="#22d3ee" opacity={0.8}>
                <title>{`${e.year}: ${e.v} site(s)`}</title>
              </rect>
            </g>
          );
        })}
        {entries.map((e, i) => {
          if (i % Math.max(1, Math.ceil(entries.length / 10)) !== 0 && i !== entries.length - 1) return null;
          return (
            <text key={`l-${e.year}`} x={PAD.l + i * cw + cw / 2} y={H - 6} textAnchor="middle" fontSize={8} fill="#6b7280">
              {`'${e.year.slice(2)}`}
            </text>
          );
        })}
      </svg>
      <div className="text-[10px] text-gray-500 mt-1">
        Awarded Government Land Sales sites per year of award. Years with no recorded award are not plotted.
      </div>
    </div>
  );
}