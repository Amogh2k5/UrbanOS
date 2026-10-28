"use client";

import { useAppStore } from '@/store';
import { DomainStatus } from '@/types';
import { Cloud, Car, Droplets } from 'lucide-react';
import { solidCardClass } from '@/components/city/presentation';

interface DomainPanelProps {
  title: string;
  /** Domain id - keeps operational summary cards distinct by system. */
  domainId: string;
  status: DomainStatus | undefined;
  icon: React.ReactNode;
}

function DomainPanel({ title, domainId, status, icon }: DomainPanelProps) {
  if (!status) return null;

  const risk = status.overall_risk || 'NORMAL';
  // Risk lives in the badge, never in the card colour.
  const badge =
    risk === 'CRITICAL' ? 'badge-critical'
      : risk === 'HIGH' ? 'badge-high'
        : risk === 'ELEVATED' || risk === 'MODERATE' ? 'badge-elevated'
          : 'badge-normal';

  return (
    <div className={solidCardClass(domainId, 'p-5')}>
      <div className="absolute inset-0 card-pattern opacity-30" aria-hidden="true" />
      <div className="relative z-10">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center space-x-3">
            <div className="p-2 bg-white/20 text-white rounded-lg">{icon}</div>
            <h3 className="font-heading font-bold text-sm tracking-widest text-white uppercase">{title}</h3>
          </div>
          <span className={`status-badge ${badge}`}>{risk}</span>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-xs text-white/90 font-bold tracking-wider mb-1">STATUS</div>
            <div className="text-sm text-white">{status.overall_status || 'Operational'}</div>
          </div>
          <div>
            <div className="text-xs text-white/90 font-bold tracking-wider mb-1">ALERTS</div>
            <div className="text-sm text-white">{status.active_alert_count || 0} Active</div>
          </div>
        </div>

        <div className="mt-4 pt-4 border-t border-white/20">
          <div className="text-xs text-white/90 font-bold tracking-wider mb-2">KEY METRICS</div>
          <div className="flex flex-col space-y-2">
            {Object.entries(status.key_metrics || {}).slice(0, 2).map(([key, value]) => (
              <div key={key} className="flex justify-between items-center text-sm">
                <span className="text-white/90 capitalize">{key.replace(/_/g, ' ')}</span>
                <span className="text-white font-mono">{String(value)}</span>
              </div>
            ))}
          </div>
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
      <DomainPanel title="Traffic" domainId="traffic" status={report.domain_status?.traffic} icon={<Car size={20} />} />
      <DomainPanel title="Environment" domainId="pm25" status={report.domain_status?.environment} icon={<Cloud size={20} />} />
      <DomainPanel title="Flood" domainId="flood" status={report.domain_status?.flood} icon={<Droplets size={20} />} />
    </div>
  );
}
