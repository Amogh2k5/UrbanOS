/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useEffect, useState } from 'react';
import { fetchTrafficReport, fetchTrafficPrediction, type TrafficPredictionResponse, type TrafficDivisionForecast } from '@/services/api';
import { Car, TrendingUp } from 'lucide-react';
import TrafficMap from './TrafficMap';

const DIVISION_ORDER = [
  'Central',
  'East',
  'North',
  'North-East',
  'West',
];

const DIVISION_CODE_TO_NAME: Record<string, string> = {
  'Central': 'Central',
  'East': 'East',
  'North': 'North',
  'North-East': 'North-East',
  'West': 'West',
};

function formatDivisionName(id: string) {
  return id;
}

function getCongestionColor(level: string) {
  switch ((level || '').toLowerCase()) {
    case 'free_flow': return 'text-green-400';
    case 'moderate': return 'text-yellow-400';
    case 'heavy': return 'text-orange-400';
    case 'severe': return 'text-red-400';
    default: return 'text-gray-400';
  }
}

function getCongestionLabel(level: string) {
  return (level || 'unknown').replace('_', ' ');
}

export default function TrafficPage() {
  // LIVE lifecycle: independent of Forecast
  const [liveData, setLiveData] = useState<any | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [liveLoading, setLiveLoading] = useState(true);

  // FORECAST lifecycle: independent of Live
  const [prediction, setPrediction] = useState<TrafficPredictionResponse | null>(null);
  const [forecastError, setForecastError] = useState<string | null>(null);
  const [forecastLoading, setForecastLoading] = useState(true);

  const [selectedIncident, setSelectedIncident] = useState<any | null>(null);

  // LIVE effect: serialized polling loop — at most ONE live request
  // in flight at any time. The next poll is scheduled ONLY after the current
  // request fully settles (success or failure); no setInterval that could
  // fire while a request is still running. Cleanup stops any pending timer
  // and blocks late state updates (Strict Mode safe).
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const runOnce = async () => {
      try {
        const res = await fetchTrafficReport();
        if (cancelled) return;
        setLiveData(res);
        setLiveError(null);
      } catch (err: any) {
        if (cancelled) return;
        setLiveError(err.message);
      } finally {
        if (cancelled) return;
        // A failed refresh must not erase the last successful live data
        // (we never clear `liveData` here; skeletons only render when
        // there is no live data at all).
        setLiveLoading(false);
        // Schedule the next refresh only after this request has completed.
        timer = setTimeout(runOnce, 30000);
      }
    };

    runOnce();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  // FORECAST effect: serialized polling loop — at most ONE prediction request
  // in flight at any time. The next poll is scheduled ONLY after the current
  // request fully settles (success or failure); there is no setInterval that
  // could fire while a request is still running. Cleanup stops any pending
  // timer and blocks late state updates (Strict Mode safe).
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const runOnce = async () => {
      try {
        const res = await fetchTrafficPrediction();
        if (cancelled) return;
        setPrediction(res);
        setForecastError(null);
      } catch (err: any) {
        if (cancelled) return;
        setForecastError(err.message);
      } finally {
        if (cancelled) return;
        // A failed refresh must not erase the last successful prediction
        // (we never clear `prediction` here, and skeletons only render when
        // there is no prediction data at all).
        setForecastLoading(false);
        // Schedule the next refresh only after this request has completed.
        timer = setTimeout(runOnce, 60000);
      }
    };

    runOnce();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  const incidents = liveData?.incidents || [];
  const activeIncidentsCount = incidents.length;

  const overallCongestion = liveData?.overall_congestion_level || 'unknown';
  const currentAvgSpeed = liveData?.overall_average_speed ?? null;

  const divisions = prediction?.divisions || [];
  const divisionMap = new Map(divisions.map((d) => [d.division, d]));
  const orderedDivisions = DIVISION_ORDER.map((code) => {
    const name = DIVISION_CODE_TO_NAME[code];
    return name ? divisionMap.get(name) : undefined;
  }).filter(Boolean) as TrafficDivisionForecast[];

  const handleIncidentClick = (incident: any | null) => {
    setSelectedIncident(incident);
  };

  return (
    <div className="h-full bg-[var(--color-background)] text-[var(--color-foreground)] p-4 md:p-6 lg:p-8 flex flex-col font-sans">
      <div className="flex flex-col flex-grow min-h-0 overflow-y-auto custom-scrollbar">
        {/* Header */}
        <div className="mb-6 flex items-center gap-3">
          <Car size={24} className="text-[var(--color-primary)]" />
          <h2 className="text-2xl font-heading text-[var(--color-primary)]">Traffic Intelligence</h2>
        </div>

        {/* Compact KPI Row — driven ONLY by the Live request */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div className="glass-panel p-4 rounded-lg border border-gray-800">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Current Avg Speed</div>
            <div className="text-2xl font-bold text-white">{currentAvgSpeed !== null ? `${currentAvgSpeed.toFixed(1)} km/h` : '--'}</div>
          </div>
          <div className="glass-panel p-4 rounded-lg border border-gray-800">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Congestion</div>
            <div className={`text-xl font-bold uppercase ${getCongestionColor(overallCongestion)}`}>{getCongestionLabel(overallCongestion)}</div>
          </div>
          <div className="glass-panel p-4 rounded-lg border border-gray-800">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Live Incidents</div>
            <div className="text-2xl font-bold text-white">{activeIncidentsCount}</div>
          </div>
<div className="glass-panel p-4 rounded-lg border border-gray-800">
             <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Next 5‑min Forecast</div>
             <div className="flex items-center gap-2 text-lg font-bold text-white">
               {forecastLoading && !prediction ? (
                 <span className="text-gray-500">…</span>
               ) : prediction ? (
                 <span className="text-green-400">Forecast</span>
               ) : (
                 <span className="text-yellow-400">Unavailable</span>
               )}
             </div>
           </div>
        </div>

        {/* Live-scoped status: loading/error NEVER affects Forecast */}
        {liveLoading && !liveData && (
          <div className="mb-4 text-sm text-gray-500 font-mono">Loading live traffic…</div>
        )}
        {liveError && (
          <div className="mb-4 glass-panel p-3 rounded-lg border border-red-500/30 text-red-500 text-sm">
            Live traffic data: {liveError}
            {liveData ? ' — showing last successful data' : ''}
          </div>
        )}

        {/* Full-width Map */}
        <div className="mb-6 flex-1 min-h-[500px] glass-panel p-2 rounded-xl overflow-hidden border border-gray-800 relative">
          <TrafficMap
            incidents={incidents}
            onIncidentClick={handleIncidentClick}
            selectedIncident={selectedIncident}
          />
        </div>

        {/* Forecast Section — driven ONLY by the Forecast request */}
        <section className="mb-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-bold text-cyan-400 flex items-center gap-2 uppercase tracking-widest text-xs">
              <TrendingUp size={18} />
              <span>Traffic Forecast – Next 5 min</span>
            </h3>
            {prediction && (
              <div className="text-xs text-gray-500 font-mono">
                Target: {new Date(prediction.target_timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </div>
            )}
          </div>

          {forecastLoading && !prediction ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="glass-panel p-4 rounded-lg border border-gray-800 animate-pulse">
                  <div className="h-4 bg-gray-700 rounded w-3/4 mb-2"></div>
                  <div className="h-6 bg-gray-700 rounded w-1/2"></div>
                </div>
              ))}
            </div>
          ) : !prediction?.divisions?.length ? (
            <div className="glass-panel p-6 rounded-lg border border-gray-800 text-center text-gray-500">
              {forecastError ? `Forecast unavailable: ${forecastError}` : 'No forecast data'}
            </div>
          ) : (
            <>
              {forecastError && (
                <div className="mb-4 glass-panel p-3 rounded-lg border border-red-500/30 text-red-500 text-sm">
                  Forecast refresh failed: {forecastError} — showing last successful forecast
                </div>
              )}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {orderedDivisions.map((div) => (
                  <div
                    key={div.division}
                    className="glass-panel p-4 rounded-lg border border-gray-800 hover:border-gray-600 transition-colors"
                  >
                    <div className="font-bold text-white text-sm uppercase tracking-wider mb-2">
                      {formatDivisionName(div.division)}
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div className="text-gray-500">Current</div>
                      <div className="font-mono text-white text-right">
                        {div.current_avg_speed !== null ? `${div.current_avg_speed.toFixed(1)} km/h` : '--'}
                      </div>
                      <div className="text-gray-500">Predicted</div>
                      <div className="font-mono text-white text-right">
                        {div.predicted_avg_speed !== null ? `${div.predicted_avg_speed.toFixed(1)} km/h` : '--'}
                      </div>
                      <div className="text-gray-500">Change</div>
                      <div className={`font-mono text-right ${div.speed_change !== null && div.speed_change !== undefined ? (div.speed_change > 0 ? 'text-green-400' : div.speed_change < 0 ? 'text-red-400' : 'text-gray-400') : 'text-gray-500'}`}>
                        {div.speed_change !== null && div.speed_change !== undefined ? `${div.speed_change > 0 ? '+' : ''}${div.speed_change.toFixed(1)} km/h` : '--'}
                      </div>
                      <div className="text-gray-500">Status</div>
                      <div className={`font-mono text-right ${getCongestionColor(div.congestion_level)}`}>
                        {getCongestionLabel(div.congestion_level)}
                      </div>
                    </div>
                    <div className="mt-3 pt-2 border-t border-gray-800 text-[10px] text-gray-500 uppercase tracking-wider">
                      {div.segment_count} segments
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
