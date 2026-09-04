"""Geographic zone lookup for Singapore traffic zones.

Loads zones from GeoJSON and provides point-in-polygon lookup.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_DEFAULT_GEOJSON_PATH = Path("traffic/data/processed/singapore_traffic_zones.geojson")


class ZoneLookup:
    """Singleton zone lookup service."""
    
    _instance: Optional["ZoneLookup"] = None
    _geojson: Optional[Dict[str, Any]] = None
    _features: List[Dict[str, Any]] = []
    
    def __new__(cls) -> "ZoneLookup":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def load(self, geojson_path: Optional[Path] = None) -> None:
        """Load zones from GeoJSON file."""
        path = geojson_path or _DEFAULT_GEOJSON_PATH
        with open(path, "r") as f:
            self._geojson = json.load(f)
        self._features = self._geojson.get("features", [])
        log.info(f"Loaded {len(self._features)} traffic zones from {path}")
    
    @property
    def is_loaded(self) -> bool:
        return self._geojson is not None
    
    def _point_in_polygon(self, lon: float, lat: float, polygon: List[List[float]]) -> bool:
        """Ray casting algorithm to test if point is in polygon."""
        ring = polygon[0]
        inside = False
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside
    
    def lookup(self, lat: float, lon: float) -> Dict[str, Optional[str]]:
        """Look up zone for a given latitude/longitude.
        
        Args:
            lat: Latitude in WGS84
            lon: Longitude in WGS84
            
        Returns:
            Dict with zone_id and zone_name, or None/unknown if outside all zones.
        """
        if not self.is_loaded:
            self.load()
        
        # Check Sentosa first (carved out of Central South)
        for feature in self._features:
            if feature["properties"]["zone_id"] == "SG_SENTOSA":
                geom = feature.get("geometry", {})
                coords = geom.get("coordinates", [])
                if coords and self._point_in_polygon(lon, lat, coords):
                    props = feature.get("properties", {})
                    return {
                        "zone_id": props.get("zone_id"),
                        "zone_name": props.get("zone_name"),
                    }
        
        # Check all other features
        for feature in self._features:
            if feature["properties"]["zone_id"] == "SG_SENTOSA":
                continue
            geom = feature.get("geometry", {})
            coords = geom.get("coordinates", [])
            if coords and self._point_in_polygon(lon, lat, coords):
                props = feature.get("properties", {})
                return {
                    "zone_id": props.get("zone_id"),
                    "zone_name": props.get("zone_name"),
                }
        
        return {"zone_id": None, "zone_name": "unknown"}
    
    def get_all_zones(self) -> List[Dict[str, str]]:
        """Get list of all zones."""
        if not self.is_loaded:
            self.load()
        return [
            {
                "zone_id": f["properties"]["zone_id"],
                "zone_name": f["properties"]["zone_name"],
                "description": f["properties"].get("description", ""),
            }
            for f in self._features
        ]


# Global instance
zone_lookup = ZoneLookup()


def get_zone(lat: float, lon: float) -> Dict[str, Optional[str]]:
    """Convenience function to look up zone for a coordinate."""
    return zone_lookup.lookup(lat, lon)


def get_all_zones() -> List[Dict[str, str]]:
    """Get all zone definitions."""
    return zone_lookup.get_all_zones()