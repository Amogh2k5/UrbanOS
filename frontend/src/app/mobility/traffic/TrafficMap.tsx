"use client";

import { useMemo, useState, useRef, useEffect } from 'react';
import Map, { Source, Layer, Marker, NavigationControl } from 'react-map-gl/maplibre';
import type { FillLayerSpecification, LineLayerSpecification, StyleSpecification } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { formatSingaporeTime } from '@/services/time';

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
  timestamp?: string;
}

interface TrafficMapProps {
  incidents: Incident[];
  onIncidentClick?: (incident: Incident | null) => void;
  selectedIncident?: Incident | null;
}

interface HoverInfo {
  feature: { properties: { name?: string; zone_name?: string } };
  x: number;
  y: number;
}

export default function TrafficMap({ incidents, onIncidentClick, selectedIncident }: TrafficMapProps) {
  const [hoverInfo, setHoverInfo] = useState<HoverInfo | null>(null);
  const [overlayPos, setOverlayPos] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const [tileError, setTileError] = useState(false);
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
        0.45,
        0.25,
      ],
    },
  }), []);

  const lineLayerStyle: LineLayerSpecification = {
    id: 'zones-line',
    type: 'line',
    source: 'zones',
    paint: {
      /* Was #00e5ff at 0.3 opacity - a neon cyan that was effectively invisible
         once the theme moved to a light basemap. Now a readable domain blue at
         a weight you can actually see. */
      'line-color': '#1d4ed8',
      'line-width': 1.5,
      'line-opacity': 0.75,
    },
  };

  const onHover = (event: { features?: { properties: { name?: string; zone_name?: string } }[]; point: { x: number; y: number } }) => {
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
    <div className="relative w-full h-full min-h-[500px] glass-panel rounded-xl overflow-hidden border border-slate-200 traffic-map-container" style={{ touchAction: 'pan-y' }}>
      <Map
        initialViewState={{
          longitude: 103.8198,
          latitude: 1.3521,
          zoom: 10.5,
        }}
        /* The map container is given an explicit min-height. react-map-gl
           renders its container as height:100%, and a percentage resolves
           against the parent's `height` property - never against `min-height`.
           The wrapper sits in an auto-height flex chain, so that percentage was
           resolving to `auto`, MapLibre sized its canvas to 0px, and the whole
           map rendered as an invisible blank box. Keeping height:100% means it
           still fills correctly whenever an ancestor does have a definite
           height; the min-height guarantees a non-zero box when none does. */
        style={{ width: '100%', height: '100%', minHeight: 500 }}
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
        onError={(e) => {
          // Tile / source failures must not present as an invisible map.
          const msg = String((e as { error?: Error })?.error?.message ?? '');
          if (/tile|source|404|403|network|fetch/i.test(msg)) setTileError(true);
        }}
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

      {/* If the basemap tiles cannot be reached the canvas is otherwise a blank
          grey box with no explanation, which is indistinguishable from "the map
          is broken". Say so explicitly instead. */}
      {tileError && (
        <div
          data-testid="traffic-map-tile-error"
          className="absolute z-20 top-3 left-1/2 -translate-x-1/2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] font-medium text-amber-800 shadow-sm"
        >
          Base map unavailable — traffic zones and incidents are still shown.
        </div>
      )}

      {incidents.length === 0 && (
        <div
          data-testid="traffic-map-no-incidents"
          className="absolute z-10 bottom-3 left-3 rounded-lg border border-slate-200 bg-white/95 px-3 py-2 text-[11px] font-medium text-slate-600 shadow-sm"
        >
          No live traffic incidents reported.
        </div>
      )}

      {hoverInfo && (
        <div
          className="absolute z-20 card-panel p-2 rounded pointer-events-none text-xs"
          style={{ left: hoverInfo.x + 15, top: hoverInfo.y + 15 }}
        >
          {/* The zone GeoJSON exposes `zone_name`, not `name`; reading `name`
              always yielded undefined, so the tooltip rendered empty. */}
          <div className="font-heading font-bold text-slate-900 capitalize">
            {String(
              hoverInfo.feature.properties.zone_name ??
                hoverInfo.feature.properties.name ??
                ''
            )
              .replace('SG_', '')
              .replace(/_/g, ' ')}
          </div>
        </div>
      )}

      {/* Incident Overlay */}
      {selectedIncident && (
        <div
          ref={overlayRef}
          className="absolute z-30 glass-panel-glow p-0 rounded-lg shadow-xl border border-slate-200 min-w-[300px] max-w-[360px] pointer-events-auto"
          style={{
            left: overlayPos.x,
            top: overlayPos.y,
            transform: dragging ? undefined : 'none',
          }}
          onMouseDown={handleOverlayMouseDown}
        >
          <div
            className="overlay-header flex items-center justify-between p-3 bg-slate-50/80 border-b border-slate-200 cursor-move"
            style={{ userSelect: 'none' }}
          >
            <h4 className="font-bold text-slate-900">Traffic Incident</h4>
            <button
              onClick={() => onIncidentClick?.(null)}
              className="text-slate-500 hover:text-slate-900 p-1"
              aria-label="Close"
            >
              ✕
            </button>
          </div>
          <div className="p-3 space-y-2 text-sm">
            <div>
              <span className="text-slate-500">Type:</span>
              <span className="ml-2 font-medium text-slate-800 capitalize">{selectedIncident.type || 'Unknown'}</span>
            </div>
            <div>
              <span className="text-slate-500">Location:</span>
              <span className="ml-2 text-slate-700">{selectedIncident.message || 'Unknown'}</span>
            </div>
            <div>
              <span className="text-slate-500">Zone:</span>
              <span className="ml-2 text-slate-700">{selectedIncident.zone_name || 'N/A'}</span>
            </div>
            <div>
              <span className="text-slate-500">Status:</span>
              <span className="ml-2 text-slate-700">{selectedIncident.status || 'Active'}</span>
            </div>
            {selectedIncident.timestamp && <div>
              <span className="text-slate-500">Reported:</span>
              <span className="ml-2 text-slate-700">{formatSingaporeTime(selectedIncident.timestamp)} SGT</span>
            </div>}
          </div>
        </div>
      )}
    </div>
  );
}
