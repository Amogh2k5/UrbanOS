"""Deterministic Fire/Safety classification rules."""
from __future__ import annotations

import re
from typing import Optional

from backend.app.safety.fire.models import FireSeverity


def classify_status(text: str) -> str:
    t = text.lower()
    if any(p in t for p in (
        "operations are still ongoing", "firefighting operations are ongoing",
        "currently ongoing", "damping down", "firefighting operations continue",
        "fire fighting operations are still ongoing",
    )):
        return "ACTIVE"
    if any(p in t for p in (
        "fully extinguished", "fire was extinguished", "fire was put out",
        "fire was brought under control", "brought under control",
        "fire was under control",
    )):
        return "RESOLVED"
    return "UNKNOWN"


def classify_severity(text: str) -> FireSeverity:
    """Classify only when the published report contains strong evidence.

    This is not a predictive score. UNKNOWN is preferred when the source does
    not provide enough evidence.
    """
    t = text.lower()
    if re.search(r"\b(body|bodies|fatalit|died|death)\b", t):
        return "CRITICAL"
    if any(p in t for p in (
        "chemical", "flammable", "hazmat", "multiple casualties",
        "major fire", "well alight", "engulfed the entire",
    )):
        return "HIGH"
    if any(p in t for p in ("casualty", "injur", "ambulance", "rescue operation")):
        return "MODERATE"
    return "UNKNOWN"


def classify_type(title: str, text: str) -> Optional[str]:
    t = f"{title} {text}".lower()
    if "vehicle" in t or "ambulance" in t:
        return "Vehicle / transport fire"
    if "construction" in t:
        return "Construction-site fire"
    if "factory" in t or "industrial" in t or "plant" in t:
        return "Industrial / factory fire"
    if "residential" in t or "condominium" in t or "apartment" in t or "block " in t:
        return "Residential / building fire"
    if "vegetation" in t or "grass" in t or "reclaimed land" in t:
        return "Vegetation / open-area fire"
    if "ship" in t or "vessel" in t or "marine" in t:
        return "Marine fire"
    if "fire" in t:
        return "Fire incident"
    return None


def infer_region(location_text: Optional[str], latitude: Optional[float], longitude: Optional[float]) -> Optional[str]:
    """Conservative region tagging from explicit place names.

    We only label regions when a strong location keyword is present. Coordinates
    are retained for the map but are not used to invent administrative borders.
    """
    if not location_text:
        return None
    t = location_text.lower()
    groups = {
        "North": ("woodlands", "yishun", "sembawang", "canberra", "mandai", "lim chu kang", "kranji"),
        "North-East": ("hougang", "sengkang", "punggol", "serangoon", "kovan"),
        "East": ("bedok", "tampines", "pasir ris", "changi", "simei", "eunos", "geylang"),
        "West": ("jurong", "tuas", "clementi", "bukit batok", "bukit panjang", "choa chu kang", "boon lay"),
        "South": ("sentosa", "telok blangah", "harbourfront", "pasir panjang", "alexandra"),
        "Central": ("orchard", "city hall", "raffles", "tanjong pagar", "robinson road", "toa payoh", "bishan", "novena", "ang mo kio", "bukit timah"),
    }
    for region, words in groups.items():
        if any(w in t for w in words):
            # Collapse North-East into East for the five-region dashboard.
            return "East" if region == "North-East" else region
    return None
