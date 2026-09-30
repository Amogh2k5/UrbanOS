with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'r') as f:
    content = f.read()

old = '{mapData && (\n            <div className="relative min-h-[500px] glass-panel rounded-xl overflow-hidden border border-gray-800">\n                  <Map\n                    initialViewState={{\n                      longitude: 103.8198,\n                      latitude: 1.3521,\n                      zoom: 10.5,\n                    }}\n                    maxBounds={[[103.5, 1.1], [104.2, 1.5]] as [number, number, number, number]}\n                    dragPan={true}\n                    dragRotate={false}\n                    pitchWithRotate={false}\n                    touchZoomRotate={false}\n                    touchPitch={false}\n                    keyboard={false}\n                    minZoom={9.5}\n                    maxZoom={16}\n                    mapStyle={MAP_STYLE as StyleSpecification}\n                    scrollZoom={false}\n                  >\n                    <NavigationControl showCompass={false} position="top-right" />\n\n                    {mapData.features.map((feature: MapFeature, idx: number) => {\n                      const { coordinates, properties } = feature;\n                      const [longitude, latitude] = coordinates;\n                      return (\n                        <Marker\n                          key={`taxi-${properties.taxi_code}`}\n                          longitude={longitude}\n                          latitude={latitude}\n                        >\n                          <div\n                            className={`w-3 h-3 rounded-full border-2 cursor-pointer transition-transform hover:scale-150 ${\n                              properties.bfa_accessible\n                                ? \'bg-emerald-400 border-emerald-200\'\n                                : \'bg-gray-500 border-gray-400\'\n                            }`}\n                            onClick={() => setSelectedStand(properties as unknown as TaxiStand)}\n                            title={properties.name}\n                          />\n                        </Marker>\n                      );\n                    })}\n\n                  </Map>\n                </div>\n          )}'

new = '{mapData && (\n            <div className="relative min-h-[500px] glass-panel rounded-xl overflow-hidden border border-gray-800 flex items-center justify-center">\n              <div className="text-center text-gray-400">\n                <p>Map with {mapData.features.length} taxi stands</p>\n                <p className="text-sm">Map component placeholder</p>\n              </div>\n            </div>\n          )}'

if old in content:
    content = content.replace(old, new)
    with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'w') as f:
        f.write(content)
    print('Replaced successfully!')
else:
    print('Old string not found')
    idx = content.find('{mapData && (')
    if idx >= 0:
        print(f'Found at index {idx}')
        print(repr(content[idx:idx+200]))