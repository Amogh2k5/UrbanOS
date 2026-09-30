"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  AlertCircle,
  Bus,
  Clock3,
  ExternalLink,
  Gauge,
  Train,
  X,
} from "lucide-react";

interface TrainAlert {
  line: string;
  direction: string | null;
  station: string | null;
  message: string;
  status: string | null;
  category: string;
}

interface TransitStatus {
  generated_at: string;
  bus_services_count: number;
  bus_routes_count: number;
  bus_stops_count: number;
  active_train_alerts: number;
  train_alerts: TrainAlert[];
  limitations: string[];
}

type RailLine = {
  code: string;
  name: string;
  color: string;
  operator: string;
};

const RAIL_LINES: RailLine[] = [
  { code: "NSL", name: "North-South Line", color: "#d71920", operator: "SMRT" },
  { code: "EWL", name: "East-West Line", color: "#159447", operator: "SMRT" },
  { code: "NEL", name: "North East Line", color: "#8b2bbf", operator: "SBS Transit" },
  { code: "CCL", name: "Circle Line", color: "#f0a31a", operator: "SMRT" },
  { code: "DTL", name: "Downtown Line", color: "#2469c9", operator: "SBS Transit" },
  { code: "TEL", name: "Thomson-East Coast Line", color: "#9a6a2f", operator: "SMRT" },
  { code: "BPLRT", name: "Bukit Panjang LRT", color: "#6f8d7a", operator: "SMRT" },
  { code: "SKLRT", name: "Sengkang LRT", color: "#5f8772", operator: "SBS Transit" },
  { code: "PGLRT", name: "Punggol LRT", color: "#9aa56d", operator: "SBS Transit" },
];

// Current Singapore rail system map. The source map is a CC BY-SA 3.0 work
// maintained on Wikimedia Commons and is used here as a static visual map;
// live operational status continues to come from the UrbanOS Transit API.
const SYSTEM_MAP_URL =
  "https://upload.wikimedia.org/wikipedia/commons/6/68/Singapore_MRT_and_LRT_System_Map.svg";
const SYSTEM_MAP_SOURCE =
  "https://commons.wikimedia.org/wiki/File:Singapore_MRT_and_LRT_System_Map.svg";

function normalise(value: string | null | undefined): string {
  return (value ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

function alertMatchesLine(alert: TrainAlert, line: RailLine): boolean {
  const lineText = normalise(`${alert.line} ${alert.message}`);
  const code = normalise(line.code);
  const name = normalise(line.name);

  if (!lineText || lineText.includes("unknown")) return false;
  return lineText.includes(code) || lineText.includes(name) ||
    (line.code === "NEL" && lineText.includes("northeast")) ||
    (line.code === "NSL" && lineText.includes("northsouth")) ||
    (line.code === "EWL" && lineText.includes("eastwest")) ||
    (line.code === "CCL" && lineText.includes("circleline")) ||
    (line.code === "DTL" && lineText.includes("downtownline")) ||
    (line.code === "TEL" && lineText.includes("thomsoneastcoast"));
}

function getLineAlerts(line: RailLine, alerts: TrainAlert[]): TrainAlert[] {
  return alerts.filter((alert) => alertMatchesLine(alert, line));
}

function Kpi({
  label,
  value,
  icon,
  alert = false,
  detail,
}: {
  label: string;
  value: string | number;
  icon: ReactNode;
  alert?: boolean;
  detail?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-800/90 bg-[#0b111d] px-4 py-3.5">
      <div className="flex items-center justify-between text-slate-500">
        <span className="text-[10px] uppercase tracking-[0.16em]">{label}</span>
        {icon}
      </div>
      <div className={`mt-1.5 text-2xl font-bold ${alert ? "text-orange-300" : "text-white"}`}>
        {typeof value === "number" ? value.toLocaleString() : value}
      </div>
      {detail && <div className="mt-0.5 text-[10px] text-slate-500">{detail}</div>}
    </div>
  );
}

function RailLineList({ lines, alerts }: { lines: RailLine[]; alerts: TrainAlert[] }) {
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {lines.map((line) => {
        const lineAlerts = getLineAlerts(line, alerts);
        const affected = lineAlerts.length > 0;
        return (
          <div
            key={line.code}
            className="flex items-center gap-3 rounded-lg border border-slate-800 bg-[#0d1422] px-3 py-2.5"
          >
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: line.color }} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-slate-200">{line.code}</span>
                {affected && (
                  <span className="rounded-full bg-orange-400/10 px-1.5 py-0.5 text-[9px] font-semibold text-orange-300">
                    ALERT
                  </span>
                )}
              </div>
              <div className="truncate text-[10px] text-slate-500">{line.name}</div>
            </div>
            <span className={`text-[10px] font-semibold ${affected ? "text-orange-300" : "text-emerald-400"}`}>
              {affected ? `${lineAlerts.length} alert${lineAlerts.length === 1 ? "" : "s"}` : "Normal"}
            </span>
          </div>
        );
      })}
    </div>
  );
}


function RailStatusGrid({ alerts }: { alerts: TrainAlert[] }) {
  const mrtLines = RAIL_LINES.filter((line) => ["NSL", "EWL", "NEL", "CCL", "DTL", "TEL"].includes(line.code));
  const lrtLines = RAIL_LINES.filter((line) => ["BPLRT", "SKLRT", "PGLRT"].includes(line.code));

  return (
    <div className="rounded-xl border border-slate-800/90 bg-[#0b111d] p-4">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-white">Rail line status</div>
          <div className="mt-0.5 text-[11px] text-slate-500">MRT and LRT status from known live alerts</div>
        </div>
        <Train size={17} className="text-slate-500" />
      </div>

      <section>
        <div className="mb-2 flex items-center gap-2">
          <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400">MRT · 6 lines</span>
        </div>
        <RailLineList lines={mrtLines} alerts={alerts} />
      </section>

      <section className="mt-5 border-t border-slate-800 pt-4">
        <div className="mb-2 flex items-center gap-2">
          <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400">LRT · 3 networks</span>
        </div>
        <RailLineList lines={lrtLines} alerts={alerts} />
      </section>
    </div>
  );
}

type AlertCategory = "bus" | "metro" | "rail";

function classifyAlert(alert: TrainAlert): AlertCategory {
  const text = normalise(`${alert.line} ${alert.message} ${alert.station}`);

  // Bus disruptions can appear in the existing train-alert feed, so classify
  // them from the actual alert text instead of trusting the API field name.
  if (
    text.includes("busservice") ||
    text.includes("busroute") ||
    text.includes("busstop") ||
    text.includes("busdiversion") ||
    text.includes("bus")
  ) {
    return "bus";
  }

  const mrtCodes = ["NSL", "EWL", "NEL", "CCL", "DTL", "TEL"].map(normalise);
  const mrtNames = RAIL_LINES.filter((line) => ["NSL", "EWL", "NEL", "CCL", "DTL", "TEL"].includes(line.code))
    .map((line) => normalise(line.name));

  if (
    mrtCodes.some((code) => text.includes(code)) ||
    mrtNames.some((name) => text.includes(name)) ||
    text.includes("mrt") ||
    text.includes("metro")
  ) {
    return "metro";
  }

  return "rail";
}

const ALERT_CATEGORY_META: Record<AlertCategory, { label: string; icon: ReactNode; color: string }> = {
  bus: { label: "Bus", icon: <Bus size={14} />, color: "text-cyan-300" },
  metro: { label: "Metro / MRT", icon: <Train size={14} />, color: "text-orange-300" },
  rail: { label: "Rail / LRT", icon: <Train size={14} />, color: "text-violet-300" },
};

function AlertGroup({
  category,
  alerts,
  onSelect,
}: {
  category: AlertCategory;
  alerts: TrainAlert[];
  onSelect: (alert: TrainAlert) => void;
}) {
  const meta = ALERT_CATEGORY_META[category];

  return (
    <div className="border-b border-slate-800 last:border-b-0">
      <div className="flex items-center justify-between px-4 py-2.5">
        <div className={`flex items-center gap-2 text-xs font-semibold ${meta.color}`}>
          {meta.icon}
          <span>{meta.label}</span>
        </div>
        <span className="text-[10px] font-semibold text-slate-500">{alerts.length}</span>
      </div>

      {alerts.length === 0 ? (
        <div className="px-4 pb-3 text-[11px] text-slate-600">No active alerts.</div>
      ) : (
        alerts.slice(0, 5).map((alert, index) => (
          <button
            key={`${category}-${alert.line}-${index}`}
            type="button"
            onClick={() => onSelect(alert)}
            className="w-full border-t border-slate-800/70 px-4 py-3 text-left transition hover:bg-slate-800/35"
          >
            <div className="flex items-center gap-2 text-[11px] font-semibold text-slate-300">
              <AlertCircle size={12} className="shrink-0 text-orange-300" />
              <span>{alert.line || (category === "bus" ? "Bus network" : category === "metro" ? "Metro network" : "Rail network")}</span>
              {alert.status && <span className="text-[9px] uppercase text-slate-500">{alert.status}</span>}
            </div>
            <div className="mt-1 line-clamp-2 text-xs leading-5 text-slate-400">{alert.message}</div>
            {alert.station && <div className="mt-1 text-[10px] text-slate-600">Station: {alert.station}</div>}
          </button>
        ))
      )}
    </div>
  );
}

function AlertsPanel({
  alerts,
  onSelect,
}: {
  alerts: TrainAlert[];
  onSelect: (alert: TrainAlert) => void;
}) {
  const grouped = useMemo(() => {
    const result: Record<AlertCategory, TrainAlert[]> = { bus: [], metro: [], rail: [] };
    alerts.forEach((alert) => result[classifyAlert(alert)].push(alert));
    return result;
  }, [alerts]);

  return (
    <div className="overflow-hidden rounded-xl border border-slate-800/90 bg-[#0b111d]">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <div>
          <div className="text-sm font-semibold text-white">Active transit alerts</div>
          <div className="text-[10px] text-slate-500">Separated by bus, metro, and rail</div>
        </div>
        <span className="text-xs font-semibold text-orange-300">{alerts.length}</span>
      </div>

      <AlertGroup category="bus" alerts={grouped.bus} onSelect={onSelect} />
      <AlertGroup category="metro" alerts={grouped.metro} onSelect={onSelect} />
      <AlertGroup category="rail" alerts={grouped.rail} onSelect={onSelect} />
    </div>
  );
}

function BusNetworkPanel({ status }: { status: TransitStatus | null }) {
  return (
    <div className="rounded-xl border border-slate-800/90 bg-[#0b111d] p-4">
      <div className="flex items-center gap-2">
        <Bus size={17} className="text-cyan-300" />
        <div>
          <div className="text-sm font-semibold text-white">Bus network</div>
          <div className="text-[10px] text-slate-500">Operational counts only — routes stay off the rail map</div>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-3">
        <Metric label="Services" value={status?.bus_services_count ?? 0} />
        <Metric label="Routes" value={status?.bus_routes_count ?? 0} />
        <Metric label="Stops" value={status?.bus_stops_count ?? 0} />
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-wider text-slate-600">{label}</div>
      <div className="mt-1 text-lg font-bold text-white">{value.toLocaleString()}</div>
    </div>
  );
}

function RailMap({ alerts }: { alerts: TrainAlert[] }) {
  const affected = RAIL_LINES.filter((line) => getLineAlerts(line, alerts).length > 0);

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-800 bg-white shadow-2xl">
      <div className="flex items-center justify-between gap-4 border-b border-slate-200 bg-white px-5 py-4">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">UrbanOS rail network</div>
          <h3 className="text-xl font-bold text-slate-900">Singapore MRT & LRT</h3>
          <p className="mt-0.5 text-xs text-slate-500">Complete rail system map with live operational status alongside it</p>
        </div>
        <div className="hidden items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-[10px] font-semibold text-slate-600 sm:flex">
          <span className={`h-2 w-2 rounded-full ${affected.length ? "bg-orange-400" : "bg-emerald-500"}`} />
          {affected.length ? `${affected.length} affected line${affected.length === 1 ? "" : "s"}` : "Network normal"}
        </div>
      </div>

      <div className="relative bg-[#f4f7f8] p-3 sm:p-5">
        <div className="relative overflow-hidden rounded-xl border border-slate-200 bg-white">
          <img
            src={SYSTEM_MAP_URL}
            alt="Singapore MRT and LRT system map"
            className="block h-auto w-full"
            draggable={false}
          />
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-white/5 via-transparent to-white/10" />
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[10px] text-slate-500">
          <span>System map is static; live operational state is shown in the UrbanOS panels.</span>
          <a
            href={SYSTEM_MAP_SOURCE}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 hover:text-slate-800"
          >
            Map source <ExternalLink size={11} />
          </a>
        </div>
      </div>
    </div>
  );
}

export default function TransitMap() {
  const [status, setStatus] = useState<TransitStatus | null>(null);
  const [alerts, setAlerts] = useState<TrainAlert[]>([]);
  const [selectedAlert, setSelectedAlert] = useState<TrainAlert | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(`${apiBase}/api/mobility/transit/status?limit_alerts=50`, {
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Transit status request failed");
      const data: TransitStatus = await response.json();
      setStatus(data);
      setAlerts(data.train_alerts || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load transit status");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      if (!cancelled) {
        await loadData();
      }
    };
    load();
    const timer = window.setInterval(async () => {
      if (!cancelled) {
        await loadData();
      }
    }, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [loadData]);

  const affectedLines = useMemo(
    () => RAIL_LINES.filter((line) => getLineAlerts(line, alerts).length > 0).length,
    [alerts],
  );

  if (loading) {
    return (
      <div className="min-h-[650px] rounded-2xl border border-slate-800 bg-[#070c16] flex items-center justify-center text-slate-400">
        Loading transit operations…
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-[650px] rounded-2xl border border-slate-800 bg-[#070c16] flex flex-col items-center justify-center p-6 text-center">
        <AlertCircle className="mb-3 text-red-400" size={38} />
        <div className="font-semibold text-white">Transit operations unavailable</div>
        <div className="mt-1 text-sm text-slate-400">Unable to load the live transit status.</div>
        <button
          type="button"
          onClick={() => {
            setLoading(true);
            void loadData();
          }}
          className="mt-4 rounded-lg bg-cyan-400 px-4 py-2 font-semibold text-slate-950"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="w-full rounded-2xl border border-slate-800 bg-[#070c16] p-4 text-white shadow-xl lg:p-5">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-bold tracking-tight">Transit Operations</h2>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2.5 py-1 text-xs font-semibold text-emerald-300">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" /> LIVE
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-500">Singapore rail network, live train alerts, and bus operations</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <Clock3 size={14} />
          {status ? new Date(status.generated_at).toLocaleString("en-SG", { timeZone: "Asia/Singapore" }) : "—"}
        </div>
      </header>

      <div className="mb-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Kpi label="MRT" value={6} icon={<Train size={17} />} detail="6 main metro lines" />
          <Kpi label="LRT" value={3} icon={<Train size={17} />} detail="3 local rail networks" />
        <Kpi label="Rail alerts" value={alerts.length} icon={<AlertCircle size={17} />} alert={alerts.length > 0} detail={`${affectedLines} known affected line${affectedLines === 1 ? "" : "s"}`} />
        <Kpi label="Bus services" value={status?.bus_services_count ?? 0} icon={<Bus size={17} />} detail="Current stored network" />
        <Kpi label="Bus stops" value={status?.bus_stops_count ?? 0} icon={<Bus size={17} />} detail="Current stored network" />
      </div>

      <div className="grid grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,1fr)_360px]">
        <RailMap alerts={alerts} />

        <aside className="space-y-4">
          <div className="rounded-xl border border-slate-800 bg-[#0b111d] p-4">
            <div className="flex items-start gap-3">
              <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${alerts.length ? "bg-orange-400" : "bg-emerald-400"}`} />
              <div>
                <div className="font-semibold text-white">{alerts.length ? "Network attention" : "Network normal"}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">
                  {alerts.length
                    ? `${alerts.length} live rail alert${alerts.length === 1 ? "" : "s"} currently available.`
                    : "No active rail alerts currently available."}
                </div>
              </div>
            </div>
          </div>

          <RailStatusGrid alerts={alerts} />
          <AlertsPanel alerts={alerts} onSelect={setSelectedAlert} />
          <BusNetworkPanel status={status} />
        </aside>
      </div>

      <footer className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-[#0b111d] px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Gauge size={16} className="text-cyan-300" />
          Operations view
        </div>
        <div className="text-xs text-slate-500">
          Static network map + live status API. No bus route geometry is shown here.
        </div>
      </footer>

      {selectedAlert && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => setSelectedAlert(null)}
        >
          <div
            className="w-full max-w-lg rounded-2xl border border-slate-700 bg-[#0b111d] shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between border-b border-slate-800 p-5">
              <div>
                <div className="flex items-center gap-2 text-orange-300">
                  <AlertCircle size={18} />
                  <span className="font-semibold">{ALERT_CATEGORY_META[classifyAlert(selectedAlert)].label} alert</span>
                </div>
                <div className="mt-1 text-lg font-bold text-white">{selectedAlert.line || "Train network"}</div>
              </div>
              <button type="button" onClick={() => setSelectedAlert(null)} className="text-slate-500 hover:text-white">
                <X size={18} />
              </button>
            </div>
            <div className="space-y-3 p-5">
              {selectedAlert.station && <Info label="Station" value={selectedAlert.station} />}
              {selectedAlert.direction && <Info label="Direction" value={selectedAlert.direction} />}
              {selectedAlert.status && <Info label="Status" value={selectedAlert.status} />}
              <Info label="Message" value={selectedAlert.message} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-[#0d1422] p-3">
      <div className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className="whitespace-pre-wrap text-sm text-slate-200">{value}</div>
    </div>
  );
}
