"use client";

import { useAppStore } from '@/store';
import { ShieldAlert, AlertTriangle } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

export default function PriorityIncidentFeed() {
  const { report } = useAppStore();

  if (!report || !report.priority_incidents || report.priority_incidents.length === 0) {
    return (
      <div className="glass-panel p-6 rounded-xl flex items-center justify-center h-full border border-gray-800/50">
        <div className="text-center text-gray-500">
          <ShieldAlert className="mx-auto mb-2 opacity-50" size={32} />
          <p className="text-sm font-bold tracking-widest uppercase">No Active Priority Incidents</p>
        </div>
      </div>
    );
  }

  return (
    <div className="glass-panel p-6 rounded-xl h-full flex flex-col border border-gray-800/50">
      <h3 className="font-heading font-bold text-lg tracking-wide text-white mb-4">PRIORITY INCIDENTS</h3>
      
      <div className="flex-grow overflow-y-auto pr-2 space-y-4 scrollbar-thin scrollbar-thumb-gray-700">
        {report.priority_incidents.map((incident) => (
          <div key={incident.id} className="p-4 rounded-lg bg-[var(--color-surface-low)] border-l-2 border-[var(--color-severity-high)]">
            <div className="flex justify-between items-start mb-2">
              <div className="flex items-center space-x-2">
                <AlertTriangle size={14} className="text-[var(--color-severity-high)]" />
                <span className="text-xs font-bold text-[var(--color-severity-high)] tracking-wider">
                  {incident.severity}
                </span>
                <span className="text-xs text-gray-500">•</span>
                <span className="text-xs font-bold text-gray-400 uppercase tracking-wider">
                  {incident.domain}
                </span>
              </div>
              <span className="text-[10px] text-gray-500 font-mono">
                {incident.id.slice(0, 8)}
              </span>
            </div>
            
            <p className="text-sm text-gray-200 font-medium mb-2 leading-snug">
              {incident.description}
            </p>
            
            <div className="flex items-center justify-between mt-3 text-xs">
              <span className="text-gray-400 font-mono bg-gray-800 px-2 py-0.5 rounded">
                {incident.affected_zones.join(', ')}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
