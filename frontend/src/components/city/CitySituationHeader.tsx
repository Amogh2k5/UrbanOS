"use client";

import { useAppStore } from '@/store';
import { ShieldAlert, CheckCircle, AlertTriangle, Info } from 'lucide-react';
import { statusBadgeClass } from './presentation';
import { formatSingaporeTime } from "@/services/time";

export default function CitySituationHeader() {
  const { report } = useAppStore();

  const badgeStatus: Record<string, string> = {
    CRITICAL: 'critical',
    HIGH: 'high',
    MODERATE: 'elevated',
    ELEVATED: 'elevated',
    LOW: 'normal',
    NORMAL: 'normal',
  };

  const getRiskIcon = (risk?: string) => {
    switch (risk) {
      case 'CRITICAL': return <ShieldAlert className="text-rose-600" size={28} />;
      case 'HIGH': return <AlertTriangle className="text-orange-600" size={28} />;
      case 'MODERATE':
      case 'ELEVATED': return <AlertTriangle className="text-amber-600" size={28} />;
      case 'LOW': return <Info className="text-blue-600" size={28} />;
      case 'NORMAL': return <CheckCircle className="text-emerald-600" size={28} />;
      default: return <Info className="text-slate-500" size={28} />;
    }
  };

  if (!report) {
    return (
      <div className="card-panel p-6 animate-pulse">
        <div className="h-6 w-48 bg-slate-200 rounded mb-4" />
        <div className="h-4 w-96 bg-slate-200 rounded" />
      </div>
    );
  }

  const risk = report.overall_risk_level;

  return (
    <div className="card-panel p-6">
      <div className="flex items-start justify-between gap-6">
        <div className="flex items-center space-x-4">
          {getRiskIcon(risk)}
          <div>
            <h2 className="text-[10px] font-bold text-slate-500 tracking-widest uppercase mb-1">
              Singapore City Situation
            </h2>
            <div className="flex items-center space-x-3">
              <span className="text-slate-900 text-2xl font-bold">OVERALL RISK</span>
              <span className={statusBadgeClass(badgeStatus[risk])}>{risk}</span>
            </div>
          </div>
        </div>

        <div className="text-right max-w-md">
          <p className="text-slate-600 text-sm italic border-l-2 border-slate-200 pl-3">
            &quot;{report.city_level_recommendations?.[0] || 'Monitoring standard city operations.'}&quot;
          </p>
          <div className="text-xs text-slate-500 mt-2 font-mono">
            UPDATED: {formatSingaporeTime(report.generated_at)} SGT
          </div>
        </div>
      </div>

      {report.priority_incidents?.length > 0 && (
        <div className="mt-4 pt-4 border-t border-slate-100 flex space-x-4">
          <span className="text-xs font-bold text-slate-500 tracking-wider uppercase">Active Incidents</span>
          <span className="text-xs text-rose-600 font-bold">{report.priority_incidents.length} Critical Issues</span>
        </div>
      )}
    </div>
  );
}
