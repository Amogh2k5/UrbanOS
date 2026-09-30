with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'r') as f:
    content = f.read()

old = '''        {/* Interactive Map Section */}
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

print('Old string in content:', old in content)
if old not in content:
    idx = content.find('Interactive Map Section')
    if idx >= 0:
        print('Found at index:', content.find('Interactive Map Section'))
        # Compare character by character
        for i, (c1, c2) in enumerate(zip(content[content.find('Interactive Map Section'):], old)):
            if c1 != c2:
                print(f'Mismatch at offset {i}: file={repr(c1)} old={repr(c2)}')
                print(f'File context: {repr(content[content.find(\"Interactive Map Section\"):content.find(\"Interactive Map Section\")+i+20])}')
                print(f'Old context: {repr(old[i:i+20])}')
                break