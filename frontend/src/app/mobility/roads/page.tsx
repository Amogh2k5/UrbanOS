"use client";

import { useEffect, useState } from 'react';
import {
  Road,
  Construction,
  Car,
  Accessibility,
  TrendingUp,
  Package,
  Truck,
  Building,
  Calendar,
} from 'lucide-react';
import {
  fetchRoadWorks,
  fetchRoadOpenings,
  fetchTaxiStands,
  fetchRoadsAnalytics,
  fetchRoadSpeedContext,
  type RoadWork,
  type RoadOpening,
  type TaxiStand,
  type RoadsAnalytics,
  type RoadSpeedContext,
} from '@/services/api';

function formatDate(dateStr: string): string {
  if (!dateStr) return '--';
  try {
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return dateStr;
    return date.toLocaleDateString('en-SG', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    });
  } catch {
    return dateStr;
  }
}

function getStatusBadge(status: 'active' | 'upcoming' | 'completed') {
  const styles: Record<string, string> = {
    active: 'bg-red-500/20 text-red-400 border-red-500/30',
    upcoming: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    completed: 'bg-green-500/20 text-green-400 border-green-500/30',
  };
  return (
    <span className={`px-2 py-0.5 text-xs font-medium rounded-full border ${styles[status] || 'bg-gray-500/20 text-gray-400'}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

function getOwnershipBadge(ownership: string) {
  const colors: Record<string, string> = {
    LTA: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    Private: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
    CCS: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
    SMRT: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  };
  const style = colors[ownership] || 'bg-gray-500/20 text-gray-400 border-gray-500/30';
  return (
    <span className={`px-2 py-0.5 text-xs font-medium rounded-full border ${style}`}>
      {ownership}
    </span>
  );
}

function getBFACheck(isAccessible: boolean) {
  return isAccessible ? (
    <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
    </svg>
  ) : (
    <svg className="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
    </svg>
  );
}

function KPICard({ label, value, icon: Icon, color = 'text-white' }: { label: string; value: string | number; icon: React.ComponentType<{ className?: string }>; color?: string }) {
  return (
    <div className="glass-panel p-4 rounded-lg border border-gray-800">
      <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
    </div>
  );
}

function StatusFilters({ active, onChange, labels }: { active: 'all' | 'active' | 'upcoming'; onChange: (v: 'all' | 'active' | 'upcoming') => void; labels: { all: string; active: string; upcoming: string } }) {
  return (
    <div className="flex flex-wrap gap-2 mb-4">
      {(['all', 'active', 'upcoming'] as const).map((filter) => (
        <button
          key={filter}
          onClick={() => onChange(filter)}
          className={`px-3 py-1.5 text-xs font-medium rounded-full transition-colors ${
            active === filter
              ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
              : 'text-gray-400 hover:text-white border border-gray-700'
          }`}
        >
          {labels[filter as keyof typeof labels]}
        </button>
      ))}
    </div>
  );
}

function DataTable<T>({ 
  data, 
  columns, 
  loading, 
  error, 
  emptyMessage 
}: { 
  data: T[]; 
  columns: { key: string; header: string; render: (item: T) => React.ReactNode }[]; 
  loading: boolean; 
  error: string | null; 
  emptyMessage: string; 
}) {
  if (loading && !data.length) {
    return (
      <div className="space-y-3">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="animate-pulse glass-panel p-4 rounded-lg border border-gray-800 flex items-center gap-4">
            <div className="w-8 h-8 bg-gray-700 rounded"></div>
            <div className="flex-1">
              <div className="h-4 bg-gray-700 rounded w-1/2 mb-2"></div>
              <div className="h-3 bg-gray-700 rounded w-1/4"></div>
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return <div className="p-4 text-red-500 text-sm">Failed to load: {error}</div>;
  }

  if (!data.length) {
    return (
      <div className="p-8 text-center text-gray-500">
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-gray-500 border-b border-gray-800">
            {columns.map((col) => (
              <th key={col.key} className="text-left p-3 font-medium">{col.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((item, idx) => (
            <tr key={idx} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
              {columns.map((col) => (
                <td key={col.key} className="p-3">{col.render(item)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function RoadsPage() {
  // Analytics state
  const [analytics, setAnalytics] = useState<RoadsAnalytics | null>(null);
  const [analyticsError, setAnalyticsError] = useState<string | null>(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(true);

  // Road Works state
  const [roadWorks, setRoadWorks] = useState<RoadWork[]>([]);
  const [roadWorksError, setRoadWorksError] = useState<string | null>(null);
  const [roadWorksLoading, setRoadWorksLoading] = useState(true);
  const [worksFilter, setWorksFilter] = useState<'all' | 'active' | 'upcoming'>('all');

  // Road Openings state
  const [roadOpenings, setRoadOpenings] = useState<RoadOpening[]>([]);
  const [roadOpeningsError, setRoadOpeningsError] = useState<string | null>(null);
  const [roadOpeningsLoading, setRoadOpeningsLoading] = useState(true);
  const [openingsFilter, setOpeningsFilter] = useState<'all' | 'active' | 'upcoming'>('all');

  // Car Stands state
  const [taxiStands, setTaxiStands] = useState<TaxiStand[]>([]);
  const [taxiStandsError, setTaxiStandsError] = useState<string | null>(null);
  const [taxiStandsLoading, setTaxiStandsLoading] = useState(true);

  // UI state
  const [activeTab, setActiveTab] = useState<'works' | 'openings' | 'taxi' | 'speed'>('works');

  // Speed Context state
  const [speedContext, setSpeedContext] = useState<RoadSpeedContext | null>(null);
  const [speedContextError, setSpeedContextError] = useState<string | null>(null);
  const [speedContextLoading, setSpeedContextLoading] = useState(true);

  // Fetch Analytics
  useEffect(() => {
    let cancelled = false;
    fetchRoadsAnalytics()
      .then((data) => { if (!cancelled) { setAnalytics(data); setAnalyticsError(null); } })
      .catch((err: Error) => { if (!cancelled) setAnalyticsError(err.message); })
      .finally(() => { if (!cancelled) setAnalyticsLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Fetch Road Works
  useEffect(() => {
    let cancelled = false;
    setRoadWorksLoading(true);
    fetchRoadWorks(50, 0, worksFilter === 'all' ? undefined : worksFilter)
      .then((data) => { if (!cancelled) { setRoadWorks(data.works); setRoadWorksError(null); } })
      .catch((err: Error) => { if (!cancelled) setRoadWorksError(err.message); })
      .finally(() => { if (!cancelled) setRoadWorksLoading(false); });
    return () => { cancelled = true; };
  }, [worksFilter]);

  // Fetch Road Openings
  useEffect(() => {
    let cancelled = false;
    setRoadOpeningsLoading(true);
    fetchRoadOpenings(50, 0, openingsFilter === 'all' ? undefined : openingsFilter)
      .then((data) => { if (!cancelled) { setRoadOpenings(data.openings); setRoadOpeningsError(null); } })
      .catch((err: Error) => { if (!cancelled) setRoadOpeningsError(err.message); })
      .finally(() => { if (!cancelled) setRoadOpeningsLoading(false); });
    return () => { cancelled = true; };
  }, [openingsFilter]);

  // Fetch Car Stands
  useEffect(() => {
    let cancelled = false;
    setTaxiStandsLoading(true);
    fetchTaxiStands(316, 0)
      .then((data) => { if (!cancelled) { setTaxiStands(data.stands); setTaxiStandsError(null); } })
      .catch((err: Error) => { if (!cancelled) setTaxiStandsError(err.message); })
      .finally(() => { if (!cancelled) setTaxiStandsLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Fetch Speed Context
  useEffect(() => {
    let cancelled = false;
    setSpeedContextLoading(true);
    fetchRoadSpeedContext()
      .then((data) => { if (!cancelled) { setSpeedContext(data); setSpeedContextError(null); } })
      .catch((err: Error) => { if (!cancelled) setSpeedContextError(err.message); })
      .finally(() => { if (!cancelled) setSpeedContextLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Filter data for display
  const filteredWorks = roadWorks;
  const filteredOpenings = roadOpenings;

  return (
    <div className="h-full bg-[var(--color-background)] text-[var(--color-foreground)] p-4 md:p-6 lg:p-8 flex flex-col font-sans">
      <div className="flex flex-col flex-grow min-h-0 overflow-y-auto">
        {/* Header */}
        <div className="mb-6 flex items-center gap-3">
          <Road size={24} className="text-blue-400" />
          <h2 className="text-2xl font-heading text-blue-400">Road Infrastructure Intelligence</h2>
        </div>

        {/* KPI Summary Section */}
        <section className="mb-6">
          <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
            <Package size={20} className="text-blue-400" />
            <span>Road Infrastructure Overview</span>
          </h3>

          {analyticsLoading && !analytics && (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
              {[...Array(6)].map((_, i) => (
                <div key={i} className="glass-panel p-4 rounded-lg border border-gray-800 animate-pulse">
                  <div className="h-4 bg-gray-700 rounded w-3/4 mb-2"></div>
                  <div className="h-8 bg-gray-700 rounded w-1/3"></div>
                </div>
              ))}
            </div>
          )}

          {analyticsError && !analyticsLoading && (
            <div className="glass-panel p-4 rounded-lg border border-red-500/30 text-red-500 text-sm">
              Failed to load analytics: {analyticsError}
            </div>
          )}

          {analytics && !analyticsLoading && !analyticsError && (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
              <KPICard label="Active Road Works" value={analytics.road_works.active} icon={Construction} color="text-red-400" />
              <KPICard label="Upcoming Works" value={analytics.road_works.upcoming} icon={TrendingUp} color="text-amber-400" />
              <KPICard label="Road Openings" value={analytics.road_openings.upcoming} icon={Truck} color="text-blue-400" />
              <KPICard label="Car Stands" value={analytics.taxi_stands.total} icon={Car} color="text-white" />
              <KPICard label="BFA Accessible" value={analytics.taxi_stands.bfa_accessible} icon={Accessibility} color="text-emerald-400" />
              <KPICard 
                label="Ownership Types" 
                value={Object.keys(analytics.taxi_stands.by_ownership).length} 
                icon={Building} 
                color="text-purple-400" 
              />
            </div>
          )}

          {analytics && !analyticsLoading && !analyticsError && (
            <div className="mt-4 glass-panel p-4 rounded-lg border border-gray-800">
              <div className="text-xs text-gray-500 mb-2">Ownership Breakdown</div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(analytics.taxi_stands.by_ownership).map(([key, val]) => (
                  <span key={key} className="px-2 py-1 text-xs bg-gray-800 rounded border border-gray-700">
                    {key}: {val}
                  </span>
                ))}
              </div>
            </div>
          )}
        </section>

        {/* Speed Context Section */}
        <section className="mb-6">
          <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
            <TrendingUp size={20} className="text-cyan-400" />
            <span>Road Speed Context (Live)</span>
          </h3>

          {speedContextLoading && !speedContext && (
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="glass-panel p-4 rounded-lg border border-gray-800 animate-pulse">
                  <div className="h-4 bg-gray-700 rounded w-3/4 mb-2"></div>
                  <div className="h-6 bg-gray-700 rounded w-1/2"></div>
                </div>
              ))}
            </div>
          )}

          {speedContextError && !speedContextLoading && (
            <div className="glass-panel p-4 rounded-lg border border-red-500/30 text-red-500 text-sm">
              Speed context unavailable: {speedContextError}
            </div>
          )}

          {speedContext && !speedContextLoading && !speedContextError && (
            <div className="space-y-2">
              <div className="text-xs text-gray-500">
                Showing top 10 of {speedContext.total_roads} roads by speed change (predicted vs current)
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-gray-500 border-b border-gray-800">
                      <th className="text-left p-3 font-medium">Road</th>
                      <th className="text-right p-3 font-medium">Current</th>
                      <th className="text-right p-3 font-medium">Predicted</th>
                      <th className="text-right p-3 font-medium">Change</th>
                      <th className="text-right p-3 font-medium">Segments</th>
                    </tr>
                  </thead>
                  <tbody>
                    {speedContext.roads.slice(0, 10).map((road, idx) => (
                      <tr key={`${road.road}-${idx}`} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                        <td className="p-3 font-mono text-white truncate max-w-[200px]" title={road.road}>
                          {road.road}
                        </td>
                        <td className="p-3 text-right font-mono text-white">{road.avg_current_speed.toFixed(1)} km/h</td>
                        <td className="p-3 text-right font-mono text-white">{road.avg_predicted_speed.toFixed(1)} km/h</td>
                        <td className="p-3 text-right font-mono">
                          <span className={road.avg_change > 0 ? 'text-green-400' : road.avg_change < 0 ? 'text-red-400' : 'text-gray-400'}>
                            {road.avg_change > 0 ? '+' : ''}{road.avg_change.toFixed(1)} km/h
                          </span>
                        </td>
                        <td className="p-3 text-right font-mono text-gray-400">{road.segment_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>

        {/* Tabbed Content Area */}
        <div className="mb-6">
          <div className="flex gap-2 mb-4 border-b border-gray-800">
            <button
              onClick={() => setActiveTab('works')}
              className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
                activeTab === 'works'
                  ? 'bg-blue-500/20 text-blue-400 border-b-2 border-blue-400'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              <Construction className="w-4 h-4 inline mr-1" />
              Road Works ({roadWorks.length})
            </button>
            <button
              onClick={() => setActiveTab('openings')}
              className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
                activeTab === 'openings'
                  ? 'bg-blue-500/20 text-blue-400 border-b-2 border-blue-400'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              <Truck className="w-4 h-4 inline mr-1" />
              Road Openings ({roadOpenings.length})
            </button>
            <button
              onClick={() => setActiveTab('taxi')}
              className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
                activeTab === 'taxi'
                  ? 'bg-blue-500/20 text-blue-400 border-b-2 border-blue-400'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              <Car className="w-4 h-4 inline mr-1" />
              Car Stands ({taxiStands.length})
            </button>
            <button
              onClick={() => setActiveTab('speed')}
              className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
                activeTab === 'speed'
                  ? 'bg-blue-500/20 text-blue-400 border-b-2 border-blue-400'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              <TrendingUp className="w-4 h-4 inline mr-1" />
              Speed Context
            </button>
          </div>

          {/* Tab Content */}
          <div className="glass-panel rounded-b-xl border border-gray-800 border-t-0 overflow-hidden">
            {/* Road Works Tab */}
            {activeTab === 'works' && (
              <div className="p-4">
                <StatusFilters
                  active={worksFilter}
                  onChange={setWorksFilter}
                  labels={{ all: 'All', active: 'Active', upcoming: 'Upcoming' }}
                />
                <DataTable
                  data={filteredWorks}
                  columns={[
                    { key: 'road_name', header: 'Road', render: (w) => <span className="font-mono text-white truncate max-w-[200px]" title={w.road_name}>{w.road_name}</span> },
                    { key: 'period', header: 'Period', render: (w) => <span className="text-gray-300"><span className="flex items-center gap-1 text-xs"><Calendar className="w-3 h-3 text-gray-500" />{formatDate(w.start_date)} – {formatDate(w.end_date)}</span></span> },
                    { key: 'svc_dept', header: 'Dept', render: (w) => <span className="text-gray-400 text-xs truncate max-w-[120px]">{w.svc_dept}</span> },
                    { key: 'status', header: 'Status', render: (w) => getStatusBadge(w.is_active ? 'active' : w.is_upcoming ? 'upcoming' : 'completed') },
                  ]}
                  loading={roadWorksLoading}
                  error={roadWorksError}
                  emptyMessage="No road works found for this filter"
                />
              </div>
            )}

            {/* Road Openings Tab */}
            {activeTab === 'openings' && (
              <div className="p-4">
                <StatusFilters
                  active={openingsFilter}
                  onChange={setOpeningsFilter}
                  labels={{ all: 'All', active: 'Active', upcoming: 'Upcoming' }}
                />
                <DataTable
                  data={filteredOpenings}
                  columns={[
                    { key: 'road_name', header: 'Road', render: (o) => <span className="font-mono text-white truncate max-w-[200px]" title={o.road_name}>{o.road_name}</span> },
                    { key: 'period', header: 'Period', render: (o) => <span className="text-gray-300"><span className="flex items-center gap-1 text-xs"><Calendar className="w-3 h-3 text-gray-500" />{formatDate(o.start_date)} – {formatDate(o.end_date)}</span></span> },
                    { key: 'svc_dept', header: 'Dept', render: (o) => <span className="text-gray-400 text-xs truncate max-w-[120px]">{o.svc_dept}</span> },
                    { key: 'status', header: 'Status', render: (o) => getStatusBadge(o.is_active ? 'active' : o.is_upcoming ? 'upcoming' : 'completed') },
                  ]}
                  loading={roadOpeningsLoading}
                  error={roadOpeningsError}
                  emptyMessage="No road openings found for this filter"
                />
              </div>
            )}

            {/* Car Stands Tab */}
            {activeTab === 'taxi' && (
              <div className="p-4">
                <div className="flex flex-wrap gap-2 mb-4">
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <input type="checkbox" className="w-4 h-4 accent-blue-500" />
                    <Accessibility className="w-4 h-4" /> BFA Only
                  </label>
                </div>
                <DataTable
                  data={taxiStands}
                  columns={[
                    { key: 'taxi_code', header: 'Code', render: (s) => <span className="font-mono text-blue-400">{s.taxi_code}</span> },
                    { key: 'name', header: 'Name', render: (s) => <span className="text-white truncate max-w-[250px]" title={s.name}>{s.name}</span> },
                    { key: 'type', header: 'Type', render: (s) => <span className="text-gray-300 text-xs capitalize">{s.type.toLowerCase()}</span> },
                    { key: 'ownership', header: 'Ownership', render: (s) => getOwnershipBadge(s.ownership) },
                    { key: 'bfa', header: 'BFA', render: (s) => <span className="text-center">{getBFACheck(s.is_bfa_accessible)}</span> },
                  ]}
                  loading={taxiStandsLoading}
                  error={taxiStandsError}
                  emptyMessage="No taxi stands found"
                />
              </div>
            )}

            {/* Speed Context Tab */}
            {activeTab === 'speed' && (
              <div className="p-4">
                {speedContextLoading && !speedContext && (
                  <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
                    {[...Array(5)].map((_, i) => (
                      <div key={i} className="glass-panel p-4 rounded-lg border border-gray-800 animate-pulse">
                        <div className="h-4 bg-gray-700 rounded w-3/4 mb-2"></div>
                        <div className="h-6 bg-gray-700 rounded w-1/2"></div>
                      </div>
                    ))}
                  </div>
                )}

                {speedContextError && !speedContextLoading && (
                  <div className="p-4 text-red-500 text-sm">Speed context unavailable: {speedContextError}</div>
                )}

                {speedContext && !speedContextLoading && !speedContextError && (
                  <div className="space-y-2">
                    <div className="text-xs text-gray-500">
                      Showing top 10 of {speedContext.total_roads} roads by speed change (predicted vs current)
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-gray-500 border-b border-gray-800">
                            <th className="text-left p-3 font-medium">Road</th>
                            <th className="text-right p-3 font-medium">Current</th>
                            <th className="text-right p-3 font-medium">Predicted</th>
                            <th className="text-right p-3 font-medium">Change</th>
                            <th className="text-right p-3 font-medium">Segments</th>
                          </tr>
                        </thead>
                        <tbody>
                          {speedContext.roads.slice(0, 10).map((road, idx) => (
                            <tr key={`${road.road}-${idx}`} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                              <td className="p-3 font-mono text-white truncate max-w-[200px]" title={road.road}>{road.road}</td>
                              <td className="p-3 text-right font-mono text-white">{road.avg_current_speed.toFixed(1)} km/h</td>
                              <td className="p-3 text-right font-mono text-white">{road.avg_predicted_speed.toFixed(1)} km/h</td>
                              <td className="p-3 text-right font-mono"><span className={road.avg_change > 0 ? 'text-green-400' : road.avg_change < 0 ? 'text-red-400' : 'text-gray-400'}>{road.avg_change > 0 ? '+' : ''}{road.avg_change.toFixed(1)} km/h</span></td>
                              <td className="p-3 text-right font-mono text-gray-400">{road.segment_count}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}