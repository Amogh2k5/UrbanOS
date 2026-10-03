with open(r'C:\projects\UrbanOS\frontend\src\app\page.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# The issue is likely in the Module Intelligence section conditional closing
# Let me replace from the Module Intelligence section start to the end of Alerts section

old = """          {/* Module Intelligence Grid */}
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
                          <div className="px-2 py-0.5 text-xs font-medium rounded-full border-gray-600">
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

          {/* Alerts & Anomalies */}
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
          </section>"""

new = """          {/* Module Intelligence Grid */}
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
                          <div className="px-2 py-0.5 text-xs font-medium rounded-full border border-gray-600">
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

          {/* Alerts & Anomalies */}
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
          </section>"""

if old in content:
    content = content.replace(old, new)
    with open(r'C:\projects\UrbanOS\frontend\src\app\page.tsx', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Fixed!')
else:
    print('Pattern not found - checking differences...')
    # Find where they differ
    idx = content.find('Module Intelligence Grid')
    if idx >= 0:
        print(f'Found at {idx}')
        print(content[idx:idx+200])