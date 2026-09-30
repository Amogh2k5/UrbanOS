"use client";

import { useAppStore } from '@/store';
import { DomainStatus } from '@/types';
import { Cloud, Car, Droplets } from 'lucide-react';

interface DomainPanelProps {
  title: string;
  status: DomainStatus | undefined;
  icon: React.ReactNode;
}

function DomainPanel({ title, status, icon }: DomainPanelProps) {
  if (!status) return null;

  return (
    <div className="glass-panel p-5 rounded-xl border border-gray-800/50 hover:bg-[var(--color-surface-high)] transition-colors">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center space-x-3">
          <div className="p-2 bg-gray-800/50 rounded-lg text-[var(--color-primary)]">
            {icon}
          </div>
          <h3 className="font-heading font-bold text-sm tracking-widest text-white uppercase">{title}</h3>
        </div>
        <div className={`px-2 py-1 rounded text-xs font-bold ${status.overall_risk === 'HIGH' || status.overall_risk === 'CRITICAL' ? 'bg-[var(--color-severity-high)] text-white' : 'bg-gray-800 text-gray-300'}`}>
          {status.overall_risk || 'NORMAL'}
        </div>
      </div>
      
      <div className="grid grid-cols-2 gap-4">
        <div>
          <div className="text-xs text-gray-500 font-bold tracking-wider mb-1">STATUS</div>
          <div className="text-sm text-gray-200">{status.overall_status || 'Operational'}</div>
        </div>
        <div>
          <div className="text-xs text-gray-500 font-bold tracking-wider mb-1">ALERTS</div>
          <div className="text-sm text-gray-200">{status.active_alert_count || 0} Active</div>
        </div>
      </div>

      <div className="mt-4 pt-4 border-t border-gray-800/50">
        <div className="text-xs text-gray-500 font-bold tracking-wider mb-2">KEY METRICS</div>
        <div className="flex flex-col space-y-2">
          {Object.entries(status.key_metrics || {}).slice(0, 2).map(([key, value]) => (
            <div key={key} className="flex justify-between items-center text-sm">
              <span className="text-gray-400 capitalize">{key.replace(/_/g, ' ')}</span>
              <span className="text-white font-mono">{String(value)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function DomainPanels() {
  const { report } = useAppStore();

  if (!report) return null;

  return (
    <div className="flex flex-col space-y-4 h-full">
      <DomainPanel 
        title="Traffic" 
        status={report.domain_status?.traffic} 
        icon={<Car size={20} />} 
      />
      <DomainPanel 
        title="Environment" 
        status={report.domain_status?.environment} 
        icon={<Cloud size={20} />} 
      />
      <DomainPanel 
        title="Flood" 
        status={report.domain_status?.flood} 
        icon={<Droplets size={20} />} 
      />
    </div>
  );
}
