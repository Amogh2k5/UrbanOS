"use client";

import { useEffect, useState } from 'react';
import {
  fetchOverviewCity,
  fetchOverviewModule,
  OverviewCityResponse,
  ModuleDetailResponse,
  fetchChat,
  ModuleSummary,
  ModuleKPI,
} from '@/services/api';
import {
  Car,
  Truck,
  Train,
  Wind,
  Cloud,
  Droplets,
  FireExtinguisher,
  ShieldAlert,
  AlertTriangle,
  Clock,
  MapPin,
  BarChart,
  TrendingUp,
  List,
  Check,
  FileText,
  ArrowRight,
} from 'lucide-react';

// Module configuration
const MODULES = [
  { id: 'traffic', name: 'Traffic', icon: Car, detailRoute: '/traffic' },
  { id: 'roads', name: 'Roads', icon: Truck, detailRoute: '/roads' },
  { id: 'transit', name: 'Transit', icon: Train, detailRoute: '/transit' },
  { id: 'pm25', name: 'Air Quality', icon: Wind, detailRoute: '/pollution' },
  { id: 'weather', name: 'Weather', icon: Cloud, detailRoute: '/weather' },
  { id: 'flood', name: 'Flood & Rain', icon: Droplets, detailRoute: '/flood' },
  { id: 'fire', name: 'Fire', icon: FireExtinguisher, detailRoute: '/safety/fire' },
];

export default function OverviewPage() {
  // City overview state
  const [overviewCity, setOverviewCity] = useState<OverviewCityResponse | null>(null);
  const [overviewCityError, setOverviewCityError] = useState<string | null>(null);
  const [overviewCityLoading, setOverviewCityLoading] = useState(true);

// Module overview state
  const [selectedModule, setSelectedModule] = useState<string | null>(null);
  const [overviewModule, setOverviewModule] = useState<ModuleDetailResponse | null>(null);
  const [overviewModuleError, setOverviewModuleError] = useState<string | null>(null);
  const [overviewModuleLoading, setOverviewModuleLoading] = useState(false);

  // Chat state
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMessages, setChatMessages] = useState<Array<{role: 'user' | 'assistant', text: string}>>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);

  // Helper function to format an ISO string to HH:MM:SS in Singapore time
  const formatSingaporeTime = (isoString: string | null): string => {
    if (!isoString) return "--";
    const date = new Date(isoString);
    const singaporeTime = new Date(date.toLocaleString("en-US", {timeZone: "Asia/Singapore"}));
    return singaporeTime.toTimeString().slice(0, 8); // HH:MM:SS
  };

  // Fetch city overview on mount
  useEffect(() => {
    let cancelled = false;
    const fetchOverviewCityData = async () => {
      setOverviewCityLoading(true);
      setOverviewCityError(null);
      try {
        const data = await fetchOverviewCity();
        if (!cancelled) {
          setOverviewCity(data);
          setOverviewCityLoading(false);
        }
      } catch (err: any) {
        if (!cancelled) {
          setOverviewCityError(err.message);
          setOverviewCityLoading(false);
        }
      }
    };

    fetchOverviewCityData();

    return () => {
      cancelled = true;
    };
  }, []);

  // Handle module selection
  const handleModuleSelect = (moduleId: string) => {
    setSelectedModule(moduleId);
    setOverviewModule(null);
    setOverviewModuleError(null);
    setOverviewModuleLoading(true);

    // Fetch module overview
    let cancelled = false;
    const fetchOverviewModuleData = async () => {
      try {
        const data = await fetchOverviewModule(moduleId);
        if (!cancelled) {
          setOverviewModule(data);
          setOverviewModuleLoading(false);
        }
      } catch (err: any) {
        if (!cancelled) {
          setOverviewModuleError(err.message);
          setOverviewModuleLoading(false);
        }
      }
    };

    fetchOverviewModuleData();

    return () => {
      cancelled = true;
    };
  };

  // Handle going back to city overview
  const handleBackToOverview = () => {
    setSelectedModule(null);
    setOverviewModule(null);
    setOverviewModuleError(null);
    setOverviewModuleLoading(false);
  };

  // Handle opening the chat panel
  const handleChatOpen = () => {
    setChatOpen(true);
  };

  // Handle closing the chat panel
  const handleChatClose = () => {
    setChatOpen(false);
    setChatInput('');
    setChatError(null);
  };

  // Handle sending a chat message
  const handleChatSend = async () => {
    const message = chatInput.trim();
    if (!message) return;

    setChatLoading(true);
    setChatError(null);

    // Add user message to chat
    setChatMessages(prev => [...prev, {role: 'user', text: message}]);

    try {
      const response = await fetchChat(message, selectedModule || undefined);
      setChatMessages(prev => [...prev, {role: 'assistant', text: response.response}]);
    } catch (err: any) {
      setChatError(err.message);
      setChatMessages(prev => [...prev, {role: 'assistant', text: 'Sorry, I encountered an error. Please try again.'}]);
    } finally {
      setChatLoading(false);
      setChatInput('');
    }
  };

  // Handle key press in chat input
  const handleChatKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleChatSend();
    }
  };

// Render module intelligence view
  if (selectedModule) {
    const moduleConfig = MODULES.find((m) => m.id === selectedModule);
    const moduleName = moduleConfig ? moduleConfig.name : selectedModule;
    const detailRoute = moduleConfig ? moduleConfig.detailRoute : '#';

    return (
      <div className="flex flex-col h-full bg-[var(--color-background)] text-[var(--color-foreground)] overflow-y-auto overflow-x-hidden font-sans relative">
        {/* Chat Panel */}
        {chatOpen && (
          <div className="fixed inset-x-0 bottom-[60px] max-h-[50vh] overflow-y-auto bg-[var(--color-background)] border-t border-gray-800 z-50">
            <div className="flex flex-col h-full p-4">
              {/* Chat Header */}
              <div className="mb-4 flex items-center justify-between">
                <h3 className="text-lg font-bold text-white">Chat with UrbanOS</h3>
                <button
                  onClick={handleChatClose}
                  className="text-sm font-medium text-gray-400 hover:text-white"
                >
                  <ArrowRight size={20} className="rotate-180" /> Close
                </button>
              </div>

              {/* Chat Messages */}
              <div className="flex-1 overflow-y-auto mb-4 space-y-2">
                {chatMessages.map((msg, index) => (
                  <div key={index} className="max-w-[80%] rounded-lg px-3 py-2">
                    <p className="text-white text-sm">{msg.text}</p>
                  </div>
                ))}
              </div>

              {/* Chat Input */}
              <div className="flex gap-2">
                <input
                  type="text"
                  value={chatInput}
                  onChange={e => setChatInput(e.target.value)}
                  onKeyDown={handleChatKeyDown}
                  placeholder="Type a message..."
                  className="flex-1 rounded-lg border border-gray-700 bg-gray-900 text-white px-3 py-2 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  disabled={chatLoading}
                />
                <button
                  onClick={handleChatSend}
                  disabled={chatLoading || !chatInput.trim()}
                  className="rounded-lg border border-gray-700 bg-gray-900 text-white px-4 py-2 disabled:opacity-50"
                >
                  {chatLoading ? 'Sending...' : 'Send'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Main Content */}
        <div className="flex flex-col flex-grow min-h-0 overflow-y-auto pb-[20pt]">
          {/* Header */}
          <div className="flex flex-col flex-grow min-h-0 overflow-y-auto">
            {/* Header with back button */}
            <div className="mb-4 flex items-center justify-between p-4">
              <button
                onClick={handleBackToOverview}
                className="flex items-center gap-2 text-sm font-medium text-gray-400 hover:text-white"
              >
                <ArrowRight size={20} className="rotate-180" /> Overview
              </button>
              <h2 className="text-2xl font-heading text-white">{moduleName} Intelligence</h2>
            </div>

            {/* AI Brief */}
            <section className="mb-6">
              <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
                <AlertTriangle size={20} className="text-cyan-400" />
                <span>AI Brief</span>
              </h3>
              {overviewModuleLoading && !overviewModule && (
                <div className="glass-panel p-4 rounded-lg border border-gray-800">
                  <div className="h-4 bg-gray-700 rounded w-3/4 mb-2"></div>
                  <div className="h-6 bg-gray-700 rounded w-1/2"></div>
                </div>
              )}
              {overviewModuleError && !overviewModuleLoading && (
                <div className="glass-panel p-4 rounded-lg border border-red-500/30 text-red-500 text-sm">
                  AI briefing temporarily unavailable.
                </div>
              )}
              {overviewModule && !overviewModuleLoading && !overviewModuleError && (
                <div className="glass-panel p-4 rounded-lg border border-gray-800">
                  <p className="text-white">{overviewModule.summary || 'AI briefing unavailable.'}</p>
                </div>
              )}
            </section>

            {/* Current Status */}
            <section className="mb-6">
              <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
                <AlertTriangle size={20} className="text-yellow-400" />
                <span>Current Status</span>
              </h3>
              {overviewModuleLoading && !overviewModule && (
                <div className="grid grid-cols-2 gap-4">
                  {[...Array(2)].map((_, i) => (
                    <div key={i} className="glass-panel p-4 rounded-lg border border-gray-800 animate-pulse">
                      <div className="h-4 bg-gray-700 rounded w-3/4 mb-2"></div>
                      <div className="h-6 bg-gray-700 rounded w-1/2"></div>
                    </div>
                  ))}
                </div>
              )}
              {overviewModuleError && !overviewModuleLoading && (
                <div className="p-4 text-red-500 text-sm">City data temporarily unavailable.</div>
              )}
              {overviewModule && !overviewModuleLoading && !overviewModuleError && (
                <div className="glass-panel p-4 rounded-lg border border-gray-800">
                  <div className="space-y-4">
                    <div className="text-white">{overviewModule.summary || 'No summary available.'}</div>
                    <div className="text-xs text-gray-400">
                      Status: {overviewModule.status}
                    </div>
                    {overviewModule.kpi && (
                      <div className="text-sm text-cyan-400">
                        {overviewModule.kpi.label}: {overviewModule.kpi.value} {overviewModule.kpi.unit}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </section>

{/* Alerts */}
            <section className="mb-6">
              <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
                <AlertTriangle size={20} className="text-red-400" />
                <span>Alerts</span>
              </h3>
              {overviewModuleLoading && !overviewModule && (
                <div className="h-12 flex items-center justify-center text-gray-500">Loading...</div>
              )}
              {overviewModuleError && !overviewModuleLoading && (
                <div className="p-4 text-red-500 text-sm">Alerts temporarily unavailable.</div>
              )}
              {overviewModule && !overviewModuleLoading && !overviewModuleError && (
                <div className="glass-panel p-4 rounded-lg border border-gray-800">
                  {overviewModule.alerts && overviewModule.alerts.length > 0 ? (
                    <div className="space-y-2">
                      {overviewModule.alerts.map((alert, index) => (
                        <div key={index} className="p-3 bg-[var(--color-surface-low)] rounded border-l-2 border-red-500 text-sm">
                          <div className="flex justify-between mb-1">
                            <span className="font-bold text-red-400 uppercase text-xs">
                              {alert.domain} - {alert.severity}
                            </span>
                            <span className="text-[10px] text-gray-500 font-mono">{alert.id?.substring(0, 8) || ''}</span>
                          </div>
                          <div className="text-gray-200">{alert.description}</div>
                          <div className="text-xs text-gray-500 mt-1 font-mono">
                            {alert.affected_zones?.join(', ') || ''}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-white">
                      No specific alerts for this module.
                    </div>
                  )}
                </div>
              )}
            </section>

            {/* Cross-Domain Intelligence */}
            <section className="mb-6">
              <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
                <AlertTriangle size={20} className="text-blue-400" />
                <span>Cross-Domain Intelligence</span>
              </h3>
              {overviewModuleLoading && !overviewModule && (
                <div className="h-12 flex items-center justify-center text-gray-500">Loading...</div>
              )}
              {overviewModuleError && !overviewModuleLoading && (
                <div className="p-4 text-red-500 text-sm">Cross-domain insights temporarily unavailable.</div>
              )}
              {overviewModule && !overviewModuleLoading && !overviewModuleError && (
                <div className="glass-panel p-4 rounded-lg border border-gray-800">
                  {overviewModule.cross_domain && overviewModule.cross_domain.length > 0 ? (
                    <div className="space-y-2">
                      {overviewModule.cross_domain.map((insight, index) => (
                        <div key={index} className="text-white text-sm">
                          {insight}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-white">
                      Cross-domain intelligence would show relationships with other modules.
                      In a full implementation, we would display relevant insights.
                    </div>
                  )}
                </div>
              )}
            </section>

            {/* Link to full module dashboard */}
            <section className="mt-6">
              <div className="text-right">
                <a
                  href={detailRoute}
                  className="text-sm font-medium text-cyan-400 hover:text-cyan-200 underline"
                >
                  View Full {moduleName} Dashboard <ArrowRight size={16} />
                </a>
              </div>
            </section>
          </div>
        </div>

        {/* Bottom Chat Bar */}
        <div className="fixed inset-x-0 bottom-0 border-t border-gray-800 bg-[var(--color-background)] z-40">
          <div className="flex items-center px-4 py-3">
            <span className="text-gray-400">?</span>
            <span className="ml-2 text-white" onClick={handleChatOpen}>
              Ask UrbanOS about {moduleName}...
            </span>
          </div>
        </div>
      </div>
    );
  }

  // Render city overview
  return (
    <div className="flex flex-col h-full bg-[var(--color-background)] text-[var(--color-foreground)] overflow-y-auto overflow-x-hidden font-sans relative">
      {/* Chat Panel */}
      {chatOpen && (
        <div className="fixed inset-x-0 bottom-[60px] max-h-[50vh] overflow-y-auto bg-[var(--color-background)] border-t border-gray-800 z-50">
          <div className="flex flex-col h-full p-4">
            {/* Chat Header */}
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-lg font-bold text-white">Chat with UrbanOS</h3>
              <button
                onClick={handleChatClose}
                className="text-sm font-medium text-gray-400 hover:text-white"
              >
                <ArrowRight size={20} className="rotate-180" /> Close
              </button>
            </div>

            {/* Chat Messages */}
            <div className="flex-1 overflow-y-auto mb-4 space-y-2">
              {chatMessages.map((msg, index) => (
                <div key={index} className="max-w-[80%] rounded-lg px-3 py-2">
                  <p className="text-white text-sm">{msg.text}</p>
                </div>
              ))}
            </div>

            {/* Chat Input */}
            <div className="flex gap-2">
              <input
                type="text"
                value={chatInput}
                onChange={e => setChatInput(e.target.value)}
                onKeyDown={handleChatKeyDown}
                placeholder="Type a message..."
                className="flex-1 rounded-lg border border-gray-700 bg-gray-900 text-white px-3 py-2 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                disabled={chatLoading}
              />
              <button
                onClick={handleChatSend}
                disabled={chatLoading || !chatInput.trim()}
                className="rounded-lg border border-gray-700 bg-gray-900 text-white px-4 py-2 disabled:opacity-50"
              >
                {chatLoading ? 'Sending...' : 'Send'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main Content */}
      <div className="flex flex-col flex-grow min-h-0 overflow-y-auto pb-[20pt]">
        <div className="flex flex-col flex-grow min-h-0 overflow-y-auto">
{/* Header */}
          <div className="mb-6 flex items-center justify-between p-4">
            <h1 className="text-2xl font-heading text-white">
              UrbanOS &middot; Singapore
            </h1>
            <div className="flex items-center gap-2 text-sm text-gray-400">
              <span className="text-gray-400">Last updated: {formatSingaporeTime(overviewCity?.generated_at || null)}</span>
            </div>
          </div>

          {/* AI City Brief */}
          <section className="mb-6">
            <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
              <AlertTriangle size={20} className="text-cyan-400" />
              <span>AI City Brief</span>
            </h3>
            {overviewCityLoading && !overviewCity && (
              <div className="glass-panel p-4 rounded-lg border border-gray-800">
                <div className="h-4 bg-gray-700 rounded w-3/4 mb-2"></div>
                <div className="h-6 bg-gray-700 rounded w-1/2"></div>
              </div>
            )}
            {overviewCityError && !overviewCityLoading && (
              <div className="glass-panel p-4 rounded-lg border border-red-500/30 text-red-500 text-sm">
                AI briefing temporarily unavailable.
              </div>
            )}
            {overviewCity && !overviewCityLoading && !overviewCityError && (
              <div className="glass-panel p-4 rounded-lg border border-gray-800">
                <p className="text-white">{overviewCity.ai_brief || 'AI briefing unavailable.'}</p>
              </div>
            )}
          </section>

          {/* Module Intelligence Grid */}
          <section className="mb-6">
            <h3 className="text-lg font-bold text-white mb-4">Module Intelligence</h3>
            {overviewCityLoading && !overviewCity && (
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                {[...Array(8)].map((_, i) => (
                  <div key={i} className="glass-panel p-4 rounded-lg border border-gray-800 animate-pulse">
                    <div className="h-4 bg-gray-700 rounded w-3/4 mb-2"></div>
                    <div className="h-6 bg-gray-700 rounded w-1/2"></div>
                  </div>
                ))}
              </div>
            )}
            {overviewCityError && !overviewCityLoading && (
              <div className="p-4 text-red-500 text-sm">City data temporarily unavailable.</div>
            )}
            {overviewCity && !overviewCityLoading && !overviewCityError && (
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                {MODULES.map((module) => {
                  const moduleData = overviewCity.modules.find(m => m.id === module.id);
                  const Icon = module.icon;
                  return (
                    <div
                      key={module.id}
                      className="glass-panel p-4 rounded-lg border border-gray-800 cursor-pointer hover:border-gray-700 transition-colors"
                      onClick={() => handleModuleSelect(module.id)}
                    >
                      <div className="flex flex-col items-center text-center h-full">
                        <div className="mb-3">
                          <Icon className="w-8 h-8 text-gray-400" />
                        </div>
                        <div className="text-sm font-medium text-white">{module.name}</div>
                        {moduleData?.kpi && (
                          <div className="mt-2 text-xs text-cyan-400">
                            {moduleData.kpi.label}: {moduleData.kpi.value} {moduleData.kpi.unit}
                          </div>
                        )}
                        {moduleData?.kpi === undefined && (
                          <div className="mt-2 text-xs text-gray-400">
                            No KPI available
                          </div>
                        )}
                        <div className="mt-2">
                          <div className="px-2 py-0.5 text-xs font-medium rounded-full border border border-gray-600">
                            Status: {moduleData?.status || 'Unavailable'}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
          <section className="mb-6">
            <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
              <AlertTriangle size={20} className="text-yellow-400" />
              <span>Alerts & Anomalies</span>
            </h3>
            {overviewCityLoading && !overviewCity && (
              <div className="h-12 flex items-center justify-center text-gray-500">Loading...</div>
            )}
            {overviewCityError && !overviewCityLoading && (
              <div className="p-4 text-red-500 text-sm">Alerts temporarily unavailable.</div>
            )}
            {overviewCity && !overviewCityLoading && !overviewCityError && (
              <div className="glass-panel p-4 rounded-lg border border-gray-800">
                {overviewCity.alerts && overviewCity.alerts.length > 0 ? (
                  <div className="space-y-2">
                    {overviewCity.alerts.map((incident: any, index: number) => (
                      <div key={index} className="p-3 bg-[var(--color-surface-low)] rounded border-l-2 border-red-500 text-sm">
                        <div className="flex justify-between mb-1">
                          <span className="font-bold text-red-400 uppercase text-xs">
                            {incident.domain} - {incident.severity}
                          </span>
                          <span className="text-[10px] text-gray-500 font-mono">{incident.id?.substring(0, 8) || ''}</span>
                        </div>
                        <div className="text-gray-200">{incident.description}</div>
                        <div className="text-xs text-gray-500 mt-1 font-mono">
                          {incident.affected_zones?.join(', ')}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="p-8 text-center text-gray-500">
                    No significant alerts
                  </div>
                )}
              </div>
            )}
          </section>

          {/* Bottom Chat Bar */}
          <div className="fixed inset-x-0 bottom-0 border-t border-gray-800 bg-[var(--color-background)] z-40">
            <div className="flex items-center px-4 py-3">
              <span className="text-gray-400">?</span>
              <span className="ml-2 text-white" onClick={handleChatOpen}>
                Ask UrbanOS anything...
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
