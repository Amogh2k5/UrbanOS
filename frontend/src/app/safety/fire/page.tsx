"use client";

import { useEffect, useState } from 'react';
import {
  FireExtinguisher,
  AlertTriangle,
  Clock,
  BarChart,
  Check,
  FileText
} from 'lucide-react';
import {
  fetchFireReport,
  type FireReport,
  type FireIncident
} from '@/services/api';
import { domainCardClass } from '@/components/city/presentation';
import { formatSingaporeDateTime } from '@/services/time';

function formatDateTime(dateStr: string): string {
  if (!dateStr) return '--';
  try {
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return dateStr;
    const formatted = formatSingaporeDateTime(date);
    return formatted === '—' ? dateStr : formatted;
  } catch {
    return dateStr;
  }
}

function getSeverityBadge(severity: FireIncident['severity']) {
  const styles: Record<string, string> = {
    CRITICAL: 'bg-red-500/20 text-red-700 border-red-500/30 text-xs font-semibold px-2 py-0.5 rounded',
    HIGH: 'bg-orange-500/20 text-orange-700 border-orange-500/30 text-xs font-semibold px-2 py-0.5 rounded',
    MODERATE: 'bg-amber-500/20 text-amber-700 border-amber-500/30 text-xs font-semibold px-2 py-0.5 rounded',
    LOW: 'bg-green-500/20 text-green-800 border-green-500/30 text-xs font-semibold px-2 py-0.5 rounded',
    UNKNOWN: 'bg-slate-200 text-slate-500 border-slate-300 text-xs font-semibold px-2 py-0.5 rounded',
  };
  return (
    <span className={styles[severity] || styles.UNKNOWN}>
      {severity}
    </span>
  );
}

function getStatusBadge(status: FireIncident['status']) {
  const styles: Record<string, string> = {
    ACTIVE: 'bg-red-500/20 text-red-700 border-red-500/30 text-xs font-semibold px-2 py-0.5 rounded',
    RESOLVED: 'bg-green-500/20 text-green-800 border-green-500/30 text-xs font-semibold px-2 py-0.5 rounded',
    UNKNOWN: 'bg-slate-200 text-slate-500 border-slate-300 text-xs font-semibold px-2 py-0.5 rounded',
  };
  return (
    <span className={styles[status] || styles.UNKNOWN}>
      {status}
    </span>
  );
}

function KPICard({ label, value, icon: Icon, color = 'text-white' }: { label: string; value: string | number; icon: React.ComponentType<{ className?: string }>; color?: string }) {
  return (
    <div className={`${domainCardClass("fire", "p-4")}`}>
      <div className="flex items-center gap-2 text-xs text-white/90 uppercase tracking-wider mb-1">
        <Icon className="h-3 w-3" />
        {label}
      </div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
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
          <div key={i} className="animate-pulse glass-panel p-4 rounded-lg border border-slate-200 flex items-center gap-4">
            <div className="w-8 h-8 bg-slate-200 rounded"></div>
            <div className="flex-1">
              <div className="h-4 bg-slate-200 rounded w-1/2 mb-2"></div>
              <div className="h-3 bg-slate-200 rounded w-1/4"></div>
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
      <div className="p-8 text-center text-slate-500">
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-slate-500 border-b border-slate-200">
            {columns.map((col) => (
              <th key={col.key} className="text-left p-3 font-medium">{col.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((item, idx) => (
            <tr key={idx} className="border-b border-slate-200 hover:bg-slate-100/30 transition-colors">
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

export default function FirePage() {
  // Fire Report state
  const [fireReport, setFireReport] = useState<FireReport | null>(null);
  const [fireError, setFireError] = useState<string | null>(null);
  const [fireLoading, setFireLoading] = useState(true);

  // UI state
  const [activeTab, setActiveTab] = useState<'active' | 'recent' | 'historical'>('active');

  // Fetch Fire Report
  useEffect(() => {
    let cancelled = false;
    fetchFireReport()
      .then((data) => { 
        if (!cancelled) { 
          setFireReport(data); 
          setFireError(null); 
        } 
      })
      .catch((err: Error) => { 
        if (!cancelled) setFireError(err.message); 
      })
      .finally(() => { 
        if (!cancelled) setFireLoading(false); 
      });
    return () => { cancelled = true; };
  }, []);

  // Filter data for tabs
  const activeIncidents = fireReport?.active_incidents || [];
  const recentIncidents = fireReport?.recent_incidents || [];
  const historicalData = fireReport?.historical_fire_counts || [];

  return (
    <div className="h-full bg-[var(--color-background)] text-[var(--color-foreground)] p-4 md:p-6 lg:p-8 flex flex-col font-sans">
      <div className="flex flex-col flex-grow min-h-0 overflow-y-auto">
        {/* Header */}
        <div className="mb-6 flex items-center gap-3">
          <FireExtinguisher size={24} className="text-red-700" />
          <h2 className="text-2xl font-heading text-red-700">Safety – Fire</h2>
        </div>

        {/* KPI Summary Section */}
        <section className="mb-6">
          <h3 className="text-lg font-bold text-slate-900 mb-4 flex items-center gap-2">
            <AlertTriangle size={20} className="text-red-700" />
            <span>Fire Safety Overview</span>
          </h3>

          {fireLoading && !fireReport && (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="glass-panel p-4 rounded-lg border border-slate-200 animate-pulse">
                  <div className="h-4 bg-slate-200 rounded w-3/4 mb-2"></div>
                  <div className="h-6 bg-slate-200 rounded w-1/2"></div>
                </div>
              ))}
            </div>
          )}

          {fireError && !fireLoading && (
            <div className="glass-panel p-4 rounded-lg border border-red-500/30 text-red-500 text-sm">
              Failed to load fire data: {fireError}
            </div>
          )}

          {fireReport && !fireLoading && !fireError && (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              <KPICard label="Active Incidents" value={fireReport.active_incident_count ?? 0} icon={AlertTriangle} />
              <KPICard label="Critical Incidents" value={fireReport.critical_incident_count ?? 0} icon={FireExtinguisher} />
              <KPICard label="Incidents Today" value={fireReport.incidents_today ?? 0} icon={Clock} />
              <KPICard label="Resolved Recent" value={fireReport.resolved_recent_count ?? 0} icon={Check} />
            </div>
          )}

          {fireReport && !fireLoading && !fireError && (
            <div className="mt-4 glass-panel p-4 rounded-lg border border-slate-200">
              <div className="text-xs text-slate-500 mb-2">Regional Breakdown</div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(fireReport.regional_counts).map(([region, count]) => (
                  <span key={region} className="px-2 py-1 text-xs bg-slate-100 rounded border border-slate-200">
                    {region}: {count ?? 0}
                  </span>
                ))}
              </div>
            </div>
          )}
        </section>

        {fireReport && !fireLoading && !fireError && (
          <div className="mb-6 glass-panel p-4 rounded-lg border border-slate-200">
            <div className="flex flex-wrap items-start gap-4">
              {fireReport.warnings.length > 0 && (
                <div>
                  <div className="text-xs text-slate-500 mb-1">Warnings:</div>
                  <div className="text-sm text-yellow-800 space-y-1">
                    {fireReport.warnings.map((warning, idx) => (
                      <div key={idx} className="flex items-center gap-1 w-[200px] truncate" title={warning}>
                        <AlertTriangle className="w-3 h-3 text-yellow-800" />
                        <span>{warning}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {fireReport.limitations.length > 0 && (
                <div>
                  <div className="text-xs text-slate-500 mb-1">Limitations:</div>
                  <div className="text-sm text-slate-500 space-y-1">
                    {fireReport.limitations.map((limitation, idx) => (
                      <div key={idx} className="flex items-center gap-1 w-[200px] truncate" title={limitation}>
                        <FileText className="w-3 h-3 text-slate-500" />
                        <span>{limitation}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Tabbed Content Area */}
        <div className="mb-6">
          <div className="flex gap-2 mb-4 border-b border-slate-200">
            <button
              onClick={() => setActiveTab('active')}
              className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
                activeTab === 'active'
                  ? 'bg-red-500/20 text-red-700 border-b-2 border-red-400'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <AlertTriangle className="w-4 h-4 inline mr-1" />
              Active Incidents ({activeIncidents.length})
            </button>
            <button
              onClick={() => setActiveTab('recent')}
              className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
                activeTab === 'recent'
                  ? 'bg-red-500/20 text-red-700 border-b-2 border-red-400'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <Clock className="w-4 h-4 inline mr-1" />
              Recent Incidents ({recentIncidents.length})
            </button>
            <button
              onClick={() => setActiveTab('historical')}
              className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
                activeTab === 'historical'
                  ? 'bg-red-500/20 text-red-700 border-b-2 border-red-400'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <BarChart className="w-4 h-4 inline mr-1" />
              Historical Data ({historicalData.length} years)
            </button>
          </div>

          {/* Tab Content */}
          <div className="glass-panel rounded-b-xl border border-slate-200 border-t-0 overflow-hidden">
            {/* Active Incidents Tab */}
            {activeTab === 'active' && (
              <div className="p-4">
                {fireLoading && activeIncidents.length === 0 && (
                  <div className="space-y-3">
                    {[...Array(3)].map((_, i) => (
                      <div key={i} className="animate-pulse glass-panel p-4 rounded-lg border border-slate-200 flex items-center gap-4">
                        <div className="w-8 h-8 bg-slate-200 rounded"></div>
                        <div className="flex-1">
                          <div className="h-4 bg-slate-200 rounded w-2/3 mb-2"></div>
                          <div className="h-3 bg-slate-200 rounded w-1/3"></div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {fireError && !fireLoading && (
                  <div className="p-4 text-red-500 text-sm">Failed to load incidents: {fireError}</div>
                )}

                {!fireLoading && !fireError && (
                  <DataTable
                    data={activeIncidents}
                    columns={[
                      { key: 'id', header: 'ID', render: (inc) => <span className="font-mono text-xs text-slate-500 truncate">{inc.id}</span> },
                      { key: 'title', header: 'Incident', render: (inc) => <span className="text-slate-800 truncate max-w-[300px]" title={inc.title}>{inc.title}</span> },
                      { key: 'location', header: 'Location', render: (inc) => <span className="text-slate-600">{inc.location || '--'}</span> },
                      { key: 'incident_type', header: 'Type', render: (inc) => <span className="text-slate-600 text-capitalize">{inc.incident_type || '--'}</span> },
                      { key: 'severity', header: 'Severity', render: (inc) => getSeverityBadge(inc.severity) },
                      { key: 'status', header: 'Status', render: (inc) => getStatusBadge(inc.status) },
                      { key: 'reported_at', header: 'Reported', render: (inc) => <span className="text-slate-600">{formatDateTime(inc.reported_at || '')}</span> },
                    ]}
                    loading={fireLoading}
                    error={fireError}
                    emptyMessage="No active fire incidents found"
                  />
                )}
              </div>
            )}

            {/* Recent Incidents Tab */}
            {activeTab === 'recent' && (
              <div className="p-4">
                {fireLoading && recentIncidents.length === 0 && (
                  <div className="space-y-3">
                    {[...Array(3)].map((_, i) => (
                      <div key={i} className="animate-pulse glass-panel p-4 rounded-lg border border-slate-200 flex items-center gap-4">
                        <div className="w-8 h-8 bg-slate-200 rounded"></div>
                        <div className="flex-1">
                          <div className="h-4 bg-slate-200 rounded w-2/3 mb-2"></div>
                          <div className="h-3 bg-slate-200 rounded w-1/3"></div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {fireError && !fireLoading && (
                  <div className="p-4 text-red-500 text-sm">Failed to load recent incidents: {fireError}</div>
                )}

                {!fireLoading && !fireError && (
                  <DataTable
                    data={recentIncidents}
                    columns={[
                      { key: 'id', header: 'ID', render: (inc) => <span className="font-mono text-xs text-slate-500 truncate">{inc.id}</span> },
                      { key: 'title', header: 'Incident', render: (inc) => <span className="text-slate-800 truncate max-w-[300px]" title={inc.title}>{inc.title}</span> },
                      { key: 'location', header: 'Location', render: (inc) => <span className="text-slate-600">{inc.location || '--'}</span> },
                      { key: 'incident_type', header: 'Type', render: (inc) => <span className="text-slate-600 text-capitalize">{inc.incident_type || '--'}</span> },
                      { key: 'severity', header: 'Severity', render: (inc) => getSeverityBadge(inc.severity) },
                      { key: 'status', header: 'Status', render: (inc) => getStatusBadge(inc.status) },
                      { key: 'reported_at', header: 'Reported', render: (inc) => <span className="text-slate-600">{formatDateTime(inc.reported_at || '')}</span> },
                    ]}
                    loading={fireLoading}
                    error={fireError}
                    emptyMessage="No recent fire incidents found"
                  />
                )}
              </div>
            )}

            {/* Historical Data Tab */}
            {activeTab === 'historical' && (
              <div className="p-4">
                {fireLoading && historicalData.length === 0 && (
                  <div className="space-y-3">
                    {[...Array(3)].map((_, i) => (
                      <div key={i} className="animate-pulse glass-panel p-4 rounded-lg border border-slate-200 flex items-center gap-4">
                        <div className="w-8 h-8 bg-slate-200 rounded"></div>
                        <div className="flex-1">
                          <div className="h-4 bg-slate-200 rounded w-2/3 mb-2"></div>
                          <div className="h-3 bg-slate-200 rounded w-1/3"></div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {fireError && !fireLoading && (
                  <div className="p-4 text-red-500 text-sm">Failed to load historical data: {fireError}</div>
                )}

                {!fireLoading && !fireError && (
                  <div className="space-y-4">
                    <div className="text-xs text-slate-500 mb-2">
                      Historical Fire Incidents by Year
                    </div>
                    {historicalData.length > 0 ? (
                      <DataTable
                        data={historicalData}
                        columns={[
                          { key: 'year', header: 'Year', render: (point) => <span className="font-mono text-slate-800">{point.year}</span> },
                          { key: 'fires', header: 'Fire Count', render: (point) => <span className="text-slate-800">{point.fires ?? 0}</span> },
                        ]}
                        loading={fireLoading}
                        error={fireError}
                        emptyMessage="No historical fire data available"
                      />
                    ) : (
                      <div className="p-8 text-center text-slate-500">
                        No historical fire data available
                      </div>
                    )}
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
