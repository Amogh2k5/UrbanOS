import type { DrainCondition } from "@/services/api";

// Kept out of WaterMap.tsx so the page can import colours without pulling in the map library.
export const CONDITION_COLOR: Record<DrainCondition, string> = {
  NORMAL: "#4ade80",
  ELEVATED: "#facc15",
  HIGH: "#fb923c",
  CRITICAL: "#ef4444",
  UNAVAILABLE: "#94a3b8",
};
