"use client";

/**
 * Alerts section for the Overview page.
 * Displays active alerts from the overview API response.
 */
import React from "react";
import { AlertTriangle, MapPin, Clock, X } from "lucide-react";
import type { AlertItem } from "@/services/api";

interface Props {
  alerts: AlertItem[];
  onDismiss?: (alertId: string) => void;
}

const DOMAIN_LABELS: Record<string, string> = {
  traffic: "Traffic", roads: "Roads", transit: "Transit", pm25: "Air Quality",
  weather: "Weather", flood: "Flood", fire: "Fire", crime: "Crime",
  water: "Water", waste: "Waste", energy: "Energy", land: "Land Use",
  housing: "Housing", construction: "Construction",
};

function cleanAlertText(value?: string | null): string {
  if (!value) return "Data currently unavailable";
  const text = value
    .replace(/\b[\w]*_?(?:id|uuid|debug|metadata|source_status)\s*[:=]\s*[^,;\s]+/gi, "")
    .replace(/\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b/gi, "")
    .replaceAll("_", " ")
    .replace(/\s+/g, " ").trim();
  if (!text || text.startsWith("{") || text.startsWith("[") || /"\w+"\s*:/.test(text)) return "Data currently unavailable";
  return text;
}

function formatRelativeTime(timestamp: string): string {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "";

  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMinutes = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMinutes / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMinutes < 1) return "Just now";
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString("en-SG", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function severityBadgeClass(severity: string): string {
  const base = "inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold tracking-wider";
  switch ((severity || "").toUpperCase()) {
    case "CRITICAL":
      return `${base} bg-rose-100 text-rose-800 border border-rose-200`;
    case "HIGH":
      return `${base} bg-orange-100 text-orange-800 border border-orange-200`;
    case "MODERATE":
      return `${base} bg-amber-100 text-amber-800 border border-amber-200`;
    case "LOW":
      return `${base} bg-blue-100 text-blue-800 border border-blue-200`;
    default:
      return `${base} bg-slate-100 text-slate-700 border border-slate-200`;
  }
}

export default function Alerts({ alerts, onDismiss }: Props) {
  if (!alerts || alerts.length === 0) {
    return (
      <section data-testid="overview-alerts" className="card-panel p-4">
        <div className="flex items-center justify-between gap-4">
          <h3 className="font-heading font-bold text-sm text-slate-700 uppercase tracking-wider">
            Alerts
          </h3>
        </div>
        <p className="text-xs text-slate-500 mt-2">No active alerts</p>
      </section>
    );
  }

  // Sort by severity (critical first) then by timestamp (newest first)
  const severityOrder: Record<string, number> = {
    CRITICAL: 0,
    HIGH: 1,
    MODERATE: 2,
    LOW: 3,
  };

  const sortedAlerts = [...alerts].sort((a, b) => {
    const severityA = severityOrder[a.severity?.toUpperCase() || ""] ?? 99;
    const severityB = severityOrder[b.severity?.toUpperCase() || ""] ?? 99;
    if (severityA !== severityB) return severityA - severityB;
    // Then by timestamp (newest first)
    const timeA = new Date(a.timestamp).getTime();
    const timeB = new Date(b.timestamp).getTime();
    return timeB - timeA;
  });

  return (
    <section data-testid="overview-alerts" className="card-panel p-4">
      <h3 className="font-heading font-bold text-sm text-slate-700 uppercase tracking-wider mb-3 flex items-center gap-2">
        <span className="w-5 h-5 rounded-full bg-red-100 text-red-600 flex items-center justify-center">
          <AlertTriangle size={12} className="text-red-600" />
        </span>
        Alerts
      </h3>

      <ul className="space-y-2" role="list" aria-label="Active alerts">
        {sortedAlerts.map((alert, index) => (
          <li
            key={alert.id || `${alert.domain}-${index}`}
            className="group rounded-lg border border-slate-200 bg-white p-3 transition-shadow hover:shadow-sm"
          >
            <div className="flex flex-wrap items-start gap-3">
              <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-red-100 text-red-600 flex items-center justify-center">
                <AlertTriangle size={14} className="text-red-600" />
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2 mb-1">
                  <h4 className="font-semibold text-slate-900 text-sm">
                    {cleanAlertText(alert.title)}
                  </h4>
                  <span className={severityBadgeClass(alert.severity)}>
                    {alert.severity ? alert.severity.charAt(0) + alert.severity.slice(1).toLowerCase() : "Unspecified"}
                  </span>
                  {DOMAIN_LABELS[alert.domain?.toLowerCase() ?? ""] && (
                    <span className="text-[10px] font-medium text-slate-500 uppercase tracking-wider bg-slate-100 px-1.5 py-0.5 rounded">
                      {DOMAIN_LABELS[alert.domain.toLowerCase()]}
                    </span>
                  )}
                </div>

                <p className="text-slate-600 text-sm leading-relaxed">
                  {cleanAlertText(alert.description)}
                </p>

                {alert.affected_zones?.length > 0 && (
                  <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px] text-slate-500">
                    <MapPin size={10} className="shrink-0" />
                    <span className="flex flex-wrap gap-1">
                      {alert.affected_zones.map((zone, i) => (
                        <span key={i} className="bg-slate-100 px-1.5 py-0.5 rounded text-slate-700">
                          {cleanAlertText(zone)}
                        </span>
                      ))}
                    </span>
                  </div>
                )}

                {alert.timestamp && (
                  <div className="mt-2 flex items-center gap-1.5 text-[10px] text-slate-500">
                    <Clock size={10} className="shrink-0" />
                    <span>{formatRelativeTime(alert.timestamp)}</span>
                    {alert.id && onDismiss && (
                      <React.Fragment>
                        <span className="mx-1">|</span>
                        <button
                          type="button"
                          onClick={() => onDismiss?.(alert.id!)}
                          className="text-slate-500 hover:text-slate-600 transition-colors"
                          aria-label="Dismiss alert"
                        >
                          <X size={10} />
                        </button>
                      </React.Fragment>
                    )}
                  </div>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
