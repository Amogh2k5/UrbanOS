"use client";

import { useAppStore } from '@/store';
import { Server, CheckCircle, XCircle } from 'lucide-react';

export default function SystemHealth() {
  const { report, isLive } = useAppStore();

  const getStatusIcon = (status: boolean) => {
    return status 
      ? <CheckCircle size={14} className="text-[var(--color-primary)]" />
      : <XCircle size={14} className="text-[var(--color-severity-critical)]" />;
  };

  return (
    <div className="glass-panel p-4 rounded-xl border border-gray-800/50 mt-4">
      <div className="flex items-center space-x-2 mb-3">
        <Server size={16} className="text-gray-400" />
        <h3 className="font-heading font-bold text-xs tracking-widest text-gray-400 uppercase">System Health</h3>
      </div>
      
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="flex items-center space-x-2">
          {getStatusIcon(report?.domain_status?.environment?.available ?? false)}
          <span className="text-xs text-gray-300">Environment Agent</span>
        </div>
        <div className="flex items-center space-x-2">
          {getStatusIcon(report?.domain_status?.traffic?.available ?? false)}
          <span className="text-xs text-gray-300">Traffic Agent</span>
        </div>
        <div className="flex items-center space-x-2">
          {getStatusIcon(report?.domain_status?.flood?.available ?? false)}
          <span className="text-xs text-gray-300">Flood Agent</span>
        </div>
        <div className="flex items-center space-x-2">
          {getStatusIcon(!!report)}
          <span className="text-xs text-gray-300">City Coordinator</span>
        </div>
      </div>
      
      <div className="mt-3 pt-3 border-t border-gray-800 flex justify-between items-center text-[10px] text-gray-500 font-mono">
        <span>API CONNECTIVITY: {isLive ? 'ESTABLISHED' : 'CONNECTING...'}</span>
        <span>LAST REFRESH: {report ? new Date(report.generated_at).toLocaleTimeString() : '--:--:--'}</span>
      </div>
    </div>
  );
}
