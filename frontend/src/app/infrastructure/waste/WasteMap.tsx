"use client";

import Map, { Layer, NavigationControl, Source } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import type { MapLayerMouseEvent, StyleSpecification } from "maplibre-gl";
import type { WasteFacilityKind, WasteMapCollection, WasteMapFeature } from "@/services/api";
import { KIND_COLOR } from "./WasteMapColors";
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

/**
 * Clustering-free circle layer (a GeoJSON source renders ~10k+ recycling bins smoothly,
 * unlike one DOM marker per point). Reference data: positions come from static NEA listings.
 */
export default function WasteMap({
  data,
  visibleKinds,
  onSelect,
}: {
  data: WasteMapCollection;
  visibleKinds: WasteFacilityKind[];
  onSelect: (f: WasteMapFeature | null) => void;
}) {
  const [basemapUnavailable, setBasemapUnavailable] = useState(false);
  const handleClick = (e: MapLayerMouseEvent) => {
    const f = e.features?.[0];
    if (!f || f.geometry.type !== "Point") {
      onSelect(null);
      return;
    }
    onSelect({
      type: "Feature",
      geometry: { type: "Point", coordinates: f.geometry.coordinates as [number, number] },
      properties: f.properties as WasteMapFeature["properties"],
    });
  };

  return (
    <div className="relative w-full h-full min-h-[420px] overflow-hidden rounded-xl">
      <Map
        style={{ width: "100%", height: "100%", minHeight: 420 }}
        initialViewState={{ longitude: 103.8198, latitude: 1.3521, zoom: 10.8 }}
        maxBounds={SG_BOUNDS}
        mapStyle={MAP_STYLE}
        onError={(event) => {
          const message = String(event.error?.message ?? "");
          if (/tile|source|network|fetch|404|403/i.test(message)) setBasemapUnavailable(true);
        }}
        dragRotate={false}
        pitchWithRotate={false}
        maxZoom={17}
        minZoom={10}
        interactiveLayerIds={["waste-points"]}
        onClick={handleClick}
        cursor="grab"
      >
        <NavigationControl showCompass={false} position="top-right" />
        <Source id="waste" type="geojson" data={data as unknown as GeoJSON.FeatureCollection}>
          <Layer
            id="waste-points"
            type="circle"
            filter={["in", ["get", "kind"], ["literal", visibleKinds]]}
            paint={{
              "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 2, 14, 4, 17, 7],
              "circle-color": [
                "match", ["get", "kind"],
                "recycling_bins", KIND_COLOR.recycling_bins,
                "ewaste", KIND_COLOR.ewaste,
                "lighting_waste", KIND_COLOR.lighting_waste,
                "disposal_sites", KIND_COLOR.disposal_sites,
                "#94a3b8",
              ],
              "circle-opacity": 0.85,
              "circle-stroke-width": 1,
              "circle-stroke-color": "#ffffff",
            }}
          />
        </Source>
      </Map>
      {basemapUnavailable && (
        <div role="status" aria-live="polite" className="absolute right-4 top-4 z-10 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 shadow-sm">
          Basemap tiles unavailable. Waste locations remain visible.
        </div>
      )}
    </div>
  );
}
