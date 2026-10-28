/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useEffect, useState, useMemo } from 'react';
import { fetchPm25Kpi, fetchPm25Prediction, type Pm25PredictionResponse } from '@/services/api';

import { ActivitySquare, AlertTriangle, CloudRain, Wind, Brain, Zap, Info } from 'lucide-react';
import { domainCardClass } from '@/components/city/presentation';
import { formatSingaporeTime } from "@/services/time";
import { useAppStore } from '@/store';

export default function PollutionPage() {
  const [data, setData] = useState<any | null>(null);
  const [prediction, setPrediction] = useState<Pm25PredictionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [predError, setPredError] = useState<string | null>(null);
  
  // Connect to global store to check cross-domain impacts from the coordinator
  const { report } = useAppStore();

  useEffect(() => {
    const loadData = async () => {
      try {
        const result = await fetchPm25Kpi();
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
    const loadPrediction = async () => {
      try {
        const result = await fetchPm25Prediction();
        setPrediction(result);
        setPredError(null);
      } catch (err: unknown) {
        if (err instanceof Error) {
          setPredError(err.message);
        } else {
          setPredError(String(err));
        }
      }
    };
    loadData();
    loadPrediction();
    const interval = setInterval(() => {
      loadData();
      loadPrediction();
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  // Compute City-Wide Summary from live data
  const summary = useMemo(() => {
    if (!data || !data.regions) return null;
    
    const regions = Object.values(data.regions) as { region: string, value: number, observed_at: string }[];
    if (regions.length === 0) return null;

    const values = regions.map(r => r.value);
    const maxVal = Math.max(...values);
    const minVal = Math.min(...values);
    
    // Calculate average
    const avg = values.reduce((sum, v) => sum + v, 0) / values.length;

    const highestRegion = regions.find(r => r.value === maxVal)?.region || 'Unknown';
    const lowestRegion = regions.find(r => r.value === minVal)?.region || 'Unknown';
    
    const regionsAboveAvg = regions.filter(r => r.value > avg).length;

    return {
      average: Math.round(avg),
      maxVal,
      minVal,
      highestRegion,
      lowestRegion,
      regionsAboveAvg,
      totalRegions: regions.length
    };
  }, [data]);

  // Check for relevant cross-domain impacts
  const airQualityImpacts = useMemo(() => {
    if (!report || !report.cross_domain_impacts) return [];
    return report.cross_domain_impacts.filter(imp => 
      imp.domains_involved?.includes('environment') || 
      imp.domains_involved?.includes('weather') ||
      imp.description.toLowerCase().includes('air') ||
      imp.description.toLowerCase().includes('haze') ||
      imp.description.toLowerCase().includes('pollution')
    );
  }, [report]);

  // Get current Singapore date (offsetDays: 0 = today, 1 = tomorrow, etc.)
  const getSGDate = (offsetDays = 0) => {
    const now = new Date();
    now.setDate(now.getDate() + offsetDays);
    return new Intl.DateTimeFormat('en-US', {
      timeZone: 'Asia/Singapore',
      month: 'short',
      day: 'numeric',
      year: 'numeric'
    }).format(now);
  };

  return (
    <div className="h-full bg-[var(--color-background)] text-[var(--color-foreground)] p-4 md:p-6 lg:p-8 flex flex-col font-sans">
      
      <div className="flex flex-col flex-grow min-h-0 overflow-y-auto custom-scrollbar">
        <h2 className="text-2xl font-heading text-[var(--color-primary)] mb-6 flex items-center gap-3">
          <Wind size={24} />
          Pollution Intelligence
        </h2>
        
        {(error || predError) && (
          <div className="text-red-500 mb-4 glass-panel p-4 rounded-lg">
            {error && <div>Live KPI: {error}</div>}
            {predError && <div>Forecast: {predError}</div>}
          </div>
        )}
        
        {data && summary ? (
          <div className="flex flex-col gap-6">
            
            {/* ============================================================
               SECTION 1: LIVE OBSERVATION
               ============================================================ */}
            <div className="glass-panel p-6 rounded-lg border-t-4 border-primary bg-primary/5">
              <div className="flex justify-between items-start mb-6">
                <h3 className="font-bold text-lg flex items-center space-x-2 text-primary uppercase tracking-widest text-xs">
                  <ActivitySquare size={18} />
                  <span>LIVE OBSERVATION</span>
                </h3>
                <div className="flex items-center gap-2 text-xs text-primary font-mono bg-primary/5 px-3 py-1 rounded">
                  <Zap size={12} className="text-primary" />
                  <span>1-Hour PM2.5 · Real-time</span>
                </div>
              </div>
              
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* City-Wide Summary */}
                <div className="lg:col-span-2 flex flex-col gap-6">
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className={`${domainCardClass("pm25", "p-4 rounded-lg")} flex flex-col justify-center items-center`}>
                      <span className="text-xs text-white/90 uppercase tracking-wider mb-2">City Average</span>
                      <span className="text-3xl font-mono text-white font-bold">{summary.average} <span className="text-sm text-white/90">µg/m³</span></span>
                    </div>
                    <div className={`${domainCardClass("pm25", "p-4 rounded-lg")} flex flex-col justify-center items-center`}>
                      <span className="text-xs text-white/90 uppercase tracking-wider mb-2">Highest Region</span>
                      <span className="text-xl font-bold text-white capitalize">{summary.highestRegion}</span>
                      <span className="text-sm font-mono text-white/90 mt-1">{summary.maxVal} µg/m³</span>
                    </div>
                    <div className={`${domainCardClass("pm25", "p-4 rounded-lg")} flex flex-col justify-center items-center`}>
                      <span className="text-xs text-white/90 uppercase tracking-wider mb-2">Lowest Region</span>
                      <span className="text-xl font-bold text-white capitalize">{summary.lowestRegion}</span>
                      <span className="text-sm font-mono text-white/90 mt-1">{summary.minVal} µg/m³</span>
                    </div>
                  </div>

                  {/* Regional Comparison Live */}
                  <div className="space-y-4">
                    {['north', 'south', 'east', 'west', 'central'].map((regionName) => {
                      const info = data.regions[regionName];
                      if (!info) return null;
                      
                      const widthPct = Math.max(5, (info.value / Math.max(summary.maxVal, 1)) * 100);
                      
                      return (
                        <div key={regionName} className="flex flex-col gap-2">
                          <div className="flex justify-between text-sm">
                            <span className="capitalize font-semibold text-slate-600 w-24">{regionName}</span>
                            <span className="font-mono text-slate-900">{info.value} <span className="text-slate-600 text-xs">µg/m³</span></span>
                          </div>
                          <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden">
                            <div 
                              className="h-full bg-primary transition-all duration-1000 ease-out rounded-full"
                              style={{ width: `${widthPct}%` }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Right: Live metadata */}
                <div className="flex flex-col justify-center items-center gap-4">
                  <div className="p-4 bg-slate-50 rounded-lg border border-slate-200 text-center w-full">
                    <span className="text-xs text-slate-500 uppercase tracking-wider mb-1">Last Updated</span>
                    <span className="font-mono text-primary">
                      {data.raw_updated_timestamp ? `${formatSingaporeTime(data.raw_updated_timestamp)} SGT` : 'Unknown'}
                    </span>
                  </div>
                  <div className="p-4 bg-slate-50 rounded-lg border border-slate-200 text-center w-full">
                    <span className="text-xs text-slate-500 uppercase tracking-wider mb-1">Unit</span>
                    <span className="font-mono text-slate-500">µg/m³</span>
                  </div>
                </div>
              </div>
            </div>

            {/* ============================================================
               SECTION 2: NEXT-DAY FORECAST
               ============================================================ */}
            <div className="glass-panel p-6 rounded-lg border-t-4 border-amber-500 bg-amber-50">
              <div className="flex justify-between items-start mb-6">
                <h3 className="font-bold text-lg flex items-center space-x-2 text-amber-700 uppercase tracking-widest text-xs">
                  <Brain size={18} />
                  <span>NEXT-DAY FORECAST</span>
                </h3>
                <div className="flex items-center gap-2 text-xs text-amber-700 font-mono bg-amber-50 px-3 py-1 rounded">
                  <Info size={12} className="text-amber-800" />
                  <span>Forecast</span>
                </div>
              </div>

              {prediction ? (
                <div className="flex flex-col gap-6">
                  {/* Prediction Metadata */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="p-4 bg-slate-50 rounded-lg border border-slate-200">
                      <span className="text-xs text-slate-500 uppercase tracking-wider mb-1">Prediction For</span>
                      <span className="font-mono text-amber-800">{getSGDate(0)}</span>
                    </div>
                    <div className="p-4 bg-slate-50 rounded-lg border border-slate-200">
                      <span className="text-xs text-slate-500 uppercase tracking-wider mb-1">Target Window</span>
                      <span className="font-mono text-slate-600 text-sm">{getSGDate(1)} → {getSGDate(1)}</span>
                    </div>
                    <div className="p-4 bg-slate-50 rounded-lg border border-slate-200">
                      <span className="text-xs text-slate-500 uppercase tracking-wider mb-1">Horizon</span>
                      <span className="font-mono text-slate-600">{prediction.prediction_horizon_hours}h</span>
                    </div>
                  </div>

                  {/* Per-Region Predictions */}
                  <div className="space-y-3">
                    {prediction.regions.map((regionPred: any) => {


                      if (!regionPred.available) {
                        return (
                          <div key={regionPred.region} className="p-4 bg-slate-50 rounded-lg border border-red-200/50">
                            <div className="flex justify-between items-center">
                              <span className="capitalize font-semibold text-slate-600">{regionPred.region}</span>
                              <span className="text-red-700 font-mono text-xs">UNAVAILABLE</span>
                            </div>
                            <div className="text-xs text-red-700 mt-1">{regionPred.unavailable_reason}</div>
                          </div>
                        );
                      }

                      return (
                        <div key={regionPred.region} className={domainCardClass("pm25", "p-4 rounded-lg")}>
                          <div className="flex justify-between items-start mb-4">
                            <span className="capitalize font-semibold text-white">{regionPred.region}</span>

                          </div>

                          <div className="grid grid-cols-2 gap-4 mb-3">
                            <div className="p-3 bg-white/15 rounded border border-white/20">
                              <span className="text-xs text-white/90 uppercase tracking-wider block mb-1">Next-Day Mean</span>
                              <span className="text-2xl font-mono text-white font-bold">
                                {regionPred.next_day_mean_ugm3 !== null ? `${regionPred.next_day_mean_ugm3} µg/m³` : '—'}
                              </span>
                            </div>
                            <div className="p-3 bg-white/15 rounded border border-white/20">
                              <span className="text-xs text-white/90 uppercase tracking-wider block mb-1">Next-Day Max</span>
                              <span className="text-2xl font-mono text-white font-bold">
                                {regionPred.next_day_max_ugm3 !== null ? `${regionPred.next_day_max_ugm3} µg/m³` : '—'}
                              </span>
                            </div>
                          </div>




                        </div>
                      );
                    })}
                  </div>


                </div>
              ) : predError ? (
                <div className="p-8 text-center bg-slate-50/20 rounded-lg border border-slate-200">
                  <div className="text-red-500 mb-2 flex justify-center"><AlertTriangle size={32} /></div>
                  <div className="text-slate-500 font-mono">FORECAST UNAVAILABLE</div>
                  <div className="text-xs text-slate-600 mt-2">{predError}</div>
                </div>
              ) : (
                <div className="flex items-center justify-center h-48 text-slate-500 font-mono animate-pulse">Loading Forecast...</div>
              )}
            </div>

            {/* ============================================================
               SECTION 3: Cross-Domain Intelligence (existing)
               ============================================================ */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div className="lg:col-span-2 flex flex-col gap-6">
                {/* Pollution Alerts */}
                <div className="glass-panel p-6 rounded-lg border-t-4 border-slate-200">
                  <h3 className="font-bold text-lg mb-4 flex items-center space-x-2 text-slate-500 uppercase tracking-widest text-xs">
                    <AlertTriangle size={18} />
                    <span>Pollution Alerts</span>
                  </h3>
                  <div className="flex items-center justify-center bg-slate-50/20 rounded-lg border border-dashed border-slate-200 p-6">
                    <div className="text-center">
                      <div className="text-slate-500 mb-2 flex justify-center"><AlertTriangle size={32} /></div>
                      <div className="text-slate-500 font-mono">No active pollution alerts</div>
                    </div>
                  </div>
                </div>

                {/* Regional Distribution Summary */}
                <div className="glass-panel p-6 rounded-lg">
                  <h3 className="font-bold text-lg mb-4 flex items-center space-x-2 text-primary uppercase tracking-widest text-xs">
                    <ActivitySquare size={18} />
                    <span>Regional PM2.5 Distribution (Live)</span>
                  </h3>
                  <div className="space-y-3">
                    <div className="flex justify-between items-center p-3 bg-slate-50 rounded border border-slate-200">
                      <span className="text-xs text-slate-500 uppercase">Highest</span>
                      <span className="text-sm text-slate-700 capitalize">{summary.highestRegion}</span>
                    </div>
                    <div className="flex justify-between items-center p-3 bg-slate-50 rounded border border-slate-200">
                      <span className="text-xs text-slate-500 uppercase">Lowest</span>
                      <span className="text-sm text-slate-700 capitalize">{summary.lowestRegion}</span>
                    </div>
                    <div className="flex justify-between items-center p-3 bg-slate-50 rounded border border-slate-200">
                      <span className="text-xs text-slate-500 uppercase">Average</span>
                      <span className="text-sm text-slate-700 font-mono">{summary.average} µg/m³</span>
                    </div>
                    <div className="flex justify-between items-center p-3 bg-slate-50 rounded border border-slate-200">
                      <span className="text-xs text-slate-500 uppercase">Regions Above City Average</span>
                      <span className="text-sm text-primary font-bold">{summary.regionsAboveAvg} / {summary.totalRegions}</span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex flex-col gap-6">
                {/* Coordinator Context */}
                {airQualityImpacts.length > 0 ? (
                  <div className="glass-panel p-6 rounded-lg border-l-4 border-primary bg-primary/5">
                    <h3 className="font-bold text-lg mb-4 flex items-center space-x-2 text-primary uppercase tracking-widest text-xs">
                      <CloudRain size={18} />
                      <span>Cross-Domain Impact</span>
                    </h3>
                    <div className="space-y-4">
                      {airQualityImpacts.map((impact, idx) => (
                        <div key={idx} className="flex flex-col gap-2">
                          <div className="text-xs text-primary font-bold uppercase tracking-wider">
                            {impact.domains_involved?.join(' + ')}
                          </div>
                          <div className="text-sm text-slate-700 italic">
                            {impact.description}
                          </div>
                          {report?.city_level_recommendations && report.city_level_recommendations.length > 0 && (
                            <div className="mt-2 p-3 bg-slate-50 rounded border border-slate-200 text-sm text-slate-600">
                              <span className="text-xs text-slate-500 uppercase block mb-1">Recommendation</span>
                              {report.city_level_recommendations[0]}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="glass-panel p-6 rounded-lg opacity-70">
                    <h3 className="font-bold text-lg mb-4 flex items-center space-x-2 text-slate-500 uppercase tracking-widest text-xs">
                      <CloudRain size={18} />
                      <span>Cross-Domain Impact</span>
                    </h3>
                    <div className="text-sm text-slate-500 text-center py-4 italic">
                      No active air-quality cross-domain impacts.
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : error ? (
          <div role="alert" className="glass-panel rounded-lg border border-red-200 bg-red-50 p-6 text-center">
            <div className="font-semibold text-red-800">Live PM2.5 observations are unavailable.</div>
            <p className="mt-2 text-sm text-red-700">The page will retry automatically. The error details are shown above.</p>
          </div>
        ) : data ? (
          <div className="glass-panel rounded-lg border border-slate-200 p-6 text-center text-sm text-slate-600">
            No regional PM2.5 readings were returned for this update.
          </div>
        ) : (
          <div aria-live="polite" aria-busy="true" className="flex items-center justify-center h-64 text-slate-500 font-mono animate-pulse">Loading Pollution Intelligence...</div>
        )}
      </div>
    </div>
  );
}
