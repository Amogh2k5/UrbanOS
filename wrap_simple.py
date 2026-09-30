with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'r') as f:
    content = f.read()

# Find the exact old string from the file using the anchor
idx = content.find('{/* Interactive Map Section */}')
if idx < 0:
    print('Anchor not found')
    exit()

# Find the end of the mapData conditional
paren = 0
brace = 0
in_str = False
end_idx = -1
for i, ch in enumerate(content[idx:], 0):
    if ch == '(' and not in_str:
        paren += 1
    elif ch == ')' and not in_str:
        paren -= 1
    elif ch == '{' and not in_str:
        brace += 1
    elif ch == '}' and not in_str:
        brace -= 1
    elif ch == '"':
        in_str = not in_str
    if paren == 0 and brace == 0 and i > 1000:
        end_idx = i + 1
        break

if end_idx < 0:
    print('Could not find end of mapData conditional')
    exit()

exact_old = content[idx:idx+end_idx]
print('Found exact old string, length:', len(exact_old))

new_section = '''        {/* Interactive Map Section */}
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
          </div>
        </section>'''

if exact_old in content:
    content = content.replace(exact_old, '''        {/* Interactive Map Section */}
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
          </div>
        </section>''')
    with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'w') as f:
        f.write(content)
    print('Replaced successfully using exact match!')
else:
    print('Could not find exact old string in content')