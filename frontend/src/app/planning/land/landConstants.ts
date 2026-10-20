import type { LandDataKind, LandGroup, LandSourceStatus } from "@/services/api";

// Kept in its own module so the page can import colours without pulling in the
// map library (same rationale as waterConstants.ts).

export const GROUP_LABEL: Record<LandGroup, string> = {
  residential: 'Residential',
  commercial: 'Commercial',
  industrial: 'Industrial',
  institutional: 'Institutional',
  transport: 'Transport',
  recreation: 'Parks / Recreation',
  water: 'Water',
  other: 'Other',
};

// Order here is the order the backend emits by_group in.
export const GROUP_ORDER: LandGroup[] = [
  'residential', 'commercial', 'industrial', 'institutional',
  'transport', 'recreation', 'water', 'other',
];

export const GROUP_COLOR: Record<LandGroup, string> = {
  residential: '#f472b6',
  commercial: '#fbbf24',
  industrial: '#38bdf8',
  institutional: '#a78bfa',
  transport: '#94a3b8',
  recreation: '#4ade80',
  water: '#22d3ee',
  other: '#64748b',
};

export const DATA_KIND_STYLE: Record<LandDataKind, { label: string; cls: string }> = {
  live: { label: 'LIVE', cls: 'text-green-800 bg-green-500/10 border-green-500/30' },
  latest_available: { label: 'LATEST AVAILABLE', cls: 'text-cyan-700 bg-cyan-500/10 border-cyan-500/30' },
  historical: { label: 'HISTORICAL', cls: 'text-violet-800 bg-violet-500/10 border-violet-500/30' },
  forecast: { label: 'FORECAST', cls: 'text-amber-800 bg-amber-500/10 border-amber-500/30' },
  unavailable: { label: 'UNAVAILABLE', cls: 'text-slate-600 bg-slate-100 border-slate-300' },
};

export const SOURCE_STATUS_STYLE: Record<LandSourceStatus, { label: string; cls: string }> = {
  available: { label: 'ALL SOURCES OK', cls: 'text-green-800 bg-green-500/10 border-green-500/30' },
  partial: { label: 'PARTIAL DATA', cls: 'text-amber-800 bg-amber-500/10 border-amber-500/30' },
  unavailable: { label: 'SOURCES UNAVAILABLE', cls: 'text-red-700 bg-red-500/10 border-red-500/30' },
};
