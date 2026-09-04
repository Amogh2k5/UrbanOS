/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useMemo, useState } from 'react';
import Map, { Source, Layer, Marker, NavigationControl } from 'react-map-gl/maplibre';
import type { FillLayerSpecification, LineLayerSpecification } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useAppStore } from '@/store';
import ZoneInspector from './ZoneInspector';
import MapLegend from './MapLegend';

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

export default function SingaporeMap() {
  const { report, selectedZone, setSelectedZone } = useAppStore();
  const [hoverInfo, setHoverInfo] = useState<any | null>(null);

  // Compute risk colors for each zone
  const getZoneRiskColor = (zoneName: string) => {
    if (!report) return '#3b82f6'; // Default Low / Blue
    
    const checkZoneAffected = (zName: string, affectedZones?: string[]) => {
      if (!affectedZones) return false;
      const normalized = zName.replace('SG_', '').replace(/_/g, ' ').toLowerCase();
      return affectedZones.some(z => z.toLowerCase() === normalized || z === zName);
    };

    const activeIncidents = report.priority_incidents?.filter(inc => checkZoneAffected(zoneName, inc.affected_zones)) || [];
    const crossImpacts = report.cross_domain_impacts?.filter(imp => checkZoneAffected(zoneName, imp.affected_zones)) || [];
    
    if (crossImpacts.some(i => i.severity === 'CRITICAL')) return '#dc2626'; // red-600
    if (crossImpacts.some(i => i.severity === 'HIGH') || activeIncidents.some(i => i.severity === 'HIGH')) return '#f97316'; // orange-500
    if (crossImpacts.some(i => i.severity === 'MODERATE') || activeIncidents.some(i => i.severity === 'MODERATE')) return '#eab308'; // yellow-500
    return '#3b82f6'; // blue-500
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
          'SG_NORTH', getZoneRiskColor('SG_NORTH'),
          'SG_NORTH_EAST', getZoneRiskColor('SG_NORTH_EAST'),
          'SG_CENTRAL_NORTH', getZoneRiskColor('SG_CENTRAL_NORTH'),
          'SG_CENTRAL_SOUTH', getZoneRiskColor('SG_CENTRAL_SOUTH'),
          'SG_EAST', getZoneRiskColor('SG_EAST'),
          'SG_WEST_NORTH', getZoneRiskColor('SG_WEST_NORTH'),
          'SG_WEST_SOUTH', getZoneRiskColor('SG_WEST_SOUTH'),
          'SG_SENTOSA', getZoneRiskColor('SG_SENTOSA'),
          '#3b82f6' // fallback
        ],
        'fill-opacity': [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          0.8,
          0.4
        ]
      }
    };
  }, [report]);

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

  const trafficIncidents = report?.source_reports?.traffic?.incidents || [];
  const floodAlerts = report?.source_reports?.flood?.active_alerts || [];

  return (
    <div className="relative w-full h-full min-h-[500px] glass-panel rounded-xl overflow-hidden">
      <Map
        initialViewState={{
          longitude: 103.8198,
          latitude: 1.3521,
          zoom: 11.5
        }}
        maxBounds={[[103.55, 1.15], [104.15, 1.50]] as any}
        dragPan={false}
        dragRotate={false}
        pitchWithRotate={false}
        touchZoomRotate={false}
        touchPitch={false}
        keyboard={false}
        minZoom={10.5}
        maxZoom={16}
        mapStyle={MAP_STYLE as any}
        interactiveLayerIds={['zones-fill']}
        onMouseMove={onHover}
        onClick={(e) => {
          if (e.features && e.features.length > 0) {
            setSelectedZone(e.features[0].properties?.name);
          } else {
            setSelectedZone(null);
          }
        }}
      >
        <NavigationControl showCompass={false} position="top-right" />
        
        <Source id="zones" type="geojson" data="/data/singapore_traffic_zones.geojson">
          <Layer {...fillLayerStyle} />
          <Layer {...lineLayerStyle} />
        </Source>

        {/* Render Traffic Incidents */}
        {trafficIncidents.map((incident: any, idx: number) => {
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

        {/* Render Flood Alerts */}
        {floodAlerts.map((alert: any, idx: number) => {
          if (alert.latitude && alert.longitude) {
            return (
              <Marker key={`flood-${idx}`} longitude={alert.longitude} latitude={alert.latitude}>
                <div 
                  className="w-4 h-4 rounded-full bg-cyan-400 border border-cyan-100 cursor-pointer shadow-[0_0_12px_rgba(34,211,238,0.8)] hover:scale-125 transition-transform"
                  title={`${alert.alert_type}: ${alert.message}`}
                />
              </Marker>
            );
          }
          return null;
        })}
      </Map>

      {hoverInfo && (
        <div 
          className="absolute z-20 glass-panel-glow p-3 rounded pointer-events-none text-sm max-w-[200px]"
          style={{ left: hoverInfo.x + 15, top: hoverInfo.y + 15 }}
        >
          <div className="font-heading font-bold text-[var(--color-primary)] capitalize">
            {hoverInfo.feature.properties.name?.replace('SG_', '').replace('_', ' ')}
          </div>
          <div className="text-gray-300 mt-1 text-xs">
            Click to open Zone Inspector for details
          </div>
        </div>
      )}

      <MapLegend />
      <ZoneInspector />
    </div>
  );
}
