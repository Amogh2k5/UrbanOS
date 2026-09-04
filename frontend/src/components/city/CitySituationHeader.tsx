"use client";

import { useAppStore } from '@/store';
import { ShieldAlert, CheckCircle, AlertTriangle, Info } from 'lucide-react';

export default function CitySituationHeader() {
  const { report } = useAppStore();

  const getRiskIcon = (risk?: string) => {
    switch (risk) {
      case 'CRITICAL': return <ShieldAlert className="text-[var(--color-severity-critical)]" size={32} />;
      case 'HIGH': return <AlertTriangle className="text-[var(--color-severity-high)]" size={32} />;
      case 'MODERATE': return <AlertTriangle className="text-[var(--color-severity-moderate)]" size={32} />;
      case 'LOW': return <Info className="text-[var(--color-severity-low)]" size={32} />;
      case 'NORMAL': return <CheckCircle className="text-[var(--color-primary)]" size={32} />;
      default: return <Info className="text-gray-500" size={32} />;
    }
  };

  const getRiskColorClass = (risk?: string) => {
    switch (risk) {
      case 'CRITICAL': return 'text-[var(--color-severity-critical)]';
      case 'HIGH': return 'text-[var(--color-severity-high)]';
      case 'MODERATE': return 'text-[var(--color-severity-moderate)]';
      case 'LOW': return 'text-[var(--color-severity-low)]';
      case 'NORMAL': return 'text-[var(--color-primary)]';
      default: return 'text-gray-500';
    }
  };

  if (!report) {
    return (
      <div className="glass-panel p-6 rounded-xl animate-pulse">
        <div className="h-6 w-48 bg-gray-700 rounded mb-4"></div>
        <div className="h-4 w-96 bg-gray-800 rounded"></div>
      </div>
    );
  }

  return (
    <div className="glass-panel p-6 rounded-xl border-l-4" style={{ borderLeftColor: 'var(--color-severity-high)' }}>
      <div className="flex items-start justify-between">
        <div className="flex items-center space-x-4">
          {getRiskIcon(report.overall_risk_level)}
          <div>
            <h2 className="text-gray-400 font-heading text-sm font-bold tracking-widest uppercase mb-1">
              Singapore City Situation
            </h2>
            <div className="flex items-center space-x-3">
              <span className="text-white text-2xl font-bold">OVERALL RISK:</span>
              <span className={`text-2xl font-bold ${getRiskColorClass(report.overall_risk_level)}`}>
                {report.overall_risk_level}
              </span>
            </div>
          </div>
        </div>
        
        <div className="text-right max-w-md">
          <p className="text-gray-300 text-sm italic border-l-2 border-gray-700 pl-3">
            &quot;{report.city_level_recommendations?.[0] || 'Monitoring standard city operations.'}&quot;
          </p>
          <div className="text-xs text-gray-500 mt-2 font-mono">
            UPDATED: {new Date(report.generated_at).toLocaleTimeString()}
          </div>
        </div>
      </div>
      
      {report.priority_incidents?.length > 0 && (
        <div className="mt-4 pt-4 border-t border-gray-800/50 flex space-x-4">
          <span className="text-xs font-bold text-gray-500 tracking-wider uppercase">Active Incidents:</span>
          <span className="text-xs text-[var(--color-severity-high)] font-bold">{report.priority_incidents.length} Critical Issues</span>
        </div>
      )}
    </div>
  );
}
