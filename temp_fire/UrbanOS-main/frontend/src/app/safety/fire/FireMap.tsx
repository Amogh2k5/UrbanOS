"use client";

import Map, { Marker, NavigationControl } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FireIncident } from "@/services/api";

const MAP_STYLE = {
  version: 8 as const,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "&copy; OpenStreetMap contributors",
    },
  },
  layers: [
    {
      id: "osm-layer",
      source: "osm",
      type: "raster",
      minzoom: 0,
      maxzoom: 19,
    },
  ],
} as const;

function markerClass(severity: FireIncident["severity"]) {
  if (severity === "CRITICAL") return "bg-red-500 shadow-[0_0_18px_rgba(239,68,68,0.9)]";
  if (severity === "HIGH") return "bg-orange-500 shadow-[0_0_16px_rgba(249,115,22,0.8)]";
  if (severity === "MODERATE") return "bg-yellow-400 shadow-[0_0_14px_rgba(250,204,21,0.7)]";
  return "bg-cyan-400 shadow-[0_0_12px_rgba(34,211,238,0.7)]";
}

export default function FireMap({
  incidents,
  onSelect,
}: {
  incidents: FireIncident[];
  onSelect?: (incident: FireIncident) => void;
}) {
  const mapped = incidents.filter(
    (i) => typeof i.latitude === "number" && typeof i.longitude === "number"
  );

  return (
    <div className="relative w-full h-full min-h-[500px] overflow-hidden rounded-xl">
      <Map
        initialViewState={{ longitude: 103.8198, latitude: 1.3521, zoom: 11.4 }}
        maxBounds={[[103.55, 1.15], [104.15, 1.50]] as any}
        mapStyle={MAP_STYLE as any}
        dragRotate={false}
        pitchWithRotate={false}
        maxZoom={17}
        minZoom={10.5}
      >
        <NavigationControl showCompass={false} position="top-right" />
        {mapped.map((incident) => (
          <Marker
            key={incident.id}
            longitude={incident.longitude as number}
            latitude={incident.latitude as number}
            anchor="center"
            onClick={(e) => {
              e.originalEvent.stopPropagation();
              onSelect?.(incident);
            }}
          >
            <button
              type="button"
              aria-label={incident.title}
              className={`w-5 h-5 rounded-full border-2 border-white ${markerClass(
                incident.severity
              )} hover:scale-125 transition-transform`}
              title={incident.title}
            />
          </Marker>
        ))}
      </Map>

      {mapped.length === 0 && (
        <div className="absolute inset-x-4 bottom-4 glass-panel p-3 rounded-lg border border-yellow-500/20 text-xs text-gray-400">
          No verified incident coordinates were supplied by the current public SCDF
          source. The map remains available for geocoded incidents when coordinates
          are provided.
        </div>
      )}

      <div className="absolute left-4 top-4 glass-panel p-3 rounded-lg border border-gray-800/80">
        <div className="text-[10px] uppercase tracking-[0.2em] text-gray-400">
          Singapore
        </div>
        <div className="text-sm font-semibold text-white">Fire incident map</div>
        <div className="text-[10px] text-gray-500 mt-1">
          Verified source coordinates only
        </div>
      </div>
    </div>
  );
}
