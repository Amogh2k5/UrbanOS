"use client";

import { useAppStore } from '@/store';
import { X, Activity, Waves, Car, ThermometerSun } from 'lucide-react';

export default function ZoneInspector() {
  const { report, selectedZone, setSelectedZone } = useAppStore();

  if (!selectedZone || !report) return null;

  // Extract specific zone data from the city report
  const zoneName = selectedZone;
  
  const checkZoneAffected = (zName: string, affectedZones?: string[]) => {
    if (!affectedZones) return false;
    const normalized = zName.replace('SG_', '').replace(/_/g, ' ').toLowerCase();
    return affectedZones.some(z => z.toLowerCase() === normalized || z === zName);
  };
  
  // Find overall domain statuses
  const envStatus = report.domain_status?.environment;
  const trafficStatus = report.domain_status?.traffic;
  const floodStatus = report.domain_status?.flood;

  // Since CitySituationReport may not have zone-specific metrics broken out natively,
  // we look up incidents and impacts related to this zone.
  const activeIncidents = report.priority_incidents?.filter(inc => checkZoneAffected(zoneName, inc.affected_zones)) || [];
  const crossImpacts = report.cross_domain_impacts?.filter(imp => checkZoneAffected(zoneName, imp.affected_zones)) || [];

  // Get zone-level risk (if affected by high risk impacts, otherwise normal)
  let zoneRisk = "LOW";
  let zoneRiskColor = "text-blue-400";
  
  if (crossImpacts.some(i => i.severity === 'CRITICAL')) {
    zoneRisk = "CRITICAL";
    zoneRiskColor = "text-red-500";
  } else if (crossImpacts.some(i => i.severity === 'HIGH') || activeIncidents.some(i => i.severity === 'HIGH')) {
    zoneRisk = "HIGH";
    zoneRiskColor = "text-orange-500";
  } else if (crossImpacts.some(i => i.severity === 'MODERATE') || activeIncidents.some(i => i.severity === 'MODERATE')) {
    zoneRisk = "MODERATE";
    zoneRiskColor = "text-yellow-400";
  }

  // Derive domain specific states for this zone
  const envZoneState = checkZoneAffected(zoneName, envStatus?.affected_zones) ? envStatus?.overall_risk || "Normal" : "Normal";
  const trafficZoneState = checkZoneAffected(zoneName, trafficStatus?.affected_zones) ? "Disrupted" : "Normal";
  const floodZoneState = checkZoneAffected(zoneName, floodStatus?.affected_zones) ? "Active Alert" : "Clear";

  return (
    <div className="absolute top-4 right-4 w-80 glass-panel-glow rounded-xl p-5 z-50 flex flex-col max-h-[90%] overflow-y-auto custom-scrollbar shadow-2xl">
      <div className="flex justify-between items-start mb-4 border-b border-gray-700 pb-3">
        <div>
          <h2 className="text-sm text-gray-400 font-semibold tracking-widest uppercase">Zone Inspector</h2>
          <h1 className="text-xl font-heading font-bold text-white mt-1 capitalize">{zoneName.replace('SG_', '').replace('_', ' ')}</h1>
        </div>
        <button 
          onClick={() => setSelectedZone(null)}
          className="text-gray-400 hover:text-white bg-gray-800/50 hover:bg-gray-700 p-1 rounded-full transition-colors"
        >
          <X size={18} />
        </button>
      </div>

      <div className="mb-5">
        <div className="text-xs text-gray-400 uppercase tracking-wider mb-1">Overall Risk</div>
        <div className={`text-2xl font-black tracking-widest ${zoneRiskColor}`}>
          {zoneRisk}
        </div>
      </div>

      <div className="space-y-4 mb-6">
        <div className="flex items-center justify-between p-2 rounded bg-gray-900/40 border border-gray-800">
          <div className="flex items-center gap-2 text-gray-300">
            <Car size={16} className="text-cyan-400" />
            <span className="font-semibold text-sm">Traffic</span>
          </div>
          <span className={`text-sm font-mono ${trafficZoneState !== 'Normal' ? 'text-orange-400' : 'text-gray-400'}`}>
            {trafficZoneState}
          </span>
        </div>
        
        <div className="flex items-center justify-between p-2 rounded bg-gray-900/40 border border-gray-800">
          <div className="flex items-center gap-2 text-gray-300">
            <ThermometerSun size={16} className="text-cyan-400" />
            <span className="font-semibold text-sm">Environment</span>
          </div>
          <span className={`text-sm font-mono ${envZoneState !== 'Normal' ? 'text-yellow-400' : 'text-gray-400'}`}>
            {envZoneState}
          </span>
        </div>

        <div className="flex items-center justify-between p-2 rounded bg-gray-900/40 border border-gray-800">
          <div className="flex items-center gap-2 text-gray-300">
            <Waves size={16} className="text-cyan-400" />
            <span className="font-semibold text-sm">Flood</span>
          </div>
          <span className={`text-sm font-mono ${floodZoneState !== 'Clear' ? 'text-red-400' : 'text-gray-400'}`}>
            {floodZoneState}
          </span>
        </div>
      </div>

      {activeIncidents.length > 0 && (
        <div className="mb-5">
          <h3 className="text-xs text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-2">
            <Activity size={14} /> Active Incidents ({activeIncidents.length})
          </h3>
          <div className="space-y-2">
            {activeIncidents.map((inc, idx) => (
              <div key={idx} className="p-2 text-sm bg-gray-800/50 rounded border-l-2 border-orange-500">
                <div className="font-bold text-gray-200">{inc.type}</div>
                <div className="text-gray-400 mt-1 line-clamp-2">{inc.description}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {crossImpacts.length > 0 && (
        <div className="mb-5">
          <h3 className="text-xs text-gray-400 uppercase tracking-wider mb-2">Coordinator Findings</h3>
          <div className="space-y-2">
            {crossImpacts.map((imp, idx) => (
              <div key={idx} className="p-2 text-sm bg-gray-800/50 rounded text-gray-300 italic">
                &quot;{imp.description}&quot;
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
