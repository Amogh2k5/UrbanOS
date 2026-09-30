"use client";

import { useAppStore } from '@/store';
import { Bot, Crosshair, AlertOctagon, BrainCircuit } from 'lucide-react';

export default function CoordinatorBriefing() {
  const { report } = useAppStore();

  if (!report) return null;

  return (
    <div className="glass-panel p-6 rounded-xl flex flex-col h-full border border-[var(--color-primary-dim)]/30">
      <div className="flex items-center space-x-3 mb-6 pb-4 border-b border-[var(--color-primary-dim)]/20">
        <div className="p-2 bg-[var(--color-primary-dim)]/10 rounded-lg">
          <Bot className="text-[var(--color-primary)]" size={24} />
        </div>
        <h3 className="font-heading font-bold text-lg tracking-wide text-white">CITY COORDINATOR</h3>
      </div>

      <div className="space-y-6 flex-grow">
        {/* Priority Issue */}
        {report.priority_incidents?.[0] && (
          <div>
            <div className="flex items-center space-x-2 mb-2">
              <AlertOctagon size={16} className="text-[var(--color-severity-high)]" />
              <span className="text-xs font-bold text-gray-400 tracking-wider">PRIORITY ISSUE</span>
            </div>
            <p className="text-sm text-gray-200">
              <span className="text-white font-semibold">{report.priority_incidents[0].type}</span> — {report.priority_incidents[0].affected_zones.join(', ')}
            </p>
          </div>
        )}

        {/* Cross Domain Impact */}
        {report.cross_domain_impacts?.[0] && (
          <div>
            <div className="flex items-center space-x-2 mb-2">
              <Crosshair size={16} className="text-[var(--color-severity-moderate)]" />
              <span className="text-xs font-bold text-gray-400 tracking-wider">CROSS-DOMAIN IMPACT</span>
            </div>
            <p className="text-sm text-gray-200 font-mono">
              {report.cross_domain_impacts[0].domains_involved.join(' + ').toUpperCase()}
            </p>
            <p className="text-xs text-gray-400 mt-1">
              {report.cross_domain_impacts[0].description}
            </p>
          </div>
        )}

        {/* AI Situation */}
        <div>
          <div className="flex items-center space-x-2 mb-2">
            <BrainCircuit size={16} className="text-[var(--color-primary)]" />
            <span className="text-xs font-bold text-gray-400 tracking-wider">AI SITUATION & RECOMMENDATION</span>
          </div>
          <div className="bg-[var(--color-surface-lowest)] p-4 rounded-lg border border-[var(--color-surface-high)]">
            <p className="text-sm text-gray-300 mb-3 italic">
              &quot;Condition analysis indicates {report.overall_city_status.toLowerCase()} operational state due to overlapping domain alerts.&quot;
            </p>
            <div className="text-sm font-semibold text-[var(--color-primary)]">
              {report.city_level_recommendations?.[0] || 'Maintain current operational posture.'}
            </div>
          </div>
        </div>
      </div>

      {/* Meta */}
      <div className="mt-6 pt-4 border-t border-gray-800/50 flex items-center justify-between text-xs text-gray-500 font-mono">
        <span>CONFIDENCE: {report.confidence.toUpperCase()}</span>
        <span>AFFECTED ZONES: {report.affected_zones.length}</span>
      </div>
    </div>
  );
}
