import type { WasteFacilityKind } from "@/services/api";

/** Layer colours shared by the map and the legend (kept out of WasteMap.tsx so maplibre loads lazily). */
export const KIND_COLOR: Record<WasteFacilityKind, string> = {
  recycling_bins: "#4ade80",
  ewaste: "#38bdf8",
  lighting_waste: "#facc15",
  disposal_sites: "#fb7185",
};
