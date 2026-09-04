/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useEffect, useState } from 'react';
import { fetchTrafficReport } from '@/services/api';

import { Car, MapPin, AlertTriangle, Activity, Map, TrendingUp, AlertCircle, Info } from 'lucide-react';
import TrafficMap from './TrafficMap';

export default function TrafficPage() {
  const [data, setData] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadData = async () => {
      try {
        const result = await fetchTrafficReport();
        setData(result);
        setError(null);
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : String(err));
      }
    };
    loadData();
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, []);

  const getTrafficColor = (state: string) => {
    switch (state?.toLowerCase()) {
      case 'heavy': return 'text-red-500';
      case 'moderate': return 'text-yellow-500';
      case 'clear': return 'text-green-500';
      default: return 'text-gray-400';
    }
  };

  const getTrafficStatusColor = (state: string) => {
    switch (state?.toLowerCase()) {
      case 'disrupted': return 'text-red-500';
      case 'attention': return 'text-yellow-500';
      case 'normal': return 'text-green-500';
      default: return 'text-gray-400';
    }
  };

  const extractRoadName = (msg: string) => {
    if (!msg) return 'Unknown Location';
    const match = msg.match(/on\s(.*?)(?:\s\(|\safter|\.|$)/i);
    return match ? match[1].trim() : 'Unknown Location';
  };

  const extractDescription = (msg: string) => {
    if (!msg) return '';
    return msg.replace(/^\(\d+\/\d+\)\d+:\d+\s/, '').trim();
  };

  if (!data && !error) {
    return (
      <div className="h-full bg-[var(--color-background)] text-[var(--color-foreground)] p-4 flex flex-col font-sans">
        
        <div className="flex items-center justify-center h-64 text-gray-500 animate-pulse font-mono">Loading Traffic Report...</div>
      </div>
    );
  }

  const incidents = data?.incidents || [];
  const activeIncidentsCount = incidents.length;
  const affectedZones = new Set(incidents.map((i: any) => i.zone_name).filter(Boolean));

  // Dynamically count by type
  const typeCounts: Record<string, number> = {};
  incidents.forEach((i: any) => {
    const t = i.type || 'Unknown';
    typeCounts[t] = (typeCounts[t] || 0) + 1;
  });

  const sortedTypes = Object.entries(typeCounts).sort((a, b) => b[1] - a[1]);
  
  const displayCategories: { name: string, count: number }[] = [];
  let otherCount = 0;
  
  sortedTypes.forEach(([type, count], index) => {
    if (index < 3) {
      displayCategories.push({ name: type, count });
    } else {
      otherCount += count;
    }
  });
  
  if (otherCount > 0) {
    displayCategories.push({ name: 'Other', count: otherCount });
  }

  // Compute incident counts per zone
  const zoneIncidentCounts: Record<string, number> = {};
  if (data?.zones) {
    data.zones.forEach((z: any) => {
      zoneIncidentCounts[z.zone_name] = z.incident_count || 0;
    });
  }

  return (
    <div className="h-full bg-[var(--color-background)] text-[var(--color-foreground)] p-4 md:p-6 lg:p-8 flex flex-col font-sans">
      
      <div className="flex flex-col flex-grow min-h-0 overflow-y-auto custom-scrollbar">
        <h2 className="text-2xl font-heading text-[var(--color-primary)] mb-6 flex items-center gap-3">
          <Car size={24} />
          Traffic Intelligence
        </h2>
        
        {error && <div className="text-red-500 mb-4 glass-panel p-4 rounded-lg border border-red-500/30">{error}</div>}
        
        {data && (
          <div className="flex flex-col gap-6">
            
            {/* Section: LIVE TRAFFIC */}
            <div className="mb-2 border-b border-gray-800 pb-2">
              <h3 className="text-sm font-bold text-gray-400 uppercase tracking-widest">Live Traffic</h3>
              <p className="text-xs text-gray-500">What is happening now?</p>
            </div>
            
            {/* Top row: Status & Map */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              
              {/* Live Traffic Status */}
              <div className="glass-panel p-6 rounded-lg flex flex-col">
                <h3 className="font-bold text-lg mb-4 flex items-center space-x-2 text-cyan-400 uppercase tracking-widest text-xs">
                  <Activity size={18} />
                  <span>Live Traffic Status</span>
                </h3>
                
                <div className="flex-grow flex flex-col justify-between space-y-6">
                  <div className="grid grid-cols-2 gap-4">
                    <div className="bg-gray-900/40 p-4 rounded border border-gray-800">
                      <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Status</div>
                      <div className={`text-xl font-bold uppercase tracking-wider ${getTrafficStatusColor(data.overall_status)}`}>
                        {data.overall_status || 'UNKNOWN'}
                      </div>
                    </div>
                    <div className="bg-gray-900/40 p-4 rounded border border-gray-800">
                      <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Congestion</div>
                      <div className={`text-xl font-bold uppercase tracking-wider ${getTrafficColor(data.overall_congestion_level)}`}>
                        {data.overall_congestion_level || '--'}
                      </div>
                    </div>
                  </div>

                  <div className="space-y-3 bg-gray-900/20 p-4 rounded border border-gray-800/50">
                    <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                      <span className="text-gray-400 text-sm">Active incidents</span>
                      <span className="font-mono text-white font-bold">{activeIncidentsCount}</span>
                    </div>
                    {displayCategories.map((cat, idx) => (
                      <div key={cat.name} className={`flex justify-between items-center text-xs text-gray-500 pl-4 ${idx === displayCategories.length - 1 ? 'border-b border-gray-800 pb-2' : ''}`}>
                        <span>{cat.name}</span>
                        <span className="font-mono">{cat.count}</span>
                      </div>
                    ))}
                    <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                      <span className="text-gray-400 text-sm">Affected zones</span>
                      <span className="font-mono text-white font-bold">{affectedZones.size}</span>
                    </div>
                    <div className="flex justify-between items-center pt-1">
                      <span className="text-gray-500 text-xs uppercase tracking-wider">Last updated</span>
                      <span className="font-mono text-gray-300 text-xs">
                        {data.generated_at ? new Date(data.generated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '--:--'}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Map View */}
              <div className="lg:col-span-2 glass-panel p-2 rounded-lg relative min-h-[400px]">
                <div className="absolute top-4 left-4 z-10 bg-gray-900/80 px-3 py-1.5 rounded border border-gray-700 flex items-center gap-2 pointer-events-none">
                  <Map size={14} className="text-cyan-400" />
                  <span className="text-xs uppercase tracking-widest text-cyan-400 font-bold">Network Map</span>
                </div>
                <TrafficMap incidents={incidents} />
              </div>

            </div>

            {/* Bottom Row: Incident Feed & Zone Summary */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              
              {/* Incident Feed */}
              <div className="lg:col-span-2 glass-panel p-6 rounded-lg flex flex-col">
                <h3 className="font-bold text-lg mb-4 text-cyan-400 flex items-center gap-2 uppercase tracking-widest text-xs">
                  <AlertTriangle size={18} /> Live Incidents Feed
                </h3>
                <div className="space-y-4">
                  {incidents.length > 0 ? (
                    incidents.map((incident: any, i: number) => (
                      <div key={i} className="p-4 bg-gray-900/40 border border-gray-800 rounded-lg hover:border-gray-600 transition-colors relative overflow-hidden group">
                        <div className={`absolute left-0 top-0 bottom-0 w-1 ${incident.type?.toLowerCase().includes('accident') ? 'bg-red-500' : 'bg-yellow-500'}`}></div>
                        <div className="flex justify-between items-start mb-2 pl-3">
                          <div>
                            <div className={`text-xs font-bold uppercase tracking-widest ${incident.type?.toLowerCase().includes('accident') ? 'text-red-400' : 'text-yellow-400'}`}>
                              {incident.type || 'Incident'}
                            </div>
                            <div className="text-lg font-bold text-gray-100 mt-1">{extractRoadName(incident.message)}</div>
                          </div>
                          <div className="text-right">
                            <div className="text-[10px] font-mono text-gray-500 px-2 py-1 bg-gray-800 rounded border border-gray-700">
                              {new Date(data.generated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                            </div>
                          </div>
                        </div>
                        <div className="text-sm text-gray-300 pl-3 mb-3 leading-relaxed">
                          {extractDescription(incident.message)}
                        </div>
                        <div className="flex items-center gap-4 pl-3 pt-2 border-t border-gray-800/50">
                          <div className="flex items-center gap-1.5 text-xs text-gray-400 uppercase tracking-wider">
                            <MapPin size={12} />
                            <span>{incident.zone_name || 'Zone unavailable'}</span>
                          </div>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="p-8 flex flex-col items-center justify-center text-center bg-gray-900/20 rounded-lg border border-dashed border-gray-800">
                      <Car size={32} className="text-gray-600 mb-3" />
                      <div className="text-lg font-bold text-gray-400 uppercase tracking-widest mb-1">Traffic Data Unavailable</div>
                      <div className="text-sm text-gray-500 font-mono italic">No live traffic observations are currently available.</div>
                    </div>
                  )}
                </div>
              </div>

              {/* Zone Summary */}
              <div className="glass-panel p-6 rounded-lg flex flex-col">
                <h3 className="font-bold text-lg mb-4 text-cyan-400 flex items-center gap-2 uppercase tracking-widest text-xs">
                  <MapPin size={18} /> Affected Zones
                </h3>
                <div className="space-y-2">
                  {Object.keys(zoneIncidentCounts).length > 0 ? (
                    Object.entries(zoneIncidentCounts)
                      .sort(([, a], [, b]) => b - a)
                      .map(([zone, count]) => (
                      <div key={zone} className="flex justify-between items-center p-3 bg-gray-900/40 rounded border border-gray-800">
                        <span className="text-sm text-gray-300 font-bold uppercase tracking-wider">{zone}</span>
                        <span className={`text-xs font-mono px-2 py-1 rounded ${count > 0 ? 'bg-red-900/30 text-red-400 border border-red-800/50' : 'text-gray-500'}`}>
                          {count > 0 ? `${count} incident${count > 1 ? 's' : ''}` : 'No active incidents'}
                        </span>
                      </div>
                    ))
                  ) : (
                    <div className="text-gray-500 text-sm italic p-4 text-center">No zone data available</div>
                  )}
                </div>
              </div>

            </div>

            {/* Section: TRAFFIC OUTLOOK */}
            <div className="mt-8 mb-2 border-b border-gray-800 pb-2">
              <h3 className="text-sm font-bold text-cyan-400 uppercase tracking-widest">Traffic Outlook</h3>
              <p className="text-xs text-gray-500">What is likely next?</p>
            </div>
            
            {/* Traffic Outlook */}
            <div className="glass-panel p-6 rounded-lg">
              <h3 className="font-bold text-lg mb-4 flex items-center gap-2 text-cyan-400 uppercase tracking-widest text-xs">
                <TrendingUp size={18} />
                <span>Traffic Outlook</span>
              </h3>
              
              <div className="mb-6 p-4 bg-gray-900/40 rounded border border-gray-800">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">

                  <div className="flex items-center gap-2">
                    <TrendingUp size={16} className="text-cyan-400" />
                    <div>
                      <div className="text-xs text-gray-500 uppercase tracking-wider">Horizon</div>
                      <div className="text-sm font-bold text-white">
                        {data?.prediction_horizon_minutes ? `${data.prediction_horizon_minutes} minutes` : '10 minutes'}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <AlertCircle size={16} className="text-yellow-400" />
                    <div>
                      <div className="text-xs text-gray-500 uppercase tracking-wider">Status</div>
                      <div className="text-sm font-bold text-yellow-400">Demo Mode</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Info size={16} className="text-gray-500" />
                    <div>
                      <div className="text-xs text-gray-500 uppercase tracking-wider">Geo-Mapping</div>
                      <div className="text-sm font-bold text-gray-400">Unavailable</div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="space-y-3">
                {data?.zones && data.zones.length > 0 ? (
                  data.zones
                    .slice()
                    .sort((a: any, b: any) => a.zone_id.localeCompare(b.zone_id))
                    .map((zone: any) => (
                      <div key={zone.zone_id} className="p-4 bg-gray-900/40 border border-gray-800 rounded-lg">
                        <div className="flex justify-between items-start mb-3">
                          <div>
                            <div className="text-sm font-bold text-gray-100 uppercase tracking-wider">{zone.zone_name}</div>
                            <div className="text-xs text-gray-500">{zone.zone_id}</div>
                          </div>
                          <span className={`text-xs font-mono px-2 py-1 rounded ${zone.is_demo_zone ? 'bg-yellow-900/30 text-yellow-400 border border-yellow-800/50' : 'bg-green-900/30 text-green-400 border border-green-800/50'}`}>
                            {zone.is_demo_zone ? 'DEMO ZONE' : 'LIVE'}
                          </span>
                        </div>
                        
                        {zone.is_demo_zone ? (
                          <div className="p-6 bg-gray-900/40 rounded border border-dashed border-gray-700 flex flex-col items-center justify-center min-h-[120px]">
                            <div className="flex items-center gap-2 text-gray-400 mb-2">
                              <AlertCircle size={18} />
                              <span className="font-bold tracking-widest text-sm uppercase">Forecast Unavailable</span>
                            </div>
                            <div className="text-xs text-gray-500 text-center max-w-sm">
                              Current forecast data is not geographically mapped to verified UrbanOS zones.
                            </div>
                          </div>
                        ) : (
                          zone.predicted_average_speed !== null && zone.predicted_average_speed !== undefined ? (
                            <div className="grid grid-cols-3 gap-4">
                              <div className="text-center p-3 bg-gray-900/20 rounded border border-gray-800">
                                <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Current Speed</div>
                                <div className={`text-xl font-bold ${zone.current_average_speed !== null ? (zone.current_average_speed >= 50 ? 'text-green-400' : zone.current_average_speed >= 30 ? 'text-yellow-400' : 'text-red-400') : 'text-gray-500'}`}>
                                  {zone.current_average_speed !== null ? `${zone.current_average_speed.toFixed(1)} km/h` : '--'}
                                </div>
                              </div>
                              <div className="text-center p-3 bg-gray-900/20 rounded border border-gray-800">
                                <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Predicted Speed</div>
                                <div className={`text-xl font-bold ${zone.predicted_average_speed !== null ? (zone.predicted_average_speed >= 50 ? 'text-green-400' : zone.predicted_average_speed >= 30 ? 'text-yellow-400' : 'text-red-400') : 'text-gray-500'}`}>
                                  {zone.predicted_average_speed !== null ? `${zone.predicted_average_speed.toFixed(1)} km/h` : '--'}
                                </div>
                              </div>
                              <div className="text-center p-3 bg-gray-900/20 rounded border border-gray-800">
                                <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Change</div>
                                <div className={`text-xl font-bold ${zone.speed_change !== null && zone.speed_change !== undefined ? (zone.speed_change > 0 ? 'text-green-400' : zone.speed_change < 0 ? 'text-red-400' : 'text-gray-400') : 'text-gray-500'}`}>
                                  {zone.speed_change !== null && zone.speed_change !== undefined ? `${zone.speed_change > 0 ? '+' : ''}${zone.speed_change.toFixed(1)} km/h` : '--'}
                                </div>
                              </div>
                            </div>
                          ) : (
                            <div className="p-4 bg-gray-900/20 rounded border border-dashed border-gray-800 text-center">
                              <div className="text-gray-500 text-sm">No valid prediction data</div>
                            </div>
                          )
                        )}
                      </div>
                    ))
                ) : (
                  <div className="text-gray-500 text-sm italic p-4 text-center">No zone forecast data available</div>
                )}
              </div>
            </div>

          </div>
        )}
      </div>
    </div>
  );
}
