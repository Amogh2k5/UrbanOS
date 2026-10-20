"use client";

import { useAppStore } from '@/store';
import { Server, CheckCircle, XCircle } from 'lucide-react';
import { formatSingaporeTime } from "@/services/time";

export default function SystemHealth() {
  const { report, isLive } = useAppStore();

  const getStatusIcon = (status: boolean) => {
    return status 
      ? <CheckCircle size={14} className="text-[var(--color-primary)]" />
      : <XCircle size={14} className="text-[var(--color-severity-critical)]" />;
  };

  return (
    <div className="card-panel p-4 rounded-xl border border-slate-200 mt-4">
      <div className="flex items-center space-x-2 mb-3">
        <Server size={16} className="text-slate-500" />
        <h3 className="font-heading font-bold text-xs tracking-widest text-slate-500 uppercase">System Health</h3>
      </div>
      
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="flex items-center space-x-2">
          {getStatusIcon(report?.domain_status?.environment?.available ?? false)}
          <span className="text-xs text-slate-600">Environment Agent</span>
        </div>
        <div className="flex items-center space-x-2">
          {getStatusIcon(report?.domain_status?.traffic?.available ?? false)}
          <span className="text-xs text-slate-600">Traffic Agent</span>
        </div>
        <div className="flex items-center space-x-2">
          {getStatusIcon(report?.domain_status?.flood?.available ?? false)}
          <span className="text-xs text-slate-600">Flood Agent</span>
        </div>
        <div className="flex items-center space-x-2">
          {getStatusIcon(!!report)}
          <span className="text-xs text-slate-600">City Coordinator</span>
        </div>
      </div>
      
      <div className="mt-3 pt-3 border-t border-slate-200 flex justify-between items-center text-[10px] text-slate-500 font-mono">
        <span>API CONNECTIVITY: {isLive ? 'ESTABLISHED' : 'CONNECTING...'}</span>
        <span>LAST REFRESH: {report ? `${formatSingaporeTime(report.generated_at)} SGT` : '--:--:--'}</span>
      </div>
    </div>
  );
}
