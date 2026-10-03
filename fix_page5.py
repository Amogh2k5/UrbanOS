with open(r'C:\projects\UrbanOS\frontend\src\app\page.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: Module Intelligence section - fix the conditional indentation
old = """{overviewCity && !overviewCityLoading && !overviewCityError && (
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
              </div>
            )}"""

new = """            {overviewCity && !overviewCityLoading && !overviewCityError && (
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
            )}"""

if old in content:
    content = content.replace(old, new)
    print('Fixed Module Intelligence conditional indentation!')
else:
    print('Module Intelligence pattern not found')

# Fix 2: Alerts section - fix conditionals indentation
old2 = """{overviewCityLoading && !overviewCity && (
              <div className="h-12 flex items-center justify-center text-gray-500">Loading...</div>
            )}
            {overviewCityError && !overviewCityLoading && (
              <div className="p-4 text-red-500 text-sm">Alerts temporarily unavailable.</div>
            )}
            {overviewCity && !overviewCityLoading && !overviewCityError && ("""

new2 = """            {overviewCityLoading && !overviewCity && (
              <div className="h-12 flex items-center justify-center text-gray-500">Loading...</div>
            )}
            {overviewCityError && !overviewCityLoading && (
              <div className="p-4 text-red-500 text-sm">Alerts temporarily unavailable.</div>
            )}
            {overviewCity && !overviewCityLoading && !overviewCityError && ("""

if old2 in content:
    content = content.replace(old2, new2)
    print('Fixed Alerts section conditionals indentation!')
else:
    print('Alerts pattern not found')

# Fix 3: Also fix the border-gray-600 to border border-gray-600 in Module Intelligence
content = content.replace('border-gray-600">', 'border border-gray-600">')

with open(r'C:\projects\UrbanOS\frontend\src\app\page.tsx', 'w', encoding='utf-8') as f:
    f.write(content)
print('Done!')