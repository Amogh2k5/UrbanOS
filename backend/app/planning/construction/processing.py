"""Construction data processing: transforms raw data into ConstructionReport."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from .models import (
    ConstructionReport,
    ConstructionInsight,
    GreenMarkBuilding,
    PipelineRecord,
    ConstructionSource,
)


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _parse_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _build_greenmark_summary(buildings: list[dict[str, Any]]) -> dict[str, Any]:
    """Build summary statistics from Green Mark buildings."""
    if not buildings:
        return {
            "total_records": 0,
            "by_rating": {},
            "by_type": {},
            "certified_buildings": 0,
        }

    ratings = Counter()
    types = Counter()
    with_dates = 0
    with_expiry = 0
    with_postal = 0

    for b in buildings:
        rating = _parse_str(b.get("Rating"))
        if rating:
            ratings[rating] += 1

        ptype = _parse_str(b.get("Project_Type"))
        if ptype:
            types[ptype] += 1

        if _parse_str(b.get("e_cert")):
            with_dates += 1
        if _parse_str(b.get("Expiry")):
            with_expiry += 1
        if _parse_str(b.get("Postal_Code")):
            with_postal += 1

    return {
        "total_records": len(buildings),
        "by_rating": dict(ratings.most_common()),
        "by_type": dict(types.most_common()),
        "certified_buildings": len(buildings),
        "records_with_cert_date": with_dates,
        "records_with_expiry": with_expiry,
        "records_with_postal": with_postal,
    }


def _build_pipeline_trend(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build pipeline trend from URA records."""
    trend = []
    for r in records:
        year = _parse_int(r.get("year"))
        if year is None:
            continue
        trend.append({
            "year": year,
            "provisional_permission": _parse_int(r.get("provisional_permission")),
            "written_permission": _parse_int(r.get("written_permission")),
            "building_plan_approval": _parse_int(r.get("building_plan_approval")),
            "building_commencement": _parse_int(r.get("building_commencement")),
            "building_completion": _parse_int(r.get("building_completion")),
        })
    return sorted(trend, key=lambda x: x["year"])


def _build_greenmark_by_rating(buildings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate Green Mark buildings by rating."""
    ratings = Counter()
    for b in buildings:
        rating = _parse_str(b.get("Rating"))
        if rating:
            ratings[rating] += 1
    return [{"rating": k, "count": v} for k, v in ratings.most_common()]


def _build_greenmark_by_type(buildings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate Green Mark buildings by project type."""
    types = Counter()
    for b in buildings:
        ptype = _parse_str(b.get("Project_Type"))
        if ptype:
            types[ptype] += 1
    return [{"project_type": k, "count": v} for k, v in types.most_common()]


def _parse_greenmark_buildings(records: list[dict[str, Any]]) -> list[GreenMarkBuilding]:
    """Parse raw records into GreenMarkBuilding models."""
    buildings = []
    for r in records:
        building = GreenMarkBuilding(
            vault_id=_parse_str(r.get("vault_id")),
            reference_no=_parse_str(r.get("Reference_No")),
            project_name=_parse_str(r.get("Project_Name")),
            actual_project_name=_parse_str(r.get("Actual_Project_Name")),
            postal_code=_parse_str(r.get("Postal_Code")),
            rating=_parse_str(r.get("Rating")),
            sle_ze_pe=_parse_str(r.get("SLE_ZE_PE")),
            project_type=_parse_str(r.get("Project_Type")),
            gfa=_parse_str(r.get("GFA")),
            re_certification=_parse_str(r.get("Re_Certification")),
            previous_gm_cert_reference_no=_parse_str(r.get("Previous_GM_Cert_Reference_No")),
            gm_version=_parse_str(r.get("GM_Version")),
            e_cert=_parse_str(r.get("e_cert")),
            expiry=_parse_str(r.get("Expiry")),
            developer=_parse_str(r.get("Developer")),
            architect=_parse_str(r.get("Architect")),
            me_engineer=_parse_str(r.get("ME_Engineer")),
            cs_engineer=_parse_str(r.get("CS_Engineer")),
            facility_manager=_parse_str(r.get("Facility_Manager")),
            esd_consultant=_parse_str(r.get("ESD_Consultant")),
            geometry=r.get("geometry"),
        )
        buildings.append(building)
    return buildings


def _parse_pipeline_records(records: list[dict[str, Any]]) -> list[PipelineRecord]:
    """Parse raw records into PipelineRecord models."""
    pipeline = []
    for r in records:
        year = _parse_int(r.get("year"))
        if year is None:
            continue
        record = PipelineRecord(
            year=year,
            provisional_permission=_parse_int(r.get("provisional_permission")),
            written_permission=_parse_int(r.get("written_permission")),
            building_plan_approval=_parse_int(r.get("building_plan_approval")),
            building_commencement=_parse_int(r.get("building_commencement")),
            building_completion=_parse_int(r.get("building_completion")),
        )
        pipeline.append(record)
    return pipeline


def _build_map_data(geojson_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Build map data from GeoJSON records."""
    if not geojson_records:
        return {"features": [], "available": False, "note": "No GeoJSON data available"}

    features = []
    for r in geojson_records:
        geom = r.get("geometry")
        if geom and isinstance(geom, dict) and geom.get("type") and geom.get("coordinates"):
            props = {k: v for k, v in r.items() if k != "geometry"}
            feature = {
                "type": "Feature",
                "geometry": geom,
                "properties": props,
            }
            features.append(feature)

    return {
        "type": "FeatureCollection",
        "features": features,
        "available": len(features) > 0,
        "feature_count": len(features),
    }


def _build_sources(sources: dict[str, Any]) -> list[ConstructionSource]:
    """Convert source results to ConstructionSource models."""
    result = []
    for key, s in sources.items():
        source = ConstructionSource(
            key=key,
            name=s.name,
            agency=s.agency,
            url=s.url,
            status=s.status,
            retrieved_at=s.retrieved_at,
            error=s.error,
            record_count=len(s.records),
            fields=s.fields,
            total_count=s.total_count,
            coverage_start=s.coverage_start,
            coverage_end=s.coverage_end,
            last_updated_at=s.last_updated_at,
        )
        result.append(source)
    return result


def build_construction_report(snapshot: dict[str, Any]) -> ConstructionReport:
    """Build ConstructionReport from raw snapshot."""
    sources = snapshot.get("sources", {})
    errors = snapshot.get("errors", [])

    # Green Mark buildings (CSV)
    gm_records = sources.get("greenmark_buildings", type("", (), {"records": []})).records

    # URA Pipeline
    pipeline_records_raw = sources.get("ura_construction_pipeline", type("", (), {"records": []})).records

    # Green Mark GeoJSON
    geojson_records = sources.get("greenmark_geojson", type("", (), {"records": []})).records

    # Building Energy (optional, 2018 only)
    energy_records = sources.get("building_energy", type("", (), {"records": []})).records

    # Build summaries
    gm_summary = _build_greenmark_summary(gm_records)
    pipeline_trend = _build_pipeline_trend(pipeline_records_raw)
    gm_by_rating = _build_greenmark_by_rating(gm_records)
    gm_by_type = _build_greenmark_by_type(gm_records)
    parsed_buildings = _parse_greenmark_buildings(gm_records)
    parsed_pipeline = _parse_pipeline_records(pipeline_records_raw)
    map_data = _build_map_data(geojson_records)
    source_models = _build_sources(sources)

    # Determine overall status
    available_sources = sum(1 for s in sources.values() if s.status == "available")
    total_sources = len(sources)
    if available_sources == total_sources:
        status = "OK"
    elif available_sources > 0:
        status = "PARTIAL"
    else:
        status = "UNAVAILABLE"

    # KPIs
    latest_pipeline = pipeline_trend[-1] if pipeline_trend else {}
    kpis = {
        "greenmark_total_records": gm_summary["total_records"],
        "greenmark_by_rating": gm_summary["by_rating"],
        "greenmark_by_type": gm_summary["by_type"],
        "latest_pipeline_year": latest_pipeline.get("year"),
        "latest_provisional_permission": latest_pipeline.get("provisional_permission"),
        "latest_written_permission": latest_pipeline.get("written_permission"),
        "latest_building_plan_approval": latest_pipeline.get("building_plan_approval"),
        "latest_building_commencement": latest_pipeline.get("building_commencement"),
        "latest_building_completion": latest_pipeline.get("building_completion"),
        "map_features_available": map_data.get("available", False),
        "map_feature_count": map_data.get("feature_count", 0),
    }

    # Insights
    insights = []
    if gm_records:
        insights.append(ConstructionInsight(
            question="How many Green Mark certified buildings are in the dataset?",
            answer=f"{gm_summary['total_records']} records with ratings: {', '.join(f'{k} ({v})' for k, v in gm_summary['by_rating'].items())}",
            data_kind="historical",
        ))
    if pipeline_trend:
        latest = pipeline_trend[-1]
        insights.append(ConstructionInsight(
            question="What is the latest residential construction pipeline data?",
            answer=f"Year {latest['year']}: {latest.get('building_completion', 'N/A')} completions, {latest.get('building_commencement', 'N/A')} commencements, {latest.get('building_plan_approval', 'N/A')} approvals.",
            data_kind="historical",
        ))
    if geojson_records:
        insights.append(ConstructionInsight(
            question="Is geospatial data available for Green Mark buildings?",
            answer=f"Yes, {len(geojson_records)} GeoJSON features available for mapping.",
            data_kind="geospatial",
        ))
    else:
        insights.append(ConstructionInsight(
            question="Is geospatial data available for Green Mark buildings?",
            answer="GeoJSON dataset returned no usable features.",
            data_kind="geospatial",
        ))

    # Limitations
    limitations = [
        "Green Mark dataset covers voluntary certification only; legislated projects and opt-outs excluded.",
        "URA pipeline data covers private residential only (2013–2017); no recent years available.",
        "Building Energy dataset covers 2018 only; not current performance.",
        "GeoJSON dataset may not have valid geometry for all buildings; verify before use.",
        "Postal codes are not precise coordinates; do not use for exact mapping.",
        "Data refresh frequency varies by source; check source metadata for latest update.",
    ]

    # Data timestamps
    data_timestamps = {}
    for key, s in sources.items():
        if s.retrieved_at:
            data_timestamps[f"{key}_retrieved"] = s.retrieved_at
        if s.last_updated_at:
            data_timestamps[f"{key}_source_updated"] = s.last_updated_at
        if s.coverage_start:
            data_timestamps[f"{key}_coverage_start"] = s.coverage_start
        if s.coverage_end:
            data_timestamps[f"{key}_coverage_end"] = s.coverage_end

    return ConstructionReport(
        generated_at=datetime.now(),
        status=status,
        kpis=kpis,
        greenmark_summary=gm_summary,
        pipeline_trend=pipeline_trend,
        greenmark_by_rating=gm_by_rating,
        greenmark_by_type=gm_by_type,
        greenmark_buildings=parsed_buildings,
        pipeline_records=parsed_pipeline,
        map_data=map_data,
        sources=source_models,
        errors=errors,
        limitations=limitations,
        insights=insights,
        confidence="medium" if status == "OK" else "low",
        data_timestamps=data_timestamps,
        is_ml_prediction=False,
    )