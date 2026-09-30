"use client";

import { useEffect, useState } from 'react';
import { fetchFloodReport } from '@/services/api';

import { Waves, AlertTriangle, History, CloudRain, ShieldAlert, Wind, Info, Target, Calendar } from 'lucide-react';

interface FloodAlert {
  alert_id?: string;
  location?: string;
  zone_name?: string;
  severity?: string;
  message?: string;
  issued_at?: string;
  source?: string;
  is_live?: boolean;
}

interface HistoricalEvent {
  event_id: string;
  date_start?: string;
  location?: string;
  region?: string;
  primary_cause?: string;
  rainfall_mm?: number;
  flood_depth_mm?: string | number;
  damage?: string;
}

interface RegionRainfall {
  available: boolean;
  source: string;
  max_1h_mm?: number;
  max_3h_mm?: number;
  max_6h_mm?: number;
  max_24h_mm?: number;
  max_15m_mm?: number;
  peak_5m_mm?: number;
  stations_reporting?: number;
  stations_with_rain?: number;
  weather_systems?: unknown[];
}

interface RegionalWeather {
  singapore_forecast_code?: string;
  singapore_forecast_text?: string;
  singapore_wind_direction?: string;
  singapore_temperature_high?: number;
  singapore_temperature_low?: number;
  malaysia_available?: boolean;
  sumatra_available?: boolean;
  regional_systems?: unknown[];
}

interface FloodReport {
  risk_level?: string;
  confidence?: string;
  primary_risk_factors?: string[];
  active_alerts?: FloodAlert[];
  singapore_rainfall?: RegionRainfall;
  malaysia_rainfall?: RegionRainfall;
  sumatra_rainfall?: RegionRainfall;
  regional_weather?: RegionalWeather;
  past_flood_events?: HistoricalEvent[];
  data_sources?: string[];
  recommendations?: string[];
  limitations?: string[];
}

export default function FloodPage() {
  const [data, setData] = useState<FloodReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadData = async () => {
      try {
        const result = await fetchFloodReport();
        setData(result);
        setError(null);
      } catch (err: unknown) {
        if (err instanceof Error) {
          setError(err.message);
        } else {
          setError(String(err));
        }
      }
    };
    loadData();
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, []);

  const getRiskColor = (risk?: string) => {
    switch (risk?.toUpperCase()) {
      case 'CRITICAL': return 'text-red-500 bg-red-900/20 border-red-900';
      case 'HIGH': return 'text-orange-500 bg-orange-900/20 border-orange-900';
      case 'MODERATE': return 'text-yellow-400 bg-yellow-900/20 border-yellow-800';
      case 'LOW': return 'text-blue-400 bg-blue-900/20 border-blue-800';
      case 'UNKNOWN': return 'text-gray-400 bg-gray-900/50 border-gray-700';
      default: return 'text-gray-400 bg-gray-900/10 border-gray-800';
    }
  };

  const getAlertColor = (severity?: string) => {
    switch (severity?.toUpperCase()) {
      case 'CRITICAL': return 'text-red-400 border-red-900/50 bg-red-900/10';
      case 'HIGH': return 'text-orange-400 border-orange-900/50 bg-orange-900/10';
      case 'MODERATE': return 'text-yellow-400 border-yellow-900/50 bg-yellow-900/10';
      default: return 'text-blue-400 border-blue-900/50 bg-blue-900/10';
    }
  };

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const formatSourceBadge = (source: string) => {
    const s = source.toLowerCase();
    if (s.includes('offline_fixture')) {
      return <span className="px-2 py-1 bg-purple-900/50 text-purple-300 border border-purple-700 rounded text-xs tracking-wider uppercase">OFFLINE FIXTURE</span>;
    }
    if (s.includes('historical')) {
      return <span className="px-2 py-1 bg-yellow-900/50 text-yellow-300 border border-yellow-700 rounded text-xs tracking-wider uppercase">HISTORICAL</span>;
    }
    if (s.includes('unavailable') || s.includes('none') || s.includes('error')) {
      return <span className="px-2 py-1 bg-gray-800 text-gray-400 border border-gray-700 rounded text-xs tracking-wider uppercase">UNAVAILABLE</span>;
    }
    return <span className="px-2 py-1 bg-green-900/50 text-green-300 border border-green-700 rounded text-xs tracking-wider uppercase">LIVE</span>;
  };

  const isValidDate = (dateString?: string) => {
    if (!dateString) return false;
    const d = new Date(dateString);
    return !isNaN(d.getTime());
  };

  if (error) {
    return (
      <div className="h-full bg-[var(--color-background)] text-[var(--color-foreground)] p-4 md:p-6 lg:p-8 flex flex-col font-sans">
        
        <div className="text-red-500 mb-4 glass-panel p-4 rounded-lg border-l-4 border-red-500">{error}</div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="h-full bg-[var(--color-background)] text-[var(--color-foreground)] p-4 md:p-6 lg:p-8 flex flex-col font-sans">
        
        <div className="flex items-center justify-center h-64 text-gray-500 font-mono animate-pulse">Loading Flood Intelligence...</div>
      </div>
    );
  }

  const confidence = data.confidence || 'UNKNOWN';
  const activeAlertCount = data.active_alerts?.length ?? 0;

  return (
    <div className="h-full bg-[var(--color-background)] text-[var(--color-foreground)] p-4 md:p-6 lg:p-8 flex flex-col font-sans">
      
      <div className="flex flex-col flex-grow min-h-0 overflow-y-auto custom-scrollbar gap-6 pb-8">
        
        <h2 className="text-2xl font-heading text-[var(--color-primary)] flex items-center gap-3">
          <Waves size={24} />
          Rain & Flood Intelligence Dashboard
        </h2>
        
        {/* ROW 1: RISK & WHY THIS RISK */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
          {/* Current Risk */}
          <div className={`p-6 rounded-lg border-l-4 ${getRiskColor(data.risk_level).replace('text', 'border')}`}>
            <h3 className="font-bold text-lg mb-4 text-gray-300 uppercase tracking-widest text-xs flex items-center gap-2">
              <ShieldAlert size={16} />
              Current Flood Risk
            </h3>
            <div className="text-4xl font-black mb-2 tracking-wider uppercase" style={{ color: 'inherit' }}>
              {data.risk_level || 'UNKNOWN'}
            </div>
            <div className="text-gray-400 font-mono text-sm mt-4 flex justify-between items-center bg-gray-900/50 p-3 rounded">
              <span>Alerts: <span className="text-white font-bold ml-1">{activeAlertCount}</span></span>
              <span>Confidence: <span className="text-cyan-400 font-bold ml-1 uppercase">{confidence}</span></span>
            </div>
          </div>

          {/* Why This Risk? */}
          <div className="glass-panel p-6 rounded-lg md:col-span-2 border-l-4 border-cyan-800">
            <h3 className="font-bold text-lg mb-4 text-cyan-400 flex items-center gap-2 uppercase tracking-widest text-xs">
              <Target size={16} /> Why This Risk?
            </h3>
            {data.primary_risk_factors && data.primary_risk_factors.length > 0 ? (
              <ul className="space-y-3">
                {data.primary_risk_factors.map((factor, i) => (
                  <li key={i} className="flex gap-3 text-sm text-gray-200">
                    <span className="text-cyan-500 flex-shrink-0 mt-0.5">&bull;</span>
                    <span className="font-semibold tracking-wide">{factor}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-gray-500 italic text-sm">No specific risk factors provided by backend.</div>
            )}
          </div>
        </div>

        {/* ROW 2: CURRENT REGIONAL RAINFALL & WEATHER */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
          {/* SINGAPORE (PRIMARY) */}
          <div className="glass-panel p-6 rounded-lg border-l-4 border-indigo-800">
            <h3 className="font-bold text-lg mb-4 text-indigo-400 flex items-center justify-between uppercase tracking-widest text-xs">
              <span className="flex items-center gap-2"><CloudRain size={16} /> Singapore</span>
              <span className="px-2 py-1 bg-indigo-900/50 text-indigo-300 border border-indigo-700 rounded text-[10px] tracking-wider font-bold">PRIMARY</span>
            </h3>
            {data.singapore_rainfall?.available ? (
              <div className="space-y-4">
                <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
                  {data.singapore_rainfall.peak_5m_mm !== undefined && (
                    <div className="p-2 bg-gray-900/40 rounded border border-gray-800">
                      <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Peak 5m</div>
                      <div className="font-mono text-lg text-white">{data.singapore_rainfall.peak_5m_mm.toFixed(1)} <span className="text-xs text-gray-500">mm</span></div>
                    </div>
                  )}
                  {data.singapore_rainfall.max_15m_mm !== undefined && (
                    <div className="p-2 bg-gray-900/40 rounded border border-gray-800">
                      <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Max 15m</div>
                      <div className="font-mono text-lg text-white">{data.singapore_rainfall.max_15m_mm.toFixed(1)} <span className="text-xs text-gray-500">mm</span></div>
                    </div>
                  )}
                  {data.singapore_rainfall.max_1h_mm !== undefined && (
                    <div className="p-2 bg-gray-900/40 rounded border border-gray-800">
                      <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Max 1h</div>
                      <div className="font-mono text-lg text-white">{data.singapore_rainfall.max_1h_mm.toFixed(1)} <span className="text-xs text-gray-500">mm</span></div>
                    </div>
                  )}
                  {data.singapore_rainfall.max_3h_mm !== undefined && (
                    <div className="p-2 bg-gray-900/40 rounded border border-gray-800">
                      <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Max 3h</div>
                      <div className="font-mono text-lg text-white">{data.singapore_rainfall.max_3h_mm.toFixed(1)} <span className="text-xs text-gray-500">mm</span></div>
                    </div>
                  )}
                  {data.singapore_rainfall.max_6h_mm !== undefined && (
                    <div className="p-2 bg-gray-900/40 rounded border border-gray-800">
                      <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Max 6h</div>
                      <div className="font-mono text-lg text-white">{data.singapore_rainfall.max_6h_mm.toFixed(1)} <span className="text-xs text-gray-500">mm</span></div>
                    </div>
                  )}
                  {data.singapore_rainfall.max_24h_mm !== undefined && (
                    <div className="p-2 bg-gray-900/40 rounded border border-gray-800">
                      <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Max 24h</div>
                      <div className="font-mono text-lg text-white">{data.singapore_rainfall.max_24h_mm.toFixed(1)} <span className="text-xs text-gray-500">mm</span></div>
                    </div>
                  )}
                </div>
                <div className="flex justify-between items-center text-xs text-gray-400">
                  <span>Stations with Rain: <span className="text-cyan-400 font-mono">{data.singapore_rainfall.stations_with_rain ?? 0}</span> / {data.singapore_rainfall.stations_reporting ?? 0}</span>
                </div>
                {data.regional_weather && (
                  <div className="pt-3 border-t border-gray-800/50 flex justify-between items-center">
                    <span className="text-xs text-gray-400 flex items-center gap-1"><Wind size={12} /> {data.regional_weather.singapore_forecast_text || 'Unknown'}</span>
                    <span className="text-xs font-mono text-gray-500">{data.regional_weather.singapore_temperature_low}-{data.regional_weather.singapore_temperature_high}&deg;C</span>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-gray-500 font-mono italic p-6 bg-gray-900/20 rounded border border-dashed border-gray-800 text-sm text-center">
                UNAVAILABLE
              </div>
            )}
          </div>

          {/* NEA 24-Hour Forecast */}
          {data.regional_weather?.singapore_forecast_text && (
            <div className="glass-panel p-4 rounded-lg border border-amber-500/30 bg-amber-900/10">
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-bold text-sm text-amber-400 flex items-center gap-2 uppercase tracking-widest text-xs">
                  <Calendar size={14} />
                  <span>NEA 24-Hour Forecast</span>
                </h3>
                <span className="px-2 py-1 bg-amber-900/30 text-amber-300 border border-amber-700 rounded text-[10px] tracking-wider font-bold">FORECAST</span>
              </div>
              <div className="text-base font-medium text-amber-200 bg-amber-900/20 p-3 rounded border border-amber-700/50">
                {data.regional_weather.singapore_forecast_text}
              </div>
              <div className="text-[10px] text-amber-500 mt-2 text-center">
                <span className="font-bold">24-Hour Forecast</span> — Not Current Rainfall
              </div>
            </div>
          )}

          {/* MALAYSIA / JOHOR (SUPPORTING) */}
          <div className="glass-panel p-6 rounded-lg border-l-4 border-blue-800">
            <h3 className="font-bold text-lg mb-4 text-blue-400 flex items-center justify-between uppercase tracking-widest text-xs">
              <span className="flex items-center gap-2"><CloudRain size={16} /> Malaysia / Johor</span>
              <span className="px-2 py-1 bg-blue-900/50 text-blue-300 border border-blue-700 rounded text-[10px] tracking-wider font-bold">SUPPORTING</span>
            </h3>
            {data.malaysia_rainfall?.available ? (
              <div className="space-y-4">
                <div className="p-3 bg-gray-900/40 rounded border border-gray-800">
                  <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Max 1h</div>
                  <div className="font-mono text-2xl text-white">{data.malaysia_rainfall.max_1h_mm?.toFixed(1) ?? '0.0'} <span className="text-xs text-gray-500">mm</span></div>
                </div>
                <div className="text-xs text-gray-400 font-mono">
                  Stations reporting: {data.malaysia_rainfall.stations_reporting ?? 0}
                </div>
              </div>
) : (
              <div className="text-gray-500 font-mono italic p-6 bg-gray-900/20 rounded border border-dashed border-gray-800 text-sm text-center">
                Rainfall data unavailable
              </div>
            )}
          </div>

          {/* SUMATRA (SUPPORTING) */}
          <div className="glass-panel p-6 rounded-lg border-l-4 border-blue-800">
            <h3 className="font-bold text-lg mb-4 text-blue-400 flex items-center justify-between uppercase tracking-widest text-xs">
              <span className="flex items-center gap-2"><CloudRain size={16} /> Sumatra</span>
              <span className="px-2 py-1 bg-blue-900/50 text-blue-300 border border-blue-700 rounded text-[10px] tracking-wider font-bold">SUPPORTING</span>
            </h3>
            {data.sumatra_rainfall?.available ? (
              <div className="space-y-4">
                <div className="p-3 bg-gray-900/40 rounded border border-gray-800">
                  <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Max 1h</div>
                  <div className="font-mono text-2xl text-white">{data.sumatra_rainfall.max_1h_mm?.toFixed(1) ?? '0.0'} <span className="text-xs text-gray-500">mm</span></div>
                </div>
                <div className="text-xs text-gray-400 font-mono">
                  Stations reporting: {data.sumatra_rainfall.stations_reporting ?? 0}
                </div>
              </div>
            ) : (
              <div className="text-gray-500 font-mono italic p-6 bg-gray-900/20 rounded border border-dashed border-gray-800 text-sm text-center">
                UNAVAILABLE
              </div>
            )}
          </div>
        </div>

        {/* ROW 3: ALERTS */}
        <div className="glass-panel p-6 rounded-lg">
          <h3 className="font-bold text-lg mb-4 text-cyan-400 flex items-center gap-2 uppercase tracking-widest text-xs">
            <AlertTriangle size={16} /> Active Official Alerts
          </h3>
          {data.active_alerts && data.active_alerts.length > 0 ? (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {data.active_alerts.map((alert, i) => {
                const isLive = alert.is_live === true || alert.source?.includes('live_api');
                
                return (
                  <div key={alert.alert_id || i} className={`p-4 border rounded-lg ${getAlertColor(alert.severity)}`}>
                    <div className="flex justify-between items-start mb-2">
                      <div className="font-bold tracking-wide uppercase text-sm">
                        {alert.location || alert.zone_name || 'Unknown Location'}
                      </div>
                      {!isLive ? (
                        <span className="px-2 py-1 bg-red-950 text-red-400 border border-red-800 font-mono text-[10px] tracking-wider rounded uppercase flex-shrink-0 ml-2">
                          OFFLINE DEMONSTRATION DATA
                        </span>
                      ) : (
                        <span className="px-2 py-1 bg-green-950 text-green-400 border border-green-800 font-mono text-[10px] tracking-wider rounded uppercase flex-shrink-0 ml-2">
                          LIVE OFFICIAL ALERT
                        </span>
                      )}
                    </div>
                    <div className="text-sm text-gray-200 mb-4 bg-black/20 p-2 rounded">{alert.message}</div>
                    <div className="flex justify-between items-center text-xs opacity-70 font-mono">
                      <span className="uppercase font-bold tracking-wider">Severity: {alert.severity || 'Unknown'}</span>
                      <span>{isValidDate(alert.issued_at) ? new Date(alert.issued_at!).toLocaleString() : 'Time unavailable'}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center p-8 bg-gray-900/20 rounded border border-dashed border-gray-800">
              <ShieldAlert size={32} className="text-gray-600 mb-2" />
              <div className="text-gray-400 font-mono text-sm">No active official flood alerts.</div>
            </div>
          )}
        </div>

        {/* ROW 4: RECOMMENDATIONS */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Recommendations */}
          <div className="glass-panel p-6 rounded-lg border-t-4 border-cyan-800">
            <h3 className="font-bold text-lg mb-4 text-cyan-400 flex items-center gap-2 uppercase tracking-widest text-xs">
              <Info size={16} /> Recommendations
            </h3>
            {data.recommendations && data.recommendations.length > 0 ? (
              <ul className="space-y-3">
                {data.recommendations.map((rec, i) => (
                  <li key={i} className="flex gap-3 text-sm text-gray-300">
                    <span className="text-cyan-500 flex-shrink-0 mt-0.5">&bull;</span>
                    <span>{rec}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-gray-500 italic text-sm">No specific recommendations at this time.</div>
            )}
          </div>

          {/* ROW 5: PAST EVENTS */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 opacity-90">
          
          {/* Past Flood Events */}
          <div className="glass-panel p-6 rounded-lg lg:col-span-2">
            <div className="mb-6">
              <h3 className="font-bold text-lg text-gray-400 flex items-center gap-2 uppercase tracking-widest text-xs">
                <History size={16} /> Past Flood Events
              </h3>
              <p className="text-[11px] text-gray-500 mt-1 uppercase tracking-widest font-mono">
                Reference only &mdash; does not determine current flood risk
              </p>
            </div>
            
            {data.past_flood_events && data.past_flood_events.length > 0 ? (
              <div className="space-y-4">
                {data.past_flood_events.slice(0, 5).map((hist, i) => (
                  <div key={hist.event_id || i} className="p-4 border border-gray-800 bg-gray-900/30 rounded-lg">
                    <div className="flex justify-between items-start mb-2">
                      <div className="font-bold text-gray-300">{hist.date_start} &mdash; {hist.location}</div>
                      <div className="text-[10px] px-2 py-0.5 bg-gray-800 text-gray-400 rounded uppercase tracking-wider">{hist.region}</div>
                    </div>
                    
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mt-3">
                      {hist.primary_cause && (
                        <div className="text-xs">
                          <span className="text-gray-600 block uppercase tracking-wider mb-1 text-[10px]">Primary Cause</span>
                          <span className="text-gray-400 capitalize">{hist.primary_cause.replace(/_/g, ' ')}</span>
                        </div>
                      )}
                      {hist.rainfall_mm !== undefined && hist.rainfall_mm !== null && (
                        <div className="text-xs">
                          <span className="text-gray-600 block uppercase tracking-wider mb-1 text-[10px]">Rainfall</span>
                          <span className="text-gray-300 font-mono">{hist.rainfall_mm} mm</span>
                        </div>
                      )}
                      {hist.flood_depth_mm !== undefined && hist.flood_depth_mm !== null && hist.flood_depth_mm !== 'nan' && (
                        <div className="text-xs">
                          <span className="text-gray-600 block uppercase tracking-wider mb-1 text-[10px]">Flood Depth</span>
                          <span className="text-gray-300 font-mono">{hist.flood_depth_mm} mm</span>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
                {data.past_flood_events.length > 5 && (
                  <button className="w-full mt-4 p-3 border border-gray-700 bg-gray-900/50 text-gray-300 rounded hover:bg-gray-800 transition-colors uppercase tracking-widest text-xs font-bold" onClick={() => alert('Full catalogue opens here (To be implemented)')}>
                    View All {data.past_flood_events.length} Past Flood Events
                  </button>
                )}
              </div>
            ) : (
              <div className="text-gray-500 font-mono italic p-4 bg-gray-900/30 rounded border border-gray-800 text-sm text-center">
                No relevant historical events match current conditions.
              </div>
            )}
</div>
           
        </div>
      </div>
    </div>
    </div>
  );
}
