/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useEffect, useState } from 'react';
import { useAppStore } from '@/store';
import { fetchCityReport, fetchWeatherKpi, fetchPm25Kpi } from '@/services/api';
import Link from 'next/link';


import SingaporeMap from '@/components/map/SingaporeMap';
import { ShieldAlert, Cloud, Car, Droplets, Wind, AlertTriangle, ArrowRight, XCircle } from 'lucide-react';


function StatusIndicator({ available }: { available?: boolean }) {
  if (available) {
    return (
      <div className="flex items-center gap-1.5 text-xs font-bold text-green-400 bg-green-400/10 px-2 py-1 rounded">
        <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse"></span>
        LIVE
      </div>
    );
  }
  return (
    <div className="flex items-center gap-1.5 text-xs font-bold text-red-400 bg-red-400/10 px-2 py-1 rounded">
      <XCircle size={10} />
      UNAVAILABLE
    </div>
  );
}

function StatusHealthItem({ name, available }: { name: string, available?: boolean }) {
  return (
    <div className="flex justify-between items-center py-2 border-b border-gray-800/50 last:border-0">
      <span className="text-sm font-semibold text-gray-300">{name}</span>
      {available ? (
        <span className="text-xs font-mono text-green-400 flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-green-400"></span> LIVE
        </span>
      ) : (
        <span className="text-xs font-mono text-red-400 flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-red-400"></span> DEGRADED
        </span>
      )}
    </div>
  );
}

export default function Dashboard() {
  const { report, setReport } = useAppStore();
  const [error, setError] = useState<string | null>(null);
  const [weatherKpi, setWeatherKpi] = useState<any>(null);
  const [pm25Kpi, setPm25Kpi] = useState<any>(null);

  useEffect(() => {
    const loadData = async () => {
      try {
        const [data, weather, pm25] = await Promise.all([
          fetchCityReport(),
          fetchWeatherKpi().catch(() => null),
          fetchPm25Kpi().catch(() => null)
        ]);
        setReport(data);
        setWeatherKpi(weather);
        setPm25Kpi(pm25);
        setError(null);
      } catch (err: any) {
        setError(err.message);
      }
    };

    loadData();
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, [setReport]);

  const traffic = report?.domain_status?.traffic;
  const flood = report?.domain_status?.flood;
  
  // Weather mapping from canonical weather KPI endpoint (direct live API)
  const weatherAvailable = !!weatherKpi?.general;
  
  // PM2.5 KPI availability from direct API call
  const pm25Available = pm25Kpi?.regions && Object.keys(pm25Kpi.regions).length > 0;

  const incidents = report?.priority_incidents || [];

  return (
    <div className="flex flex-col h-full bg-[var(--color-background)] text-[var(--color-foreground)] overflow-y-auto overflow-x-hidden font-sans">
      
      
      {/* Main Content Container - bounded to prevent overflow */}
      <div className="flex flex-col w-full max-w-[1920px] mx-auto px-4 md:px-6 lg:px-8 pb-8 gap-6 flex-grow">
        
        {/* Global Error state if API completely fails */}
        {error && (
          <div className="glass-panel p-4 bg-red-900/20 border-l-4 border-red-500 rounded flex items-center space-x-3 text-red-200 shrink-0">
            <ShieldAlert size={20} />
            <div>
              <h3 className="font-bold text-sm">API Unavailable</h3>
              <p className="text-xs">{error}</p>
            </div>
          </div>
        )}

        {/* CITY STATUS: 4 Compact Summary Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 shrink-0">
          <div className="glass-panel rounded-xl p-4 border border-gray-800/50 flex flex-col justify-between">
            <div className="flex justify-between items-start mb-2">
              <div className="flex items-center gap-2 text-gray-400">
                <Cloud size={16} className="text-blue-400" />
                <span className="text-xs font-bold tracking-wider">WEATHER</span>
              </div>
              <StatusIndicator available={weatherAvailable} />
            </div>
            {weatherAvailable ? (
              <div>
                <div className="text-xl font-mono font-bold text-white mb-1">
                  {weatherKpi?.general?.temperature_high_c ? `${weatherKpi.general.temperature_low_c}-${weatherKpi.general.temperature_high_c}°C` : '--'}
                </div>
                <div className="text-xs text-gray-500 line-clamp-1 flex justify-between items-center">
                  <span>{weatherKpi?.general?.forecast_text || 'Unknown'}</span>
                  <span className="text-[9px] uppercase tracking-wider text-cyan-400 bg-cyan-900/20 px-1 py-0.5 rounded ml-2">24h Forecast</span>
                </div>
              </div>
            ) : (
              <div className="text-xl font-mono font-bold text-gray-600">--</div>
            )}
          </div>

          <div className="glass-panel rounded-xl p-4 border border-gray-800/50 flex flex-col justify-between">
            <div className="flex justify-between items-start mb-2">
              <div className="flex items-center gap-2 text-gray-400">
                <Car size={16} className="text-yellow-400" />
                <span className="text-xs font-bold tracking-wider">TRAFFIC</span>
              </div>
              <StatusIndicator available={traffic?.available} />
            </div>
            {traffic?.available ? (
              <div>
                <div className={`text-xl font-mono font-bold mb-1 ${traffic?.overall_status === 'DISRUPTED' ? 'text-red-400' : traffic?.overall_status === 'ELEVATED' ? 'text-yellow-400' : 'text-green-400'}`}>
                  {traffic?.overall_status || 'NORMAL'}
                </div>
                <div className="text-xs text-gray-500 line-clamp-1">
                  {traffic?.active_alert_count || 0} active incidents
                </div>
              </div>
            ) : (
              <div className="text-xl font-mono font-bold text-gray-600">--</div>
            )}
          </div>

          <div className="glass-panel rounded-xl p-4 border border-gray-800/50 flex flex-col justify-between">
            <div className="flex justify-between items-start mb-2">
              <div className="flex items-center gap-2 text-gray-400">
                <Droplets size={16} className="text-cyan-400" />
                <span className="text-xs font-bold tracking-wider">FLOOD</span>
              </div>
              <StatusIndicator available={flood?.available} />
            </div>
            {flood?.available ? (
              <div>
                <div className={`text-xl font-mono font-bold mb-1 ${flood?.overall_risk === 'HIGH' ? 'text-red-400' : flood?.overall_risk === 'MODERATE' ? 'text-yellow-400' : 'text-green-400'}`}>
                  {flood?.overall_risk || 'LOW'}
                </div>
                <div className="text-xs text-gray-500 line-clamp-1">
                  {flood?.active_alert_count || 0} warnings
                </div>
              </div>
            ) : (
              <div className="text-xl font-mono font-bold text-gray-600">--</div>
            )}
          </div>

          <div className="glass-panel rounded-xl p-4 border border-gray-800/50 flex flex-col justify-between">
            <div className="flex justify-between items-start mb-2">
              <div className="flex items-center gap-2 text-gray-400">
                <Wind size={16} className="text-teal-400" />
                <span className="text-xs font-bold tracking-wider">POLLUTION</span>
              </div>
              <StatusIndicator available={pm25Available} />
            </div>
            {pm25Available ? (
              <div>
                <div className="text-xl font-mono font-bold text-green-400 mb-1">
                  {(() => {
                    const regions = Object.values(pm25Kpi.regions) as any[];
                    const avg = regions.reduce((sum, r) => sum + r.value, 0) / regions.length;
                    if (avg <= 12) return 'GOOD';
                    if (avg <= 35) return 'MODERATE';
                    if (avg <= 55) return 'UNHEALTHY';
                    if (avg <= 150) return 'VERY UNHEALTHY';
                    return 'HAZARDOUS';
                  })()}
                </div>
                <div className="text-xs text-gray-500 line-clamp-1">
                  Avg: {(() => {
                    const regions = Object.values(pm25Kpi.regions) as any[];
                    return Math.round(regions.reduce((sum, r) => sum + r.value, 0) / regions.length);
                  })()} µg/m³
                </div>
              </div>
            ) : (
              <div className="text-xl font-mono font-bold text-gray-600">--</div>
            )}
          </div>
        </div>

        {/* MAP - Visually dominant, explicitly bounded */}
        <div className="w-full h-[500px] lg:h-[600px] relative shrink-0 rounded-xl overflow-hidden glass-panel border border-gray-800/50 z-0">
          <SingaporeMap />
        </div>

        {/* ALERTS & SYSTEM HEALTH */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 shrink-0">
          {/* PRIORITY ALERTS */}
          <div className="lg:col-span-2 glass-panel p-5 rounded-xl border border-gray-800/50 flex flex-col max-h-[300px]">
            <h3 className="text-xs font-bold text-gray-400 tracking-widest mb-4 flex items-center gap-2 shrink-0">
              <AlertTriangle size={14} className="text-orange-400" /> PRIORITY ALERTS
            </h3>
            
            <div className="flex-grow overflow-y-auto pr-2 space-y-3 custom-scrollbar">
              {incidents.length > 0 ? (
                incidents.map((incident: any) => (
                  <div key={incident.id} className="p-3 bg-[var(--color-surface-low)] rounded border-l-2 border-red-500 text-sm">
                    <div className="flex justify-between mb-1">
                      <span className="font-bold text-red-400 uppercase text-xs">{incident.domain} - {incident.severity}</span>
                      <span className="text-[10px] text-gray-500 font-mono">{incident.id.substring(0, 8)}</span>
                    </div>
                    <div className="text-gray-200">{incident.description}</div>
                    <div className="text-xs text-gray-500 mt-1 font-mono">{incident.affected_zones?.join(', ')}</div>
                  </div>
                ))
              ) : (
                <div className="h-full flex items-center justify-center text-gray-500 text-xs font-bold tracking-widest uppercase py-8">
                  NO ACTIVE PRIORITY ALERTS
                </div>
              )}
            </div>
          </div>

          {/* SYSTEM HEALTH */}
          <div className="lg:col-span-1 glass-panel p-5 rounded-xl border border-gray-800/50 flex flex-col">
            <h3 className="text-xs font-bold text-gray-400 tracking-widest mb-4 shrink-0">SYSTEM HEALTH</h3>
            <div className="flex-grow flex flex-col">
              <StatusHealthItem name="Weather API" available={weatherAvailable} />
              <StatusHealthItem name="Traffic API" available={traffic?.available} />
              <StatusHealthItem name="Flood API" available={flood?.available} />
              <StatusHealthItem name="Pollution API" available={pm25Available} />
              <StatusHealthItem name="City Coordinator" available={!error} />
            </div>
          </div>
        </div>

        {/* DOMAIN SUMMARIES */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 shrink-0">
          <div className="glass-panel p-4 rounded-xl border border-gray-800/50 flex flex-col justify-between group hover:bg-[var(--color-surface-high)] transition-colors">
            <div>
              <div className="text-xs font-bold text-blue-400 tracking-widest mb-2">WEATHER OUTLOOK</div>
              <div className="text-sm text-gray-300 line-clamp-2 mb-4">
                {weatherAvailable ? `Forecast: ${weatherKpi?.general?.forecast_text || 'Unknown'}` : 'Data unavailable.'}
              </div>
            </div>
            <Link href="/weather" className="text-xs font-bold text-gray-400 group-hover:text-white flex items-center gap-1 transition-colors">
              VIEW DETAILS <ArrowRight size={12} />
            </Link>
          </div>

          <div className="glass-panel p-4 rounded-xl border border-gray-800/50 flex flex-col justify-between group hover:bg-[var(--color-surface-high)] transition-colors">
            <div>
              <div className="text-xs font-bold text-yellow-400 tracking-widest mb-2">TRAFFIC NETWORK</div>
              <div className="text-sm text-gray-300 line-clamp-2 mb-4">
                {traffic?.available ? `${traffic?.active_alert_count || 0} incidents affecting ${traffic?.affected_zones?.length || 0} zones.` : 'Data unavailable.'}
              </div>
            </div>
            <Link href="/traffic" className="text-xs font-bold text-gray-400 group-hover:text-white flex items-center gap-1 transition-colors">
              VIEW DETAILS <ArrowRight size={12} />
            </Link>
          </div>

          <div className="glass-panel p-4 rounded-xl border border-gray-800/50 flex flex-col justify-between group hover:bg-[var(--color-surface-high)] transition-colors">
            <div>
              <div className="text-xs font-bold text-cyan-400 tracking-widest mb-2">FLOOD MONITORING</div>
              <div className="text-sm text-gray-300 line-clamp-2 mb-4">
                {flood?.available ? `Overall risk: ${flood?.overall_risk || 'LOW'}. ${flood?.affected_zones?.length || 0} zones affected.` : 'Data unavailable.'}
              </div>
            </div>
            <Link href="/flood" className="text-xs font-bold text-gray-400 group-hover:text-white flex items-center gap-1 transition-colors">
              VIEW DETAILS <ArrowRight size={12} />
            </Link>
          </div>

          <div className="glass-panel p-4 rounded-xl border border-gray-800/50 flex flex-col justify-between group hover:bg-[var(--color-surface-high)] transition-colors">
            <div>
              <div className="text-xs font-bold text-teal-400 tracking-widest mb-2">AIR QUALITY</div>
              <div className="text-sm text-gray-300 line-clamp-2 mb-4">
                {pm25Available ? (() => {
                    const regions = Object.values(pm25Kpi.regions) as any[];
                    const avg = Math.round(regions.reduce((sum, r) => sum + r.value, 0) / regions.length);
                    const status = avg <= 12 ? 'GOOD' : avg <= 35 ? 'MODERATE' : avg <= 55 ? 'UNHEALTHY' : avg <= 150 ? 'VERY UNHEALTHY' : 'HAZARDOUS';
                    return `Status: ${status}. Avg: ${avg} µg/m³.`;
                  })() : 'Data unavailable.'}
              </div>
            </div>
            <Link href="/pollution" className="text-xs font-bold text-gray-400 group-hover:text-white flex items-center gap-1 transition-colors">
              VIEW DETAILS <ArrowRight size={12} />
            </Link>
          </div>
        </div>

      </div>
    </div>
  );
}
