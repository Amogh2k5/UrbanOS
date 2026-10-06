"""Deterministic processing for official crime datasets."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.app.safety.crime.data import SCAM_TYPES_2025
from backend.app.safety.crime.models import (
    ArrestSeries, CrimeReport, CrimeSeries, MajorOffenceSeries, NpcCrimeSeries,
    ScamType,
)

YEAR_KEYS = [str(y) for y in range(2011, 2026)]


def _clean_name(value: Any) -> str:
    return str(value or "").strip()


def _numeric(value: Any) -> Optional[float]:
    if value in (None, "", "na", "NA", "null", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pivot_records(records: Iterable[Dict[str, Any]], name_key: str = "DataSeries") -> List[Dict[str, Any]]:
    result = []
    for row in records:
        name = _clean_name(row.get(name_key))
        if not name:
            continue
        values = {year: _numeric(row.get(year)) for year in YEAR_KEYS if year in row}
        result.append({"name": name, "values": values})
    return result


def find_series(records: Iterable[Dict[str, Any]], exact: str) -> Optional[Dict[str, Any]]:
    for row in records:
        if _clean_name(row.get("DataSeries")).lower() == exact.lower():
            return row
    return None


def to_values(row: Optional[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    if not row:
        return {}
    return {year: _numeric(row.get(year)) for year in YEAR_KEYS if year in row}


def process_snapshot(snapshot) -> CrimeReport:
    crime = snapshot.datasets.get("crime_cases", [])
    major = snapshot.datasets.get("major_offences", [])
    arrests = snapshot.datasets.get("arrests", [])
    npc = snapshot.datasets.get("npc", [])

    physical = find_series(crime, "Physical Crime Cases Recorded")
    scams_cyber = find_series(crime, "Scams & Cybercrimes Cases Recorded")
    scams = find_series(crime, "Scams")
    physical_rate = find_series(crime, "Physical Crime Rate")

    arrest_total_rows = [
        r for r in arrests
        if _clean_name(r.get("DataSeries")).startswith("Total Persons Arrested For ")
    ]

    overview_names = {
        "Crimes Against Persons", "Violent / Serious Property Crimes",
        "Housebreaking And Related Crimes", "Theft And Related Crimes",
        "Commercial Crimes", "Miscellaneous Crimes",
        "Scams & Cybercrimes Cases Recorded", "Scams",
    }
    overview = [
        CrimeSeries(name=_clean_name(r.get("DataSeries")), values=to_values(r))
        for r in crime
        if _clean_name(r.get("DataSeries")) in overview_names
    ]

    major_series = [
        MajorOffenceSeries(name=_clean_name(r.get("DataSeries")), values=to_values(r))
        for r in major
        if _clean_name(r.get("DataSeries")) and _clean_name(r.get("DataSeries")) != "Total"
    ]

    arrest_series = [
        ArrestSeries(
            offence=_clean_name(r.get("DataSeries")).replace("Total Persons Arrested For ", ""),
            values=to_values(r),
        )
        for r in arrest_total_rows
    ]

    # NPC data is location-based but does not provide coordinates in this
    # dataset. Keep it tabular; do not invent lat/lon for a heatmap.
    npc_series: List[NpcCrimeSeries] = []
    for r in npc:
        name = _clean_name(r.get("DataSeries"))
        # The official dataset interleaves an NPC/Police-Division total row
        # with offence rows. Only rows naming a police division/NPC are treated
        # as geographic units; offence rows are not mislabeled as places.
        if not name:
            continue
        if ("NPC" in name or name.endswith(" - Total")) and (
            "Police Division" in name
        ):
            npc_series.append(
                NpcCrimeSeries(
                    npc=name,
                    offence="selected major offences total",
                    values=to_values(r),
                )
            )

    limitations = [
        "Official crime data used here is annual/historical, not an operational live incident feed.",
        "2022 onward SPF reporting separates Physical Crimes from Scams & Cybercrimes; older years are not directly equivalent for every subcategory.",
        "NPC geographic data covers cases with known locations but supplies no latitude/longitude in this dataset; no crime heatmap is generated.",
        "Scam category/loss detail comes from the SPF Annual Scam and Cybercrime Brief 2025 infographic, not a machine-readable API.",
    ]
    if not npc:
        limitations.append("NPC geographic dataset was unavailable, so geographic analysis is omitted.")

    return CrimeReport(
        generated_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        source_status=snapshot.source_status,
        data_period="2011-2025 for selected major offences/arrests/NPC; 2020-2025 for aggregate crime cases; scam detail 2025",
        data_sources=[
            "data.gov.sg / SINGSTAT — Crime Cases Recorded, Annual",
            "data.gov.sg / SINGSTAT — Cases Recorded For Selected Major Offences, Annual",
            "data.gov.sg / SINGSTAT — Persons Arrested For Selected Major Offences By Sex And Broad Age Group, Annual",
            "data.gov.sg / SINGSTAT — Selected Major Offences Recorded By Neighbourhood Police Centre (NPC), Annual",
            "Singapore Police Force — Annual Scam and Cybercrime Brief 2025 infographic",
        ],
        total_physical_crime_2025=int(physical["2025"]) if physical and _numeric(physical.get("2025")) is not None else None,
        total_scams_cybercrime_2025=int(scams_cyber["2025"]) if scams_cyber and _numeric(scams_cyber.get("2025")) is not None else None,
        total_scams_2025=int(scams["2025"]) if scams and _numeric(scams.get("2025")) is not None else None,
        physical_crime_rate_2025=_numeric(physical_rate.get("2025")) if physical_rate else None,
        arrests_2025_total_selected_offences=None,
        overview=overview,
        major_offences=major_series,
        arrests=arrest_series,
        npc_geography=npc_series,
        scam_types=[ScamType(**x) for x in SCAM_TYPES_2025],
        geographic_scope="Neighbourhood Police Centre (NPC), cases with known locations; tabular only",
        limitations=limitations,
        warnings=snapshot.warnings,
        errors=snapshot.errors,
        is_ml_prediction=False,
    )
