with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'r') as f:
    content = f.read()

old = '''{/* Interactive Map Section */}
        <section className="mb-6">
          <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
            <MapPin size={20} className="text-[var(--color-primary)]" />
            <span>Road Infrastructure Map</span>
          </h3>

          {mapDataLoading && !mapData && (
            <div className="min-h-[500px] glass-panel p-2 rounded-xl overflow-hidden border border-gray-800 relative flex items-center justify-center">
              <Loader2 className="w-10 h-10 text-[var(--color-primary)] animate-spin" />
            </div>
          )}
          {mapDataError && (
            <div className="min-h-[500px] glass-panel p-2 rounded-xl overflow-hidden border border-gray-800 relative flex items-center justify-center text-red-500">
              Failed to load map data: {mapDataError}
            </div>
          )}
          {mapData && (
            <div className="relative min-h-[500px] glass-panel rounded-xl overflow-hidden border border-gray-800 flex items-center justify-center">
              <div className="text-center text-gray-400">
                <p>Map with {mapData.features.length} taxi stands</p>
                <p className="text-sm">Map component placeholder</p>
              </div>
            </div>
          )}'''

new = '''        {/* Interactive Map Section */}
        <section className="mb-6">
          <div>
            <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
              <MapPin size={20} className="text-[var(--color-primary)]" />
              <span>Road Infrastructure Map</span>
            </h3>

            {mapDataLoading && !mapData && (
              <div className="min-h-[500px] glass-panel p-2 rounded-xl overflow-hidden border border-gray-800 relative flex items-center justify-center">
                <Loader2 className="w-10 h-10 text-[var(--color-primary)] animate-spin" />
              </div>
            )}
            {mapDataError && (
              <div className="min-h-[500px] glass-panel p-2 rounded-xl overflow-hidden border border-gray-800 relative flex items-center justify-center text-red-500">
                Failed to load map data: {mapDataError}
              </div>
            )}
            {mapData && (
              <div className="relative min-h-[500px] glass-panel rounded-xl overflow-hidden border border-gray-800 flex items-center justify-center">
                <div className="text-center text-gray-400">
                  <p>Map with {mapData.features.length} taxi stands</p>
                  <p className="text-sm">Map component placeholder</p>
                </div>
              </div>
            )}
          </div>'''

if old in content:
    content = content.replace(old, new)
    with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'w') as f:
        f.write(content)
    print('Replaced successfully!')
else:
    print('Old string not found')
    idx = content.find('Interactive Map Section')
    if idx >= 0:
        print('Found at index:', content.find('Interactive Map Section'))