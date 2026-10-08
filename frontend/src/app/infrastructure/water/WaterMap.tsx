"use client";

import Map, { Marker, NavigationControl } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import type { StyleSpecification } from "maplibre-gl";
import type { WaterDrainSensorStatus } from "@/services/api";
import { CONDITION_COLOR } from "./waterConstants";

const MAP_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "&copy; OpenStreetMap contributors",
    },
  },
  layers: [{ id: "osm-layer", source: "osm", type: "raster", minzoom: 0, maxzoom: 19 }],
};

const SG_BOUNDS: [number, number, number, number] = [103.55, 1.15, 104.15, 1.5];

export default function WaterMap({
  sensors,
  readingsAvailable,
  onSelect,
  selectedId,
}: {
  sensors: WaterDrainSensorStatus[];
  readingsAvailable: boolean;
  onSelect?: (s: WaterDrainSensorStatus) => void;
  selectedId?: string | null;
}) {
  return (
    <div className="relative w-full h-full min-h-[460px] overflow-hidden rounded-xl">
      <Map
        initialViewState={{ longitude: 103.8198, latitude: 1.3521, zoom: 10.8 }}
        maxBounds={SG_BOUNDS}
        mapStyle={MAP_STYLE}
        dragRotate={false}
        pitchWithRotate={false}
        maxZoom={17}
        minZoom={10}
      >
        <NavigationControl showCompass={false} position="top-right" />
        {sensors.map((s) => {
          const selected = s.sensor.id === selectedId;
          return (
            <Marker key={s.sensor.id} longitude={s.sensor.longitude} latitude={s.sensor.latitude} anchor="center"
              onClick={(e) => { e.originalEvent.stopPropagation(); onSelect?.(s); }}>
              <button
                type="button"
                aria-label={s.sensor.name || s.sensor.id}
                title={`${s.sensor.name || s.sensor.id} — ${s.condition === "UNAVAILABLE" ? "no reading available" : s.condition}`}
                className={`rounded-full border border-white/80 hover:scale-150 transition-transform ${selected ? "w-4 h-4 ring-2 ring-white" : "w-2.5 h-2.5"}`}
                style={{ background: CONDITION_COLOR[s.condition] }}
              />
            </Marker>
          );
        })}
      </Map>

      <div className="absolute left-4 top-4 glass-panel p-3 rounded-lg border border-gray-800/80">
        <div className="text-[10px] uppercase tracking-[0.2em] text-gray-400">PUB drain &amp; canal sensors</div>
        <div className="text-sm font-semibold text-white">{sensors.length} locations</div>
        <div className="text-[10px] text-gray-500 mt-1">
          {readingsAvailable ? "Coloured by latest reading" : "Locations only — grey = no official reading"}
        </div>
      </div>

      {!readingsAvailable && (
        <div className="absolute inset-x-4 bottom-4 glass-panel p-3 rounded-lg border border-yellow-500/20 text-xs text-gray-400">
          PUB publishes where its sensors are, but no official open feed of their water-level readings was found.
          Nothing here is a live drain condition.
        </div>
      )}
    </div>
  );
}
