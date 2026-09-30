"use client";

import { useEffect, useState } from 'react';
import {
  FireExtinguisher,
  AlertTriangle,
  Clock,
  MapPin,
  BarChart,
  TrendingUp,
  List,
  Check,
  FileText
} from 'lucide-react';
import {
  fetchFireReport,
  type FireReport,
  type FireIncident
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

function formatDateTime(dateStr: string): string {
  if (!dateStr) return '--';
  try {
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return dateStr;
    return date.toLocaleString('en-SG', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  } catch {
    return dateStr;
  }
}

function getSeverityBadge(severity: FireIncident['severity']) {
  const styles: Record<string, string> = {
    CRITICAL: 'bg-red-500/20 text-red-400 border-red-500/30 text-xs font-semibold px-2 py-0.5 rounded',
    HIGH: 'bg-orange-500/20 text-orange-400 border-orange-500/30 text-xs font-semibold px-2 py-0.5 rounded',
    MODERATE: 'bg-amber-500/20 text-amber-400 border-amber-500/30 text-xs font-semibold px-2 py-0.5 rounded',
    LOW: 'bg-green-500/20 text-green-400 border-green-500/30 text-xs font-semibold px-2 py-0.5 rounded',
    UNKNOWN: 'bg-gray-500/20 text-gray-400 border-gray-500/30 text-xs font-semibold px-2 py-0.5 rounded',
  };
  return (
    <span className={styles[severity] || styles.UNKNOWN}>
      {severity}
    </span>
  );
}

function getStatusBadge(status: FireIncident['status']) {
  const styles: Record<string, string> = {
    ACTIVE: 'bg-red-500/20 text-red-400 border-red-500/30 text-xs font-semibold px-2 py-0.5 rounded',
    RESOLVED: 'bg-green-500/20 text-green-400 border-green-500/30 text-xs font-semibold px-2 py-0.5 rounded',
    UNKNOWN: 'bg-gray-500/20 text-gray-400 border-gray-500/30 text-xs font-semibold px-2 py-0.5 rounded',
  };
  return (
    <span className={styles[status] || styles.UNKNOWN}>
      {status}
    </span>
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
    setFireLoading(true);
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
          <FireExtinguisher size={24} className="text-red-400" />
          <h2 className="text-2xl font-heading text-red-400">Safety – Fire</h2>
        </div>

        {/* KPI Summary Section */}
        <section className="mb-6">
          <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
            <AlertTriangle size={20} className="text-red-400" />
            <span>Fire Safety Overview</span>
          </h3>

          {fireLoading && !fireReport && (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="glass-panel p-4 rounded-lg border border-gray-800 animate-pulse">
                  <div className="h-4 bg-gray-700 rounded w-3/4 mb-2"></div>
                  <div className="h-6 bg-gray-700 rounded w-1/2"></div>
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
              <KPICard label="Active Incidents" value={fireReport.active_incident_count ?? 0} icon={AlertTriangle} color="text-red-400" />
              <KPICard label="Critical Incidents" value={fireReport.critical_incident_count ?? 0} icon={FireExtinguisher} color="text-orange-400" />
              <KPICard label="Incidents Today" value={fireReport.incidents_today ?? 0} icon={Clock} color="text-yellow-400" />
              <KPICard label="Resolved Recent" value={fireReport.resolved_recent_count ?? 0} icon={Check} color="text-emerald-400" />
            </div>
          )}

          {fireReport && !fireLoading && !fireError && (
            <div className="mt-4 glass-panel p-4 rounded-lg border border-gray-800">
              <div className="text-xs text-gray-500 mb-2">Regional Breakdown</div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(fireReport.regional_counts).map(([region, count]) => (
                  <span key={region} className="px-2 py-1 text-xs bg-gray-800 rounded border border-gray-700">
                    {region}: {count ?? 0}
                  </span>
                ))}
              </div>
            </div>
          )}
        </section>

        {/* Data Source Information */}
        {fireReport && !fireLoading && !fireError && (
          <div className="mb-6 glass-panel p-4 rounded-lg border border-gray-800">
            <div className="flex flex-wrap items-start gap-4">
              <div>
                <div className="text-xs text-gray-500 mb-1">Data Sources:</div>
                <div className="text-sm text-gray-300 space-y-1">
                  {fireReport.data_sources.map((source, idx) => (
                    <div key={idx} className="flex items-center gap-1">
                      <MapPin className="w-3 h-3 text-gray-500" />
                      <span>{source}</span>
                    </div>
                  ))}
                </div>
              </div>
              {fireReport.warnings.length > 0 && (
                <div>
                  <div className="text-xs text-gray-500 mb-1">Warnings:</div>
                  <div className="text-sm text-yellow-400 space-y-1">
                    {fireReport.warnings.map((warning, idx) => (
                      <div key={idx} className="flex items-center gap-1 w-[200px] truncate" title={warning}>
                        <AlertTriangle className="w-3 h-3 text-yellow-400" />
                        <span>{warning}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {fireReport.limitations.length > 0 && (
                <div>
                  <div className="text-xs text-gray-500 mb-1">Limitations:</div>
                  <div className="text-sm text-gray-400 space-y-1">
                    {fireReport.limitations.map((limitation, idx) => (
                      <div key={idx} className="flex items-center gap-1 w-[200px] truncate" title={limitation}>
                        <FileText className="w-3 h-3 text-gray-400" />
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
          <div className="flex gap-2 mb-4 border-b border-gray-800">
            <button
              onClick={() => setActiveTab('active')}
              className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
                activeTab === 'active'
                  ? 'bg-red-500/20 text-red-400 border-b-2 border-red-400'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              <AlertTriangle className="w-4 h-4 inline mr-1" />
              Active Incidents ({activeIncidents.length})
            </button>
            <button
              onClick={() => setActiveTab('recent')}
              className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
                activeTab === 'recent'
                  ? 'bg-red-500/20 text-red-400 border-b-2 border-red-400'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              <Clock className="w-4 h-4 inline mr-1" />
              Recent Incidents ({recentIncidents.length})
            </button>
            <button
              onClick={() => setActiveTab('historical')}
              className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
                activeTab === 'historical'
                  ? 'bg-red-500/20 text-red-400 border-b-2 border-red-400'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              <BarChart className="w-4 h-4 inline mr-1" />
              Historical Data ({historicalData.length} years)
            </button>
          </div>

          {/* Tab Content */}
          <div className="glass-panel rounded-b-xl border border-gray-800 border-t-0 overflow-hidden">
            {/* Active Incidents Tab */}
            {activeTab === 'active' && (
              <div className="p-4">
                {fireLoading && activeIncidents.length === 0 && (
                  <div className="space-y-3">
                    {[...Array(3)].map((_, i) => (
                      <div key={i} className="animate-pulse glass-panel p-4 rounded-lg border border-gray-800 flex items-center gap-4">
                        <div className="w-8 h-8 bg-gray-700 rounded"></div>
                        <div className="flex-1">
                          <div className="h-4 bg-gray-700 rounded w-2/3 mb-2"></div>
                          <div className="h-3 bg-gray-700 rounded w-1/3"></div>
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
                      { key: 'id', header: 'ID', render: (inc) => <span className="font-mono text-xs text-gray-400 truncate">{inc.id}</span> },
                      { key: 'title', header: 'Incident', render: (inc) => <span className="text-white truncate max-w-[300px]" title={inc.title}>{inc.title}</span> },
                      { key: 'location', header: 'Location', render: (inc) => <span className="text-gray-300">{inc.location || '--'}</span> },
                      { key: 'incident_type', header: 'Type', render: (inc) => <span className="text-gray-300 text-capitalize">{inc.incident_type || '--'}</span> },
                      { key: 'severity', header: 'Severity', render: (inc) => getSeverityBadge(inc.severity) },
                      { key: 'status', header: 'Status', render: (inc) => getStatusBadge(inc.status) },
                      { key: 'reported_at', header: 'Reported', render: (inc) => <span className="text-gray-300">{formatDateTime(inc.reported_at || '')}</span> },
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
                      <div key={i} className="animate-pulse glass-panel p-4 rounded-lg border border-gray-800 flex items-center gap-4">
                        <div className="w-8 h-8 bg-gray-700 rounded"></div>
                        <div className="flex-1">
                          <div className="h-4 bg-gray-700 rounded w-2/3 mb-2"></div>
                          <div className="h-3 bg-gray-700 rounded w-1/3"></div>
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
                      { key: 'id', header: 'ID', render: (inc) => <span className="font-mono text-xs text-gray-400 truncate">{inc.id}</span> },
                      { key: 'title', header: 'Incident', render: (inc) => <span className="text-white truncate max-w-[300px]" title={inc.title}>{inc.title}</span> },
                      { key: 'location', header: 'Location', render: (inc) => <span className="text-gray-300">{inc.location || '--'}</span> },
                      { key: 'incident_type', header: 'Type', render: (inc) => <span className="text-gray-300 text-capitalize">{inc.incident_type || '--'}</span> },
                      { key: 'severity', header: 'Severity', render: (inc) => getSeverityBadge(inc.severity) },
                      { key: 'status', header: 'Status', render: (inc) => getStatusBadge(inc.status) },
                      { key: 'reported_at', header: 'Reported', render: (inc) => <span className="text-gray-300">{formatDateTime(inc.reported_at || '')}</span> },
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
                      <div key={i} className="animate-pulse glass-panel p-4 rounded-lg border border-gray-800 flex items-center gap-4">
                        <div className="w-8 h-8 bg-gray-700 rounded"></div>
                        <div className="flex-1">
                          <div className="h-4 bg-gray-700 rounded w-2/3 mb-2"></div>
                          <div className="h-3 bg-gray-700 rounded w-1/3"></div>
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
                    <div className="text-xs text-gray-500 mb-2">
                      Historical Fire Incidents by Year
                    </div>
                    {historicalData.length > 0 ? (
                      <DataTable
                        data={historicalData}
                        columns={[
                          { key: 'year', header: 'Year', render: (point) => <span className="font-mono text-white">{point.year}</span> },
                          { key: 'fires', header: 'Fire Count', render: (point) => <span className="text-white">{point.fires ?? 0}</span> },
                          { key: 'source', header: 'Source', render: (point) => <span className="text-gray-300 text-xs truncate">{point.source}</span> },
                        ]}
                        loading={fireLoading}
                        error={fireError}
                        emptyMessage="No historical fire data available"
                      />
                    ) : (
                      <div className="p-8 text-center text-gray-500">
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