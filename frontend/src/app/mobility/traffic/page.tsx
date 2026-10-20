/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useEffect, useState } from 'react';
import { fetchTrafficReport, fetchTrafficPrediction, type TrafficPredictionResponse, type TrafficDivisionForecast } from '@/services/api';
import { Car, TrendingUp } from 'lucide-react';
import TrafficMap from './TrafficMap';
import { domainCardClass } from '@/components/city/presentation';
import { formatSingaporeTime } from "@/services/time";

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
    case 'free_flow': return 'text-emerald-100'; // on solid card
    case 'moderate': return 'text-amber-100'; // on solid card
    case 'heavy': return 'text-orange-100'; // on solid card
    case 'severe': return 'text-red-100'; // on solid card
    default: return 'text-white/90';
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
          <div className={`${domainCardClass("traffic", "p-4 rounded-lg shadow-sm")}`}>
            <div className="text-xs text-white/90 uppercase tracking-wider mb-1">Current Avg Speed</div>
            <div className="text-2xl font-bold text-white">{currentAvgSpeed !== null ? `${currentAvgSpeed.toFixed(1)} km/h` : '--'}</div>
          </div>
          <div className={`${domainCardClass("traffic", "p-4 rounded-lg shadow-sm")}`}>
            <div className="text-xs text-white/90 uppercase tracking-wider mb-1">Congestion</div>
            <div className={`text-xl font-bold uppercase ${getCongestionColor(overallCongestion)}`}>{getCongestionLabel(overallCongestion)}</div>
          </div>
          <div className={`${domainCardClass("traffic", "p-4 rounded-lg shadow-sm")}`}>
            <div className="text-xs text-white/90 uppercase tracking-wider mb-1">Live Incidents</div>
            <div className="text-2xl font-bold text-white">{activeIncidentsCount}</div>
          </div>
<div className={`${domainCardClass("traffic", "p-4 rounded-lg shadow-sm")}`}>
             <div className="text-xs text-white/90 uppercase tracking-wider mb-1">Next 5‑min Forecast</div>
             <div className="flex items-center gap-2 text-lg font-bold text-white">
               {forecastLoading && !prediction ? (
                 <span className="text-white/90">…</span>
               ) : prediction ? (
                 <span className="text-white">Forecast</span>
               ) : (
                 <span className="text-white/90">Unavailable</span>
               )}
             </div>
           </div>
        </div>

        {/* Live-scoped status: loading/error NEVER affects Forecast */}
        {liveLoading && !liveData && (
          <div className="mb-4 text-sm text-slate-500 font-mono">Loading live traffic…</div>
        )}
        {liveError && (
          <div className="mb-4 glass-panel p-3 rounded-lg border border-red-500/30 text-red-500 text-sm">
            Live traffic data: {liveError}
            {liveData ? ' — showing last successful data' : ''}
          </div>
        )}

        {/* Full-width Map */}
        <div className="mb-6 flex-1 min-h-[500px] glass-panel p-2 rounded-xl overflow-hidden border border-slate-200 relative">
          <TrafficMap
            incidents={incidents}
            onIncidentClick={handleIncidentClick}
            selectedIncident={selectedIncident}
          />
        </div>

        {/* Forecast Section — driven ONLY by the Forecast request */}
        <section className="mb-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-bold text-cyan-700 flex items-center gap-2 uppercase tracking-widest text-xs">
              <TrendingUp size={18} />
              <span>Traffic Forecast – Next 5 min</span>
            </h3>
            {prediction && (
              <div className="text-xs text-slate-500 font-mono">
                Target: {formatSingaporeTime(prediction.target_timestamp)} SGT
              </div>
            )}
          </div>

          {forecastLoading && !prediction ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[...Array(5)].map((_, i) => (
                <div key={i} className={`${domainCardClass("traffic", "p-4 rounded-lg shadow-sm")} animate-pulse`}>
                  <div className="h-4 bg-slate-200 rounded w-3/4 mb-2"></div>
                  <div className="h-6 bg-slate-200 rounded w-1/2"></div>
                </div>
              ))}
            </div>
          ) : !prediction?.divisions?.length ? (
            <div className="glass-panel p-6 rounded-lg border border-slate-200 text-center text-slate-500">
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
                    className={`${domainCardClass("traffic", "p-4 rounded-lg shadow-sm")} hover:shadow-md transition-shadow`}
                  >
                    <div className="font-bold text-white text-sm uppercase tracking-wider mb-2">
                      {formatDivisionName(div.division)}
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div className="text-white/90">Current</div>
                      <div className="font-mono text-white text-right">
                        {div.current_avg_speed !== null ? `${div.current_avg_speed.toFixed(1)} km/h` : '--'}
                      </div>
                      <div className="text-white/90">Predicted</div>
                      <div className="font-mono text-white text-right">
                        {div.predicted_avg_speed !== null ? `${div.predicted_avg_speed.toFixed(1)} km/h` : '--'}
                      </div>
                      <div className="text-white/90">Change</div>
                      <div className={`font-mono text-right ${div.speed_change !== null && div.speed_change !== undefined ? (div.speed_change > 0 ? 'text-white' : 'text-white/90') : 'text-white/90'}`}>
                        {div.speed_change !== null && div.speed_change !== undefined ? `${div.speed_change > 0 ? '+' : ''}${div.speed_change.toFixed(1)} km/h` : '--'}
                      </div>
                      <div className="text-white/90">Status</div>
                      <div className={`font-mono text-right ${getCongestionColor(div.congestion_level)}`}>
                        {getCongestionLabel(div.congestion_level)}
                      </div>
                    </div>
                    <div className="mt-3 pt-2 border-t border-white/30 text-[10px] text-white/90 uppercase tracking-wider">
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
