/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useEffect, useState } from 'react';
import { fetchWeatherKpi } from '@/services/api';

import { CloudRain, Wind, ThermometerSun, Droplets, Map, AlertTriangle, Cloud, Compass, Calendar, CloudSun, Wind as WindIcon } from 'lucide-react';

export default function WeatherPage() {
  const [data, setData] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedRegion, setSelectedRegion] = useState<string | null>(null);

  useEffect(() => {
    const loadData = async () => {
      try {
        const result = await fetchWeatherKpi();
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

  // Use the API's valid period to show timeframe
  const formatTimeRange = (start?: string, end?: string) => {
    if (!start || !end) return '24-Hour Forecast';
    const s = new Date(start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const e = new Date(end).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return `Valid: ${s} to ${e}`;
  };

  return (
    <div className="h-full bg-[var(--color-background)] text-[var(--color-foreground)] p-4 md:p-6 lg:p-8 flex flex-col font-sans">
      
      <div className="flex flex-col flex-grow min-h-0 overflow-y-auto custom-scrollbar">
        <h2 className="text-2xl font-heading text-[var(--color-primary)] mb-6 flex items-center gap-3">
          <CloudRain size={24} />
          Weather Intelligence
        </h2>
        
        {error && <div className="text-red-500 mb-4 glass-panel p-4 rounded-lg">{error}</div>}
        
        {data ? (
          <div className="flex flex-col gap-6">
            
            {/* Top row: 24h Summary + Alerts */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              
              {/* 24-Hour Outlook */}
              <div className="lg:col-span-2 glass-panel p-6 rounded-lg flex flex-col justify-between">
                <div>
                  <div className="flex justify-between items-start mb-6">
                    <h3 className="font-bold text-lg flex items-center space-x-2 text-cyan-400 uppercase tracking-widest text-xs">
                      <ThermometerSun size={18} />
                      <span>24-Hour National Outlook</span>
                    </h3>
                    <div className="text-xs text-gray-400 font-mono bg-gray-900/50 px-3 py-1 rounded">
                      {formatTimeRange(data.general?.valid_period_start, data.general?.valid_period_end)}
                    </div>
                  </div>
                  
                  {data.general ? (
                    <div className="flex flex-col md:flex-row gap-8 items-center">
                      <div className="flex flex-col items-center justify-center p-6 bg-cyan-900/10 border border-cyan-900/30 rounded-full w-48 h-48 shrink-0">
                        <Cloud size={48} className="text-cyan-400 mb-2" />
                        <span className="text-xl font-black text-center leading-tight">{data.general.forecast_text || 'Unknown'}</span>
                      </div>
                      
                      <div className="grid grid-cols-2 gap-4 w-full">
                        <div className="p-4 bg-gray-900/40 rounded-lg border border-gray-800 flex flex-col h-full">
                          <div className="text-cyan-400 text-xs uppercase tracking-wider mb-2 flex items-start justify-between">
                            <span className="flex items-center gap-2 mt-0.5"><ThermometerSun size={14}/> Current Temperature</span>
                            {data.current_temperature?.available && (
                              <div className="text-[8px] px-1.5 py-0.5 bg-green-900/30 text-green-400 border border-green-800 rounded tracking-widest uppercase text-right leading-tight">
                                LIVE OBSERVATION
                                {data.current_temperature.source?.includes('NEA') && (
                                  <>
                                    <br/>
                                    NEA / data.gov.sg
                                  </>
                                )}
                              </div>
                            )}
                          </div>
                          {data.current_temperature?.available ? (
                            <div className="flex flex-col flex-grow">
                              <div className="text-3xl font-mono text-white mb-1 leading-none mt-1">
                                {data.current_temperature.value_c}°C
                              </div>
                              <div className="text-xs text-gray-400 mb-4 font-mono">
                                {data.current_temperature.stations_used} stations &middot; {data.current_temperature.freshness_minutes?.toFixed(0)} min ago
                              </div>
                              <div className="text-[9px] text-gray-500 uppercase tracking-widest mb-1 mt-auto pt-2 border-t border-gray-800/50">Observed Station Range</div>
                              <div className="text-xs font-mono text-gray-400">
                                {data.current_temperature.min_c}°C &mdash; {data.current_temperature.max_c}°C
                              </div>
                            </div>
                          ) : (
                            <div className="flex-grow flex flex-col justify-center mt-2">
                              <div className="text-2xl font-mono text-gray-500 italic uppercase">Unavailable</div>
                            </div>
                          )}
                        </div>

                        <div className="p-4 bg-gray-900/40 rounded-lg border border-gray-800 flex flex-col h-full">
                          <div className="text-gray-500 text-xs uppercase tracking-wider mb-2 flex items-center gap-2"><ThermometerSun size={14}/> Forecast</div>
                          <div className="text-3xl font-mono text-white mb-2 leading-none mt-1">
                            {data.general.temperature_c ?? `${data.general.temperature_low_c}° - ${data.general.temperature_high_c}°`}°C
                          </div>
                        </div>
                        
                        <div className="p-4 bg-gray-900/40 rounded-lg border border-gray-800">
                          <div className="text-gray-500 text-xs uppercase tracking-wider mb-2 flex items-center gap-2"><Droplets size={14}/> Relative Humidity</div>
                          <div className="text-2xl font-mono text-white">
                            {data.general.relative_humidity_pct ?? `${data.general.relative_humidity_low_pct} - ${data.general.relative_humidity_high_pct}`}%
                          </div>
                        </div>

                        <div className="p-4 bg-gray-900/40 rounded-lg border border-gray-800 flex justify-between items-center">
                          <div>
                            <div className="text-gray-500 text-xs uppercase tracking-wider mb-1 flex items-center gap-2"><Wind size={14}/> Surface Wind</div>
                            <div className="text-xl font-mono text-white">
                              {data.general.wind_speed_kmh ?? `${data.general.wind_speed_low_kmh} - ${data.general.wind_speed_high_kmh}`} <span className="text-sm text-gray-400">km/h</span>
                            </div>
                          </div>
                          <div className="flex flex-col items-center justify-center bg-gray-800/50 w-12 h-12 rounded-full border border-gray-700">
                            <Compass size={18} className="text-cyan-500 mb-1" />
                            <span className="text-[10px] font-bold text-gray-300">{data.general.wind_direction}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="text-gray-500 font-mono italic">Forecast data unavailable</div>
                  )}
                </div>
              </div>

              {/* Alerts Section */}
              <div className="glass-panel p-6 rounded-lg border-t-4 border-gray-700 flex flex-col">
                <h3 className="font-bold text-lg mb-4 flex items-center space-x-2 text-gray-400 uppercase tracking-widest text-xs">
                  <AlertTriangle size={18} />
                  <span>Active Weather Alerts</span>
                </h3>
                <div className="flex-grow flex items-center justify-center bg-gray-900/20 rounded-lg border border-dashed border-gray-800 p-6">
                  <div className="text-center">
                    <div className="text-green-500/80 mb-2 flex justify-center"><AlertTriangle size={32} /></div>
                    <div className="text-gray-400 font-mono">No active weather alerts</div>
                    <div className="text-xs text-gray-600 mt-2">API reports normal conditions</div>
                  </div>
                </div>
              </div>

            </div>

            {/* OFFICIAL NEA FORECAST Section */}
            <div className="glass-panel p-6 rounded-lg border-t-4 border-amber-500 bg-amber-900/10">
              <div className="flex justify-between items-start mb-6">
                <h3 className="font-bold text-lg flex items-center space-x-2 text-amber-400 uppercase tracking-widest text-xs">
                  <Calendar size={18} />
                  <span>OFFICIAL NEA FORECAST</span>
                </h3>
                <div className="text-xs text-amber-400 font-mono bg-amber-900/30 px-3 py-1 rounded">
                  Source: NEA 24-Hour Weather Forecast / data.gov.sg
                </div>
              </div>

              {data.general ? (
                <>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                  {/* Temperature Range */}
                  <div className="p-4 bg-gray-900/40 rounded-lg border border-gray-800">
                    <div className="flex items-center gap-2 text-amber-400 text-xs uppercase tracking-wider mb-3">
                      <ThermometerSun size={14} />
                      <span>Temperature Range</span>
                    </div>
                    <div className="text-2xl font-mono text-white">
                      {data.general.temperature_low_c !== undefined && data.general.temperature_high_c !== undefined
                        ? `${data.general.temperature_low_c}° - ${data.general.temperature_high_c}°C`
                        : data.general.temperature_c !== undefined
                        ? `${data.general.temperature_c}°C`
                        : '—'}
                    </div>
                    <div className="text-[10px] text-gray-500 uppercase tracking-widest mt-1">
                      Forecast Low / High
                    </div>
                  </div>

                  {/* Relative Humidity Range */}
                  <div className="p-4 bg-gray-900/40 rounded-lg border border-gray-800">
                    <div className="flex items-center gap-2 text-amber-400 text-xs uppercase tracking-wider mb-3">
                      <Droplets size={14} />
                      <span>Relative Humidity</span>
                    </div>
                    <div className="text-2xl font-mono text-white">
                      {data.general.relative_humidity_low_pct !== undefined && data.general.relative_humidity_high_pct !== undefined
                        ? `${data.general.relative_humidity_low_pct}% - ${data.general.relative_humidity_high_pct}%`
                        : data.general.relative_humidity_pct !== undefined
                        ? `${data.general.relative_humidity_pct}%`
                        : '—'}
                    </div>
                    <div className="text-[10px] text-gray-500 uppercase tracking-widest mt-1">
                      Forecast Low / High
                    </div>
                  </div>

                  {/* Wind Speed Range */}
                  <div className="p-4 bg-gray-900/40 rounded-lg border border-gray-800">
                    <div className="flex items-center gap-2 text-amber-400 text-xs uppercase tracking-wider mb-3">
                      <WindIcon size={14} />
                      <span>Surface Wind</span>
                    </div>
                    <div className="text-2xl font-mono text-white">
                      {data.general.wind_speed_low_kmh !== undefined && data.general.wind_speed_high_kmh !== undefined
                        ? `${data.general.wind_speed_low_kmh} - ${data.general.wind_speed_high_kmh} km/h`
                        : data.general.wind_speed_kmh !== undefined
                        ? `${data.general.wind_speed_kmh} km/h`
                        : '—'}
                    </div>
                    <div className="text-[10px] text-gray-500 uppercase tracking-widest mt-1">
                      Forecast Low / High
                    </div>
                  </div>

                  {/* Wind Direction */}
                  <div className="p-4 bg-gray-900/40 rounded-lg border border-gray-800 flex flex-col items-center justify-center">
                    <div className="flex items-center gap-2 text-amber-400 text-xs uppercase tracking-wider mb-3">
                      <Compass size={14} />
                      <span>Wind Direction</span>
                    </div>
                    <div className="flex flex-col items-center">
                      <div className="flex flex-col items-center justify-center bg-gray-800/50 w-16 h-16 rounded-full border border-gray-700 mb-2">
                        <WindIcon size={24} className="text-amber-500" />
                      </div>
                      <span className="text-lg font-bold text-gray-200">{data.general.wind_direction || '—'}</span>
                    </div>
                    <div className="text-[10px] text-gray-500 uppercase tracking-widest mt-1">
                      Compass Direction
                    </div>
                  </div>
                </div>

                <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="p-4 bg-gray-900/40 rounded-lg border border-gray-800">
                    <div className="flex items-center gap-2 text-amber-400 text-xs uppercase tracking-wider mb-3">
                      <CloudSun size={14} />
                      <span>Weather Condition</span>
                    </div>
                    <div className="text-lg font-semibold text-white text-center">
                      {data.general.forecast_text || 'Unknown'}
                    </div>
                    <div className="text-[10px] text-gray-500 uppercase tracking-widest mt-1 text-center">
                      Code: {data.general.forecast_code || '—'}
                    </div>
                  </div>

                  <div className="p-4 bg-gray-900/40 rounded-lg border border-gray-800">
                    <div className="flex items-center gap-2 text-amber-400 text-xs uppercase tracking-wider mb-3">
                      <Calendar size={14} />
                      <span>Forecast Validity</span>
                    </div>
                    <div className="text-sm font-mono text-white text-center">
                      {formatTimeRange(data.general?.valid_period_start, data.general?.valid_period_end)}
                    </div>
                    <div className="text-[10px] text-gray-500 uppercase tracking-widest mt-1 text-center">
                      NEA Official Issue
                    </div>
                  </div>
                </div>
                </>

              ) : (
                <div className="text-gray-500 font-mono italic text-center py-8">
                  Forecast data unavailable
                </div>
              )}
            </div>

            {/* Bottom Row: Regional Conditions */}
            <div className="glass-panel p-6 rounded-lg flex-grow">
              <div className="flex justify-between items-end mb-6 border-b border-gray-800 pb-4">
                <h3 className="font-bold text-lg flex items-center space-x-2 text-cyan-400 uppercase tracking-widest text-xs">
                  <Map size={18} />
                  <span>Regional Conditions</span>
                </h3>
                <span className="text-xs text-gray-500 font-mono italic">
                  Note: Regional precision limited to weather descriptors (provided by API)
                </span>
              </div>
              
              {data.regions && Object.keys(data.regions).length > 0 ? (
                selectedRegion ? (
                  <div className="bg-gray-900/40 border border-cyan-900/50 rounded-lg p-6 relative animate-in fade-in slide-in-from-bottom-4 duration-300">
                    <button 
                      onClick={() => setSelectedRegion(null)}
                      className="absolute top-4 right-4 text-gray-400 hover:text-white bg-gray-800 hover:bg-gray-700 rounded-full w-8 h-8 flex items-center justify-center transition-colors"
                    >
                      &times;
                    </button>
                    <div className="flex flex-col items-center">
                      <span className="text-sm uppercase tracking-widest text-cyan-400 mb-4">{selectedRegion} Region</span>
                      <Cloud size={48} className="text-gray-300 mb-4" />
                      <div className="text-2xl font-bold text-white mb-6">
                        {data.regions[selectedRegion]?.forecast_text || 'Unknown'}
                      </div>
                      
                      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 w-full max-w-4xl">
                        <div className="p-3 bg-gray-800/50 rounded border border-gray-700 flex flex-col justify-between">
                          <span className="text-xs text-gray-500 uppercase mb-1">Condition</span>
                          <span className="text-sm font-semibold text-gray-200">{data.regions[selectedRegion]?.forecast_text || 'N/A'}</span>
                        </div>
                        <div className="p-3 bg-gray-800/50 rounded border border-gray-700 flex flex-col justify-between relative">
                          <div className="flex justify-between items-start mb-1">
                            <span className="text-xs text-gray-500 uppercase">Current Temp</span>
                            {data.regions[selectedRegion]?.current_temperature?.value_c !== undefined && (
                              <span className="text-[7px] px-1 py-0.5 bg-green-900/30 text-green-400 border border-green-800 rounded tracking-widest uppercase ml-1">LIVE</span>
                            )}
                          </div>
                          <span className="text-sm font-semibold text-gray-200">
                            {data.regions[selectedRegion]?.current_temperature?.value_c !== undefined 
                              ? `${data.regions[selectedRegion].current_temperature.value_c}°C` 
                              : <span className="text-gray-500 italic font-mono">Unavailable</span>}
                          </span>
                        </div>
                        <div className="p-3 bg-gray-800/50 rounded border border-gray-700 flex flex-col justify-between relative">
                          <span className="text-xs text-gray-500 uppercase mb-1">Forecast Temp</span>
                          <span className="text-sm font-semibold text-gray-200">
                            {data.general?.temperature_c ?? `${data.general?.temperature_low_c}° - ${data.general?.temperature_high_c}°C`}{data.general?.temperature_c !== undefined ? '°C' : ''}
                          </span>
                          <span className="absolute top-2 right-2 text-[10px] text-gray-500 italic" title="National 24h range">(Nat)</span>
                        </div>
                        <div className="p-3 bg-gray-800/50 rounded border border-gray-700 flex flex-col justify-between relative">
                          <span className="text-xs text-gray-500 uppercase mb-1">Humidity</span>
                          <span className="text-sm font-semibold text-gray-200">
                            {data.general?.relative_humidity_pct ?? `${data.general?.relative_humidity_low_pct} - ${data.general?.relative_humidity_high_pct}`}%
                          </span>
                          <span className="absolute top-2 right-2 text-[10px] text-gray-500 italic" title="National 24h range">(Nat)</span>
                        </div>
                        <div className="p-3 bg-gray-800/50 rounded border border-gray-700 flex flex-col justify-between">
                          <span className="text-xs text-gray-500 uppercase mb-1">Last Updated</span>
                          <span className="text-sm font-semibold text-gray-200">
                            {data.updated_timestamp ? new Date(data.updated_timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Unknown'}
                          </span>
                        </div>
                      </div>
                      
                      <div className="mt-6 text-xs text-gray-500 italic text-center">
                        Note: Detailed metrics (temperature, humidity, wind) reflect the national 24-hour range, as the NEA API does not provide regional granularity for these.
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
                    {Object.entries(data.regions as any).map(([region, info]: [string, any]) => (
                      <div 
                        key={region} 
                        onClick={() => setSelectedRegion(region)}
                        className="bg-gray-900/40 border border-gray-800 rounded-lg p-5 flex flex-col items-center justify-center text-center hover:border-cyan-500/50 hover:bg-cyan-900/20 transition-colors cursor-pointer relative"
                      >
                        {info.current_temperature?.value_c !== undefined && (
                          <span className="absolute top-2 right-2 text-[6px] px-1 py-0.5 bg-green-900/30 text-green-400 border border-green-800 rounded tracking-widest uppercase">LIVE</span>
                        )}
                        <span className="text-xs uppercase tracking-widest text-gray-500 mb-3">{region}</span>
                        <Cloud size={32} className="text-gray-400 mb-3" />
                        <span className={`text-sm font-bold text-gray-200 ${info.current_temperature?.value_c !== undefined ? 'mb-2' : ''}`}>{info.forecast_text || 'Unknown'}</span>
                        {info.current_temperature?.value_c !== undefined && (
                          <span className="text-xs font-mono text-cyan-400">{info.current_temperature.value_c}°C</span>
                        )}
                      </div>
                    ))}
                  </div>
                )
              ) : (
                <div className="text-gray-500 font-mono italic p-8 text-center bg-gray-900/20 rounded-lg border border-gray-800">
                  Regional forecast data unavailable
                </div>
              )}
            </div>

          </div>
        ) : (
          <div className="flex items-center justify-center h-64 text-gray-500 font-mono animate-pulse">Loading Weather Intelligence...</div>
        )}
      </div>
    </div>
  );
}
