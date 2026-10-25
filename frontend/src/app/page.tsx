"use client";

/**
 * UrbanOS City Overview.
 *
 * Layout follows the `urbanos_solid_kpis.html` reference, adapted to the
 * existing dark UrbanOS theme and navigation shell:
 *
 *   1. AI City Situation   - grounded narrative from the backend
 *   2. Active Risk Signals - only coordinator impacts that carry evidence
 *   3. Domain Performance  - live KPI cards, each linking to its domain page
 *
 * The landing view reads cached `/api/overview/city` summaries. The full city
 * coordinator is requested only when the user chooses to run an assessment.
 *
 * No intelligence logic lives here. Every value rendered comes from the API.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchCityReport,
  fetchOverviewCity,
  fetchOverviewModule,
  fetchCityNarrative,
  fetchChat,
  ApiError,
} from "@/services/api";
import type { OverviewCityResponse, ModuleDetailResponse } from "@/services/api";
import type { CitySituationReport, DomainStatus } from "@/types/intelligence";
import { useAppStore } from "@/store";
import CitySituationPanel from "@/components/city/CitySituationPanel";
import RiskSignals from "@/components/city/RiskSignals";
import DomainKpiGrid from "@/components/city/DomainKpiGrid";
import KpiInsightPanel from "@/components/city/KpiInsightPanel";
import { formatTimestamp, substantiveFindings } from "@/components/city/presentation";
import { Send, X, MessageSquare, TriangleAlert } from "lucide-react";

export default function OverviewPage() {
  const setReport = useAppStore((s) => s.setReport);

  const [overview, setOverview] = useState<OverviewCityResponse | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);

  const [report, setCityReport] = useState<CitySituationReport | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const [reportLoading, setReportLoading] = useState(false);

  const [insightDomain, setInsightDomain] = useState<string | null>(null);

  const [selectedModule, setSelectedModule] = useState<string | null>(null);
  const [moduleDetail, setModuleDetail] = useState<ModuleDetailResponse | null>(null);
  const [moduleError, setModuleError] = useState<string | null>(null);
  const [moduleLoading, setModuleLoading] = useState(false);

  const [chatOpen, setChatOpen] = useState(false);
  const [chatMessages, setChatMessages] = useState<
    Array<{ role: "user" | "assistant"; text: string }>
  >([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);

  // ------------------------------------------------------------- data loading
  // Loading flags start as `true` in useState, so this never needs a
  // synchronous setState before the first await (which the lint rules and
  // React both discourage inside an effect).
  const load = useCallback(async () => {
    const overviewResult = await Promise.allSettled([fetchOverviewCity()]).then((r) => r[0]);

    if (overviewResult.status === "fulfilled") {
      setOverview(overviewResult.value);
      setOverviewError(null);
    } else {
      const reason = overviewResult.reason;
      setOverviewError(
        reason instanceof ApiError
          ? `API error ${reason.status}`
          : reason instanceof Error
            ? reason.message
            : "Unknown error"
      );
    }

    setOverviewLoading(false);
  }, []);

  useEffect(() => {
    let cancelled = false;
    // `load` performs its setState only after an `await`, so no render is
    // triggered synchronously inside this effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!cancelled) void load();
    return () => {
      cancelled = true;
    };
  }, [load]);

  const requestCityReport = useCallback(async () => {
    setReportLoading(true);
    setReportError(null);
    try {
      const result = await fetchCityReport();
      setCityReport(result);
      setReport(result);
      try {
        const narrative = await fetchCityNarrative();
        if (narrative.city_assessment_ready && narrative.ai_brief) {
          setOverview((prev) => prev ? {
            ...prev,
            ai_brief: narrative.ai_brief,
            city_assessment_ready: true,
          } : prev);
        }
      } catch {
        // The coordinator report remains usable without optional narration.
      }
      // The coordinator cache is now warm: re-read the Overview summaries so
      // the domain cards, findings and assessment-ready flag reflect the run
      // the user just paid for, instead of staying on the cold-cache view.
      try {
        await load();
      } catch {
        // The report above is already rendered; a failed summary refresh
        // leaves the previous cards in place rather than blanking them.
      }
    } catch (reason) {
      setReportError(
        reason instanceof ApiError
          ? `API error ${reason.status}`
          : reason instanceof Error
            ? reason.message
            : "Unknown error"
      );
    } finally {
      setReportLoading(false);
    }
  }, [setReport, load]);

  const loadModuleDetail = useCallback(async (moduleId: string) => {
    setSelectedModule(moduleId);
    setModuleLoading(true);
    setModuleError(null);
    try {
      setModuleDetail(await fetchOverviewModule(moduleId));
    } catch (e) {
      setModuleDetail(null);
      setModuleError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setModuleLoading(false);
    }
  }, []);

  // -------------------------------------------------------------- derived data
  const domainStatus = useMemo(
    () => (overview?.domain_status ?? {}) as Record<string, DomainStatus>,
    [overview?.domain_status]
  );

  const domainsWithFindings = useMemo(() => {
    const set = new Set<string>();
    for (const [id, status] of Object.entries(domainStatus)) {
      if (substantiveFindings(status?.findings).length > 0) set.add(id);
    }
    return set;
  }, [domainStatus]);

  const activeInsight = insightDomain ? domainStatus[insightDomain] : null;

  const submitChat = async () => {
    const message = chatInput.trim();
    if (!message) return;
    setChatInput("");
    setChatLoading(true);
    setChatError(null);

    // Forward bounded history so the Copilot has conversational context.
    // It can never introduce a fact the coordinator report does not contain.
    const history = chatMessages.slice(-6);
    setChatMessages((prev) => [...prev, { role: "user", text: message }]);

    try {
      const res = await fetchChat(message, selectedModule ?? undefined, history);
      setChatMessages((prev) => [...prev, { role: "assistant", text: res.response }]);
    } catch (e) {
      const detail = e instanceof Error ? e.message : "Unknown error";
      setChatError(detail);
      setChatMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text:
            "I could not reach the UrbanOS assistant. The deterministic city " +
            "status and KPI values on this page are unaffected.",
        },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[var(--color-background)]">
      <div className="max-w-6xl mx-auto px-4 lg:px-10 py-8 space-y-8">
        {/* 1. AI City Situation */}
        <CitySituationPanel
          narrative={overview?.ai_brief ?? null}
          report={report}
          assessmentReady={overview?.city_assessment_ready ?? false}
          loading={overviewLoading || reportLoading}
          error={overviewError}
          onRequestReport={requestCityReport}
        />

        {/* 2. Active Risk Signals */}
        <RiskSignals
          impacts={report?.cross_domain_impacts}
          loading={reportLoading}
          error={reportError}
          reportAvailable={Boolean(report) && !reportError}
        />

        {/* 3. Domain Performance */}
        <DomainKpiGrid
          modules={overview?.modules}
          domainsWithFindings={domainsWithFindings}
          onOpenInsight={(id) => setInsightDomain(id)}
        />

        {/* Module detail (existing behaviour, preserved) */}
        {selectedModule && (
          <section
            data-testid="module-detail"
            className="card-panel p-6"
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-heading font-bold text-sm text-slate-800">
                {moduleDetail?.module_name ?? selectedModule} Detail
              </h3>
              <button
                type="button"
                onClick={() => setSelectedModule(null)}
                className="text-slate-500 hover:text-slate-800"
                aria-label="Close module detail"
              >
                <X size={16} />
              </button>
            </div>

            {moduleLoading && (
              <p data-testid="module-detail-loading" className="text-sm text-slate-500 animate-pulse">
                Loading module detail...
              </p>
            )}
            {moduleError && (
              <p data-testid="module-detail-error" className="text-sm text-rose-800 flex items-center gap-2">
                <TriangleAlert size={14} /> {moduleError}
              </p>
            )}
            {moduleDetail && !moduleLoading && (
              <div className="space-y-2 text-sm text-slate-700">
                <p data-testid="module-detail-summary">{moduleDetail.summary}</p>
                <p className="text-xs text-slate-500 font-mono">
                  status: {moduleDetail.status}
                  {moduleDetail.updated_at
                    ? ` · updated ${formatTimestamp(moduleDetail.updated_at)}`
                    : ""}
                </p>
              </div>
            )}
          </section>
        )}

        {/* Alerts (existing behaviour, preserved) */}
        {overview && overview.alerts.length > 0 && (
          <section data-testid="overview-alerts" className="card-panel p-6">
            <h3 className="font-heading font-bold text-sm text-slate-900 mb-3">Alerts</h3>
            <ul className="space-y-2">
              {overview.alerts.map((a, i) => (
                <li
                  key={`${a.domain}-${i}`}
                  className="text-xs text-slate-500 border-l-2 border-slate-200 pl-3"
                >
                  <span className="font-semibold text-slate-800">{a.title}</span>
                  <span className="block text-slate-500">{a.description}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <div className="h-24" />
      </div>

      {/* KPI insight - opened by the card's sparkles action, never by the card */}
      {insightDomain && (
        <KpiInsightPanel
          domainId={insightDomain}
          status={activeInsight}
          onClose={() => setInsightDomain(null)}
        />
      )}

      {/* Copilot (existing behaviour; Phase 5 grounds it) */}
      <button
        type="button"
        onClick={() => setChatOpen((v) => !v)}
        data-testid="copilot-toggle"
        aria-label="Toggle assistant"
        className="fixed bottom-6 right-6 w-14 h-14 bg-indigo-600 text-white rounded-full shadow-lg hover:scale-105 transition-transform z-[100] flex items-center justify-center ring-4 ring-slate-200"
      >
        <MessageSquare size={22} />
      </button>

      {chatOpen && (
        <div
          data-testid="copilot-panel"
          className="fixed bottom-24 right-6 w-[350px] h-[460px] bg-white border border-slate-200 rounded-2xl shadow-2xl flex flex-col z-[90] overflow-hidden"
        >
          <div className="flex items-center justify-between px-5 h-12 border-b border-slate-200 shrink-0">
            <span className="font-bold text-slate-800 text-sm flex items-center">
              <MessageSquare size={15} className="mr-2 text-slate-700" /> Assistant
            </span>
            <button
              type="button"
              onClick={() => setChatOpen(false)}
              className="text-slate-500 hover:text-slate-800"
              aria-label="Close assistant"
            >
              <X size={16} />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-slate-50 custom-scrollbar">
            {chatMessages.length === 0 && (
              <div data-testid="copilot-intro" className="space-y-2">
                <p className="text-xs text-slate-500">
                  Ask about the current city status, a domain, or an active
                  risk signal.
                </p>
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  Answers come only from the deterministic City Coordinator
                  report. If the report does not contain the answer, the
                  assistant will say so rather than guess. Scenario simulation
                  and operational actions are not supported.
                </p>
              </div>
            )}
            {chatMessages.map((m, i) => (
              <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[85%] text-xs rounded-2xl px-3 py-2 leading-relaxed ${
                    m.role === "user"
                      ? "bg-indigo-600 text-white rounded-tr-sm"
                      : "bg-white border border-slate-200 text-slate-600 rounded-tl-sm"
                  }`}
                >
                  {m.text}
                </div>
              </div>
            ))}
            {chatLoading && (
              <p data-testid="copilot-loading" className="text-xs text-slate-500 animate-pulse">
                Checking validated city intelligence...
              </p>
            )}
            {chatError && (
              <p data-testid="copilot-error" className="text-xs text-rose-800">
                {chatError}
              </p>
            )}
          </div>

          <div className="p-3 border-t border-slate-200 flex gap-2 shrink-0">
            <input
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void submitChat();
              }}
              placeholder="Ask about UrbanOS data"
              data-testid="copilot-input"
              className="flex-1 bg-white border border-slate-300 text-slate-800 text-xs rounded-lg px-3 py-2 focus:outline-none"
            />
            <button
              type="button"
              onClick={() => void submitChat()}
              disabled={chatLoading || !chatInput.trim()}
              data-testid="copilot-send"
              className="px-3 bg-indigo-600 text-white rounded-lg disabled:bg-slate-200 disabled:text-slate-500"
              aria-label="Send"
            >
              <Send size={14} />
            </button>
          </div>
        </div>
      )}

      {/* Module detail strip - preserves the existing inline module detail. */}
      {overview && overview.modules.length > 0 && (
        <section data-testid="module-detail-strip" className="flex flex-wrap items-center gap-2">
          <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mr-1">
            Module detail
          </span>
          {overview.modules.map((m) => (
            <button
              key={m.id}
              type="button"
              data-testid={`module-detail-button-${m.id}`}
              onClick={() => void loadModuleDetail(m.id)}
              className={`text-[11px] px-2.5 py-1 rounded-lg border transition-colors ${
                selectedModule === m.id
                  ? "border-[var(--color-primary)] text-[var(--color-primary)]"
                  : "border-slate-300 text-slate-500 hover:text-slate-800 hover:border-slate-400"
              }`}
            >
              {m.name}
            </button>
          ))}
        </section>
      )}
    </div>
  );
}
