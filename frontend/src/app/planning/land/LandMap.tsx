"use client";

import Map, { Marker, NavigationControl, Source, Layer } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import type { StyleSpecification, LayerSpecification } from "maplibre-gl";
import type { LandMapLayer, LandPlanningArea } from "@/services/api";
import { useState } from "react";

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

const PA_FILL: LayerSpecification = {
  id: "pa-fill",
  type: "fill",
  source: "pa",
  paint: {
    "fill-color": "#22d3ee",
    "fill-opacity": ["case", ["get", "selected"], 0.35, 0.12],
  },
};

const PA_LINE: LayerSpecification = {
  id: "pa-line",
  type: "line",
  source: "pa",
  paint: { "line-color": "#67e8f9", "line-width": ["case", ["get", "selected"], 2, 0.7], "line-opacity": 0.8 },
};

interface Props {
  layers: LandMapLayer[];
  planningAreas: LandPlanningArea[];
  selected: LandPlanningArea | null;
  onSelect: (pa: LandPlanningArea) => void;
  showSensors: boolean;
}

/**
 * Land intelligence map.
 *
 * Only layers the backend actually produced are drawn. Land-use zone and
 * cadastral geometry are intentionally absent (see /map `layers_unavailable`)
 * and the map says so rather than implying they are missing from the data.
 */
export default function LandMap({ layers, planningAreas, selected, onSelect, showSensors }: Props) {
  const [basemapUnavailable, setBasemapUnavailable] = useState(false);
  const paLayer = layers.find((l) => l.id === "planning_areas");
  const glsLayer = layers.find((l) => l.id === "gls_sites");

  const features = (paLayer?.data.features ?? []).map((f, i) => ({
    type: "Feature" as const,
    geometry: f.geometry,
    properties: {
      ...f.properties,
      selected: planningAreas[i]?.name === selected?.name ? 1 : 0,
    },
  }));

  const glsFeatures = (glsLayer?.data.features ?? []) as {
    type: "Feature";
    geometry: { type: "Point"; coordinates: [number, number] };
    properties: Record<string, unknown>;
  }[];

  const empty = !paLayer && !glsLayer;

  return (
    <div className="relative w-full h-full min-h-[460px] overflow-hidden rounded-xl">
      <Map
        style={{ width: '100%', height: '100%', minHeight: 460 }}
        initialViewState={{ longitude: 103.82, latitude: 1.35, zoom: 10.4 }}
        maxBounds={SG_BOUNDS}
        mapStyle={MAP_STYLE}
        onError={(event) => {
          const message = String(event.error?.message ?? "");
          if (/tile|source|network|fetch|404|403/i.test(message)) setBasemapUnavailable(true);
        }}
        dragRotate={false}
        pitchWithRotate={false}
        maxZoom={16}
        minZoom={9.5}
        interactiveLayerIds={paLayer && features.length > 0 ? ["pa-fill"] : undefined}
        onClick={(e) => {
          const f = e.features?.[0];
          if (!f) return;
          const name = (f.properties as Record<string, unknown>)?.name;
          const pa = planningAreas.find((p) => p.name === name);
          if (pa) onSelect(pa);
        }}
      >
        <NavigationControl showCompass={false} position="top-right" />

        {paLayer && features.length > 0 && (
          <Source id="pa" type="geojson" data={{ type: "FeatureCollection", features }}>
            <Layer {...PA_FILL} />
            <Layer {...PA_LINE} />
          </Source>
        )}

        {glsLayer && glsFeatures.map((f, i) => (
          <Marker
            key={`gls-${i}`}
            longitude={f.geometry.coordinates[0]}
            latitude={f.geometry.coordinates[1]}
            anchor="center"
          >
            <button
              type="button"
              aria-label={String(f.properties.location ?? "GLS site")}
              title={`${f.properties.location ?? "GLS site"} — awarded ${f.properties.award_year ?? "?"}`}
              className="w-2 h-2 rounded-full border border-white/80 hover:scale-150 transition-transform"
              style={{ background: "#fbbf24" }}
            />
          </Marker>
        ))}
      </Map>

      {basemapUnavailable && (
        <div role="status" aria-live="polite" className="absolute right-4 top-4 z-10 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 shadow-sm">
          Basemap tiles unavailable. Available planning layers remain visible.
        </div>
      )}

      <div className="absolute left-4 top-4 card-panel p-3 rounded-lg border border-slate-200">
        <div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">Planning areas</div>
        <div className="text-sm font-semibold text-slate-900">{paLayer?.data.features.length ?? 0} boundaries</div>
        <div className="text-[10px] text-slate-500 mt-1">Master Plan 2025 (land only, sea excluded)</div>
        {glsLayer && (
          <div className="text-[10px] text-slate-500 mt-1 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full inline-block" style={{ background: "#fbbf24" }} />
            {glsLayer.data.features.length} awarded GLS sites
          </div>
        )}
      </div>

      {showSensors && (
        <div className="absolute right-4 bottom-4 card-panel p-2 rounded-lg border border-slate-200 text-[10px] text-slate-500">
          GLS points shown for the most recent awards only.
        </div>
      )}

      {empty && (
        <div className="absolute inset-0 flex items-center justify-center p-6 text-center">
          <div className="card-panel p-4 rounded-lg border border-yellow-500/25 text-xs text-slate-500 max-w-sm">
            No map layers are available. The planning-area and GLS sources did not return geometry in this
            build.
          </div>
        </div>
      )}
    </div>
  );
}
