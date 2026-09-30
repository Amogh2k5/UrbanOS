with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'r') as f:
    content = f.read()

# Find the mapData conditional start
start_idx = content.find('{mapData && (', 34000)
print(f'Start at: {start_idx}')

# Find the matching closing by counting braces and parens
paren_count = 0
brace_count = 0
in_string = False
escape = False
end_idx = -1

for i, ch in enumerate(content[start_idx:], start_idx):
    if ch == '(' and not in_string:
        paren_count += 1
    elif ch == ')' and not in_string:
        paren_count -= 1
    elif ch == '{' and not in_string:
        brace_count += 1
    elif ch == '}' and not in_string:
        brace_count -= 1
    elif ch == '"' and not escape:
        in_string = not in_string
    elif ch == "'" and not escape:
        in_string = not in_string
    elif ch == '\\' and not escape:
        escape = True
        continue
    else:
        escape = False
    
    if paren_count == 0 and brace_count == 0 and i > start_idx:
        end_idx = i + 1
        print(f'Found matching at offset {i} (absolute {end_idx})')
        print(f'Length: {end_idx - start_idx}')
        print(repr(content[start_idx:end_idx]))
        break

if end_idx > 0:
    old = content[start_idx:end_idx]
    
    new = '''{mapData && (
            <div className="relative min-h-[500px] glass-panel rounded-xl overflow-hidden border border-gray-800">
                  <Map
                    initialViewState={{
                      longitude: 103.8198,
                      latitude: 1.3521,
                      zoom: 10.5,
                    }}
                    maxBounds={[[103.5, 1.1], [104.2, 1.5]] as [number, number, number, number]}
                    dragPan={true}
                    dragRotate={false}
                    pitchWithRotate={false}
                    touchZoomRotate={false}
                    touchPitch={false}
                    keyboard={false}
                    minZoom={9.5}
                    maxZoom={16}
                    mapStyle={MAP_STYLE as StyleSpecification}
                    scrollZoom={false}
                  >
                    <NavigationControl showCompass={false} position="top-right" />

                    {mapData.features.map((feature: MapFeature, idx: number) => {
                      const { coordinates, properties } = feature;
                      const [longitude, latitude] = coordinates;
                      return (
                        <Marker
                          key={`taxi-${properties.taxi_code}`}
                          longitude={longitude}
                          latitude={latitude}
                        >
                          <div
                            className={`w-3 h-3 rounded-full border-2 cursor-pointer transition-transform hover:scale-150 ${
                              properties.bfa_accessible
                                ? 'bg-emerald-400 border-emerald-200'
                                : 'bg-gray-500 border-gray-400'
                            }`}
                            onClick={() => setSelectedStand(properties as unknown as TaxiStand)}
                            title={properties.name}
                          />
                        </Marker>
                      );
                    })}

                  </Map>
                </div>
          )}'''
    
    new_content = content[:start_idx] + new + content[end_idx:]
    
    with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'w') as f:
        f.write(new_content)
    print('Replaced successfully!')
else:
    print('Could not find matching closing')