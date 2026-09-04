"use client";

import { useMemo, useState } from 'react';
import Map, { Source, Layer, Marker, NavigationControl } from 'react-map-gl/maplibre';
import type { FillLayerSpecification, LineLayerSpecification } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

const MAP_STYLE = {
  version: 8,
  sources: {
    'osm': {
      type: 'raster',
      tiles: [
        'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      ],
      tileSize: 256,
      attribution: '&copy; OpenStreetMap contributors'
    }
  },
  layers: [
    {
      id: 'osm-layer',
      source: 'osm',
      type: 'raster',
      minzoom: 0,
      maxzoom: 19
    }
  ]
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export default function TrafficMap({ incidents }: { incidents: any[] }) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [hoverInfo, setHoverInfo] = useState<any | null>(null);

  // Default color for zones
  const getZoneRiskColor = () => {
    return '#3b82f6'; // blue-500 for traffic dashboard base map
  };

  const fillLayerStyle: FillLayerSpecification = useMemo(() => {
    return {
      id: 'zones-fill',
      type: 'fill',
      source: 'zones',
      paint: {
        'fill-color': [
          'match',
          ['get', 'name'],
          'SG_NORTH', getZoneRiskColor(),
          'SG_NORTH_EAST', getZoneRiskColor(),
          'SG_CENTRAL_NORTH', getZoneRiskColor(),
          'SG_CENTRAL_SOUTH', getZoneRiskColor(),
          'SG_EAST', getZoneRiskColor(),
          'SG_WEST_NORTH', getZoneRiskColor(),
          'SG_WEST_SOUTH', getZoneRiskColor(),
          'SG_SENTOSA', getZoneRiskColor(),
          '#3b82f6' // fallback
        ],
        'fill-opacity': [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          0.2,
          0.1
        ]
      }
    };
  }, []);

  const lineLayerStyle: LineLayerSpecification = {
    id: 'zones-line',
    type: 'line',
    source: 'zones',
    paint: {
      'line-color': '#00e5ff',
      'line-width': 1,
      'line-opacity': 0.3
    }
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const onHover = (event: { features?: any[]; point: { x: number; y: number } }) => {
    const { features, point: { x, y } } = event;
    const hoveredFeature = features && features[0];

    setHoverInfo(
      hoveredFeature
        ? {
            feature: hoveredFeature,
            x,
            y
          }
        : null
    );
  };

  return (
    <div className="relative w-full h-full min-h-[400px] glass-panel rounded-xl overflow-hidden border border-gray-800">
      <Map
        initialViewState={{
          longitude: 103.8198,
          latitude: 1.3521,
          zoom: 10.5
        }}
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        maxBounds={[[103.5, 1.1], [104.2, 1.5]] as any}
        dragPan={true}
        dragRotate={false}
        pitchWithRotate={false}
        touchZoomRotate={false}
        touchPitch={false}
        keyboard={false}
        minZoom={9.5}
        maxZoom={16}
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        mapStyle={MAP_STYLE as any}
        interactiveLayerIds={['zones-fill']}
        onMouseMove={onHover}
      >
        <NavigationControl showCompass={false} position="top-right" />
        
        <Source id="zones" type="geojson" data="/data/singapore_traffic_zones.geojson">
          <Layer {...fillLayerStyle} />
          <Layer {...lineLayerStyle} />
        </Source>

        {/* Render Traffic Incidents */}
        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
        {incidents.map((incident: any, idx: number) => {
          if (incident.latitude && incident.longitude) {
            return (
              <Marker key={`traffic-${idx}`} longitude={incident.longitude} latitude={incident.latitude}>
                <div 
                  className="w-4 h-4 bg-red-500 transform rotate-45 border border-red-200 cursor-pointer shadow-lg hover:scale-125 transition-transform"
                  title={`${incident.type}: ${incident.message}`}
                />
              </Marker>
            );
          }
          return null;
        })}
      </Map>

      {hoverInfo && (
        <div 
          className="absolute z-20 glass-panel-glow p-2 rounded pointer-events-none text-xs bg-gray-900/90 text-white"
          style={{ left: hoverInfo.x + 15, top: hoverInfo.y + 15 }}
        >
          <div className="font-heading font-bold text-[var(--color-primary)] capitalize">
            {hoverInfo.feature.properties.name?.replace('SG_', '').replace('_', ' ')}
          </div>
        </div>
      )}
    </div>
  );
}
