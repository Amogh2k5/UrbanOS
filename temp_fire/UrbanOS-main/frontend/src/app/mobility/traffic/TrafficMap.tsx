"use client";

import { useMemo, useState, useRef, useEffect } from 'react';
import Map, { Source, Layer, Marker, NavigationControl } from 'react-map-gl/maplibre';
import type { FillLayerSpecification, LineLayerSpecification, StyleSpecification } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

const MAP_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '&copy; OpenStreetMap contributors',
    },
  },
  layers: [
    {
      id: 'osm-layer',
      source: 'osm',
      type: 'raster',
      minzoom: 0,
      maxzoom: 19,
    },
  ],
};

interface Incident {
  type?: string;
  message?: string;
  latitude?: number;
  longitude?: number;
  zone_name?: string;
  status?: string;
}

interface TrafficMapProps {
  incidents: Incident[];
  onIncidentClick?: (incident: Incident | null) => void;
  selectedIncident?: Incident | null;
}

interface HoverInfo {
  feature: { properties: { name?: string } };
  x: number;
  y: number;
}

export default function TrafficMap({ incidents, onIncidentClick, selectedIncident }: TrafficMapProps) {
  const [hoverInfo, setHoverInfo] = useState<HoverInfo | null>(null);
  const [overlayPos, setOverlayPos] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const dragStartRef = useRef({ x: 0, y: 0 });
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!dragging) return;
    const move = (e: MouseEvent) => {
      const dx = e.clientX - dragStartRef.current.x;
      const dy = e.clientY - dragStartRef.current.y;
      setOverlayPos((prev) => ({ x: prev.x + dx, y: prev.y + dy }));
      dragStartRef.current = { x: e.clientX, y: e.clientY };
    };
    const up = () => setDragging(false);
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
    return () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
  }, [dragging]);

  const getZoneRiskColor = () => '#3b82f6';

  const fillLayerStyle: FillLayerSpecification = useMemo(() => ({
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
        '#3b82f6',
      ],
      'fill-opacity': [
        'case',
        ['boolean', ['feature-state', 'hover'], false],
        0.2,
        0.1,
      ],
    },
  }), []);

  const lineLayerStyle: LineLayerSpecification = {
    id: 'zones-line',
    type: 'line',
    source: 'zones',
    paint: {
      'line-color': '#00e5ff',
      'line-width': 1,
      'line-opacity': 0.3,
    },
  };

  const onHover = (event: { features?: { properties: { name?: string } }[]; point: { x: number; y: number } }) => {
    const { features, point: { x, y } } = event;
    const hoveredFeature = features && features[0];
    setHoverInfo(hoveredFeature ? { feature: hoveredFeature, x, y } : null);
  };

  const handleMarkerClick = (incident: Incident, e: React.MouseEvent) => {
    e.stopPropagation();
    if (onIncidentClick) onIncidentClick(incident);
    const mapContainer = document.querySelector('.traffic-map-container');
    if (mapContainer) {
      const rect = mapContainer.getBoundingClientRect();
      setOverlayPos({ x: rect.width / 2 - 160, y: rect.height / 2 - 80 });
    }
  };

  const handleOverlayMouseDown = (e: React.MouseEvent) => {
    if (e.target === overlayRef.current || (e.target as HTMLElement).closest('.overlay-header')) {
      setDragging(true);
      dragStartRef.current = { x: e.clientX, y: e.clientY };
    }
  };

  return (
    <div className="relative w-full h-full min-h-[500px] glass-panel rounded-xl overflow-hidden border border-gray-800 traffic-map-container" style={{ touchAction: 'pan-y' }}>
      <Map
        initialViewState={{
          longitude: 103.8198,
          latitude: 1.3521,
          zoom: 10.5,
        }}
        maxBounds={[103.5, 1.1, 104.2, 1.5] as [number, number, number, number]}
        dragPan={true}
        dragRotate={false}
        pitchWithRotate={false}
        touchZoomRotate={false}
        touchPitch={false}
        keyboard={false}
        minZoom={9.5}
        maxZoom={16}
        mapStyle={MAP_STYLE as StyleSpecification}
        interactiveLayerIds={['zones-fill']}
        onMouseMove={onHover}
        onClick={() => {
          // clicking empty map can close overlay (handled by parent)
        }}
        scrollZoom={false}
      >
        <NavigationControl showCompass={false} position="top-right" />

        <Source id="zones" type="geojson" data="/data/singapore_traffic_zones.geojson">
          <Layer {...fillLayerStyle} />
          <Layer {...lineLayerStyle} />
        </Source>

        {incidents.map((incident: Incident, idx: number) => {
          if (incident.latitude && incident.longitude) {
            return (
              <Marker
                key={`traffic-${idx}`}
                longitude={incident.longitude}
                latitude={incident.latitude}
                onClick={(e) => handleMarkerClick(incident, e as unknown as React.MouseEvent)}
              >
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

      {/* Incident Overlay */}
      {selectedIncident && (
        <div
          ref={overlayRef}
          className="absolute z-30 glass-panel-glow p-0 rounded-lg shadow-xl border border-gray-700 min-w-[300px] max-w-[360px] pointer-events-auto"
          style={{
            left: overlayPos.x,
            top: overlayPos.y,
            transform: dragging ? undefined : 'none',
          }}
          onMouseDown={handleOverlayMouseDown}
        >
          <div
            className="overlay-header flex items-center justify-between p-3 bg-gray-900/80 border-b border-gray-700 cursor-move"
            style={{ userSelect: 'none' }}
          >
            <h4 className="font-bold text-white">Traffic Incident</h4>
            <button
              onClick={() => onIncidentClick?.(null)}
              className="text-gray-400 hover:text-white p-1"
              aria-label="Close"
            >
              ✕
            </button>
          </div>
          <div className="p-3 space-y-2 text-sm">
            <div>
              <span className="text-gray-400">Type:</span>
              <span className="ml-2 font-medium text-white capitalize">{selectedIncident.type || 'Unknown'}</span>
            </div>
            <div>
              <span className="text-gray-400">Location:</span>
              <span className="ml-2 text-white">{selectedIncident.message || 'Unknown'}</span>
            </div>
            <div>
              <span className="text-gray-400">Zone:</span>
              <span className="ml-2 text-white">{selectedIncident.zone_name || 'N/A'}</span>
            </div>
            <div>
              <span className="text-gray-400">Status:</span>
              <span className="ml-2 text-white">{selectedIncident.status || 'Active'}</span>
            </div>
            <div>
              <span className="text-gray-400">Time:</span>
              <span className="ml-2 text-white">{new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
