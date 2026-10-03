with open(r'C:\projects\UrbanOS\frontend\src\app\page.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

old = """            )}
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
                        <div className="mt-2 text-xs text-gray-400">
          <section className="mb-6">"""

new = """            )}
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
          <section className="mb-6">"""

if old in content:
    content = content.replace(old, new)
    with open(r'C:\projects\UrbanOS\frontend\src\app\page.tsx', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Fixed!')
else:
    print('Pattern not found')