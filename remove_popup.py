with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'r') as f:
    content = f.read()

# Remove the disabled selectedStand popup entirely
old = '''              {/* Selected Stand Popup - Temporarily disabled for build */}
              {false && selectedStand && (
                <div className="absolute bottom-4 right-4 z-10 glass-panel-glow p-4 rounded-lg border border-gray-700 min-w-[280px] max-w-[320px] shadow-xl pointer-events-auto">
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <h4 className="font-bold text-white text-sm">{selectedStand.name}</h4>
                      <div className="flex items-center gap-2 mt-1 text-xs">
                        <span className="font-mono text-[var(--color-primary)]">{selectedStand.taxi_code}</span>
                        {getOwnershipBadge(selectedStand.ownership)}
                      </div>
                    </div>
                    <button
                      onClick={() => setSelectedStand(null)}
                      className="text-gray-400 hover:text-white p-1"
                      aria-label="Close"
                    >
                      ✕
                    </button>
                  </div>
                  <div className="space-y-2 text-sm">
                    <div className="flex items-center gap-2 text-gray-300">
                      <MapPin className="w-4 h-4 text-gray-500" />
                      <span className="font-mono">
                        {selectedStand.latitude.toFixed(6)}, {selectedStand.longitude.toFixed(6)}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-gray-500 w-20">Type:</span>
                      <span className="text-white capitalize">{selectedStand.type.toLowerCase()}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-gray-500 w-20">Ownership:</span>
                      <span className="text-white">{selectedStand.ownership}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-gray-500 w-20">BFA:</span>
                      <span className="flex items-center gap-1 text-white">
                        {getBFACheck(selectedStand.is_bfa_accessible)}
                        {selectedStand.is_bfa_accessible ? 'Accessible' : 'Not Accessible'}
                      </span>
                    </div>
                  </div>
                </div>
              )}'''

if old in content:
    content = content.replace(old, '')
    with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'w') as f:
        f.write(content)
    print('Removed popup successfully!')
else:
    print('Popup not found')