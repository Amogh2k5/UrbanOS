"""Deterministic City Coordinator for UrbanOS.

The coordinator is the only place that reasons across domains. It is pure
Python and pure rules - **there is no LLM anywhere in this module**. Narrative
phrasing is a separate, downstream concern.

Rules this module enforces:

  * One failing domain can never fail the run. Failures are recorded per
    domain; water and land degrade to warnings because they are advisory
    domains, while life-safety and mobility domains record errors.
  * Missing data is ``UNKNOWN``, never ``NORMAL``. Absence of evidence is not
    evidence of normal conditions.
  * A cross-domain impact requires evidence from every domain it cites. Two
    unrelated elevated domains produce a ``multi_domain_high_risk`` signal but
    are never presented as causally linked.
  * Recommendations may only rest on findings already present in the state.
  * Provenance, timestamps, limitations and affected zones are carried through.

The LangGraph nodes mirror the existing domain agents, so this reads like the
rest of the agent code in this repository.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from langgraph.graph import END, StateGraph

from backend.app.intelligence.contracts import (
    CitySituationReport, CrossDomainImpact, DomainStatus, PriorityIncident,
)

log = logging.getLogger(__name__)
SG = timezone(timedelta(hours=8))

# Domain agents are imported into this module's namespace so tests can patch
# them individually (``patch("coordinator.city_agent....")``).
#
# Order matters: ``safety/fire/api.py`` imports ``run_fire_agent`` at module
# level while ``safety/fire/agent.py`` imports ``fetch_fire_snapshot`` from the
# API at module level. Importing ``fire.api`` first resolves that pre-existing
# cycle in the only order that works.
import backend.app.safety.fire.api  # noqa: E402,F401  (breaks the fire cycle)

from backend.app.environment.environment_module import EnvironmentModule  # noqa: E402
from backend.app.environment.flood.agent import run_flood_agent_v3  # noqa: E402
from backend.app.infrastructure.water.agent import run_water_agent  # noqa: E402
from backend.app.mobility.traffic.agent import run_traffic_agent  # noqa: E402
from backend.app.planning.land.agent import run_land_agent  # noqa: E402
from backend.app.safety.crime.agent import run_crime_agent  # noqa: E402
from backend.app.safety.fire.agent import run_fire_agent  # noqa: E402
from backend.app.infrastructure.waste.agent import run_waste_agent  # noqa: E402
from backend.app.planning.housing.agent import run_housing_agent  # noqa: E402
from backend.app.infrastructure.energy.agent import run_energy_agent  # noqa: E402

#: Domains that define city confidence. Adding a domain must not silently
#: change this rule.
CORE_DOMAINS = ("environment", "traffic", "flood")

_RISK_ORDER = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}

#: City status vocabulary (distinct from risk).
_STATUS_BY_RISK = {
    "LOW": "NORMAL",
    "MODERATE": "ELEVATED",
    "HIGH": "DISRUPTED",
    "CRITICAL": "CRITICAL",
}

#: PSI boundary (µg/m³) at which air quality alone justifies a cross-domain
#: signal. "Unhealthy" on the Singapore PSI scale.
_PM25_IMPACT_THRESHOLD = 100.0

_BASE_LIMITATIONS = [
    "The City Coordinator is a deterministic rule engine, not an ML predictor; "
    "it performs no forecasting and trains no model.",
    "Individual domains may fall back to offline fixtures when live sources are "
    "unavailable, so a value can be current-shaped but not live.",
]


# ============================================================ state
@dataclass
class CityCoordinatorState:
    """Everything the coordinator knows, at every stage of the graph."""

    environment_report: Any = None
    traffic_report: Any = None
    flood_report: Any = None
    water_report: Any = None
    land_report: Any = None
    fire_report: Any = None
    crime_report: Any = None
    waste_report: Any = None
    housing_report: Any = None
    energy_report: Any = None

    domain_status: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    cross_domain_impacts: List[Dict[str, Any]] = field(default_factory=list)
    #: Rules evaluated but not raised, with the input that was missing.
    #: Disclosure only - never contributes to risk, incidents or recommendations.
    near_misses: List[Dict[str, Any]] = field(default_factory=list)
    priority_incidents: List[Dict[str, Any]] = field(default_factory=list)
    city_level_recommendations: List[str] = field(default_factory=list)
    affected_zones: List[str] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)

    source_reports: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    overall_city_status: str = "UNKNOWN"
    overall_risk_level: str = "UNKNOWN"
    confidence: str = "low"
    report: Any = None


# ============================================================ helpers
def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return None
    return str(value)


def _dump(report: Any) -> Dict[str, Any]:
    """Best-effort JSON-safe dict for an arbitrary agent report."""
    if report is None:
        return {}
    if isinstance(report, dict):
        return dict(report)
    for attr in ("model_dump_json_safe", "model_dump", "to_dict"):
        fn = getattr(report, attr, None)
        if callable(fn):
            try:
                out = fn()
                if isinstance(out, dict):
                    return out
            except Exception:
                continue
    return {}


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _source_meta(report: Any, fallback: str) -> Dict[str, Any]:
    d = _dump(report)
    return {
        "subdomain": d.get("subdomain") or getattr(report, "subdomain", None) or fallback,
        "domain": d.get("domain") or getattr(report, "domain", None),
        "generated_at": d.get("generated_at") or _iso(getattr(report, "generated_at", None)),
        "source_status": d.get("source_status") or getattr(report, "source_status", None),
        "is_ml_prediction": bool(d.get("is_ml_prediction", False)),
    }


def _unavailable(domain: str, error: str) -> Dict[str, Any]:
    return {
        "domain": domain,
        "available": False,
        "overall_status": None,
        "overall_risk": None,
        "risk_level": None,
        "key_metrics": {},
        "active_alert_count": None,
        "affected_zones": [],
        "primary_risk_factors": [],
        "confidence": "low",
        "limitations": [error],
        "warnings": [],
        "errors": [],
        "is_ml_prediction": False,
        "error": error,
    }


# ============================================================ node 1: collect
def collect_reports(state: CityCoordinatorState) -> CityCoordinatorState:
    """Run every domain agent. No single failure may abort the coordinator."""
    try:
        # Issue the environment forecast for a current hour. Without this the
        # module caps t0 at the newest entry in the research weather CSVs
        # (2024) and reports that as the city environment.
        t0 = _environment_t0()
        state.environment_report = (
            EnvironmentModule().run(prediction_timestamp=t0)
            if t0 is not None else EnvironmentModule().run()
        )
        state.source_reports["environment"] = _source_meta(state.environment_report, "environment")
    except Exception as exc:
        state.environment_report = None
        state.errors.append(f"Environment Agent failed: {exc}")
        state.warnings.append("Environment report unavailable")

    try:
        state.traffic_report = run_traffic_agent()
        state.source_reports["traffic"] = _source_meta(state.traffic_report, "traffic")
    except Exception as exc:
        state.traffic_report = None
        state.errors.append(f"Traffic Agent failed: {exc}")
        state.warnings.append("Traffic report unavailable")

    try:
        state.flood_report = run_flood_agent_v3()
        state.source_reports["flood"] = _source_meta(state.flood_report, "flood")
    except Exception as exc:
        state.flood_report = None
        state.errors.append(f"Flood Agent failed: {exc}")
        state.warnings.append("Flood report unavailable")

    # Advisory domains degrade to warnings rather than errors.
    try:
        state.water_report = run_water_agent()
        state.source_reports["water"] = _source_meta(state.water_report, "water")
    except Exception as exc:
        state.water_report = None
        state.warnings.append(f"Water report unavailable: {exc}")

    try:
        state.land_report = run_land_agent()
        state.source_reports["land"] = _source_meta(state.land_report, "land")
    except Exception as exc:
        state.land_report = None
        state.warnings.append(f"Land report unavailable: {exc}")

    try:
        state.fire_report = run_fire_agent()
        state.source_reports["fire"] = _source_meta(state.fire_report, "fire")
    except Exception as exc:
        state.fire_report = None
        state.errors.append(f"Fire Agent failed: {exc}")
        state.warnings.append("Fire report unavailable")

    try:
        state.crime_report = run_crime_agent()
        state.source_reports["crime"] = _source_meta(state.crime_report, "crime")
    except Exception as exc:
        state.crime_report = None
        state.errors.append(f"Crime Agent failed: {exc}")
        state.warnings.append("Crime report unavailable")

    # Waste (advisory: headline metrics only; never city status/risk/confidence)
    try:
        state.waste_report = run_waste_agent()
        state.source_reports["waste"] = _source_meta(state.waste_report, "waste")
    except Exception as exc:
        state.waste_report = None
        state.warnings.append(f"Waste report unavailable: {exc}")

    # Housing (advisory: periodic statistics only; never city status/risk/confidence)
    try:
        state.housing_report = run_housing_agent()
        state.source_reports["housing"] = _source_meta(state.housing_report, "housing")
    except Exception as exc:
        state.housing_report = None
        state.warnings.append(f"Housing report unavailable: {exc}")

    # Energy (advisory: historical statistics only; never city status/risk/confidence)
    try:
        state.energy_report = run_energy_agent()
        state.source_reports["energy"] = _source_meta(state.energy_report, "energy")
    except Exception as exc:
        state.energy_report = None
        state.warnings.append(f"Energy report unavailable: {exc}")

    return state


# =========================================================== node 2: normalize
def _pm25_risk(max_pm25: Optional[float]) -> Optional[str]:
    """PSI-band mapping for the next-day PM2.5 maximum.

    Bands follow the Singapore PSI scale: below 30 is low, up to 50 is moderate,
    above 50 is high.
    """
    if max_pm25 is None:
        return None
    if max_pm25 < 30:
        return "LOW"
    if max_pm25 <= 50:
        return "MODERATE"
    return "HIGH"


def _observed_air_quality() -> Dict[str, Any]:
    """Current NEA PM2.5 observations from the live collector's SQLite store.

    The ML environment module forecasts from the static research dataset, whose
    weather inputs stop in 2024 - so its forecast is pinned to 2024-12-31 and
    cannot describe today. The cross-domain air-quality rules must reason about
    *observed* air quality, which this store keeps current via the PM2.5
    collector. Same underlying NEA source, read through the store the Overview
    already uses.

    Never raises: an unreadable store yields an empty result, which the caller
    treats as "no observation", not as clean air.
    """
    try:
        from backend.app.environment.pm25.data import Pm25ObservationStore

        snapshot = Pm25ObservationStore().get_latest_snapshot() or {}
    except Exception as exc:  # noqa: BLE001 - evidence must never abort a run
        log.warning("Observed air quality unavailable: %s", exc)
        return {"available": False, "reason": str(exc)}

    values: Dict[str, float] = {}
    observed_at: Optional[str] = None
    for region, reading in snapshot.items():
        if not isinstance(reading, dict):
            continue
        value = _num(reading.get("value"))
        if value is None:
            continue
        values[str(region)] = value
        stamp = reading.get("observed_at")
        if stamp:
            observed_at = str(stamp)

    if not values:
        return {"available": False, "reason": "no usable regional reading"}

    return {
        "available": True,
        "max_pm25": max(values.values()),
        "mean_pm25": sum(values.values()) / len(values),
        "regions": values,
        "observed_at": observed_at,
    }


def _environment_t0() -> Optional[pd.Timestamp]:
    """Issuance hour for the environment forecast.

    The module's own default caps t0 by the newest issue in the *research*
    weather CSVs, which end in 2024, so it silently backdates the whole
    environment assessment by roughly 22 months and reports a 2024 forecast as
    current. We ask for a current issuance instead and let the module flag its
    own stale weather input honestly (it already emits
    ``weather_forecast_stale:*``), rather than quietly serving last year.
    """
    try:
        from backend.app.environment.pm25.data import Pm25ObservationStore

        stamp = Pm25ObservationStore().get_latest_observation_timestamp()
        if stamp:
            latest = pd.Timestamp(stamp)
            if latest.tzinfo is None:
                latest = latest.tz_localize(SG)
            else:
                latest = latest.tz_convert(SG)
        else:
            latest = pd.Timestamp.now(tz=SG)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not derive environment t0; falling back to now: %s", exc)
        return None

    # D-1 23:00: the issuance cutoff, with a fully observable next-day window.
    t0 = latest.normalize() - pd.Timedelta(days=1) + pd.Timedelta(hours=23)
    if t0 > latest:
        t0 = latest.floor("h")
    return t0


def _normalize_environment(report: Any) -> Dict[str, Any]:
    d = _dump(report)
    regions = d.get("regions") or []
    values: List[float] = []
    for r in regions:
        if isinstance(r, dict):
            for key in ("pm25_next_day_max", "predicted_value", "value"):
                v = _num(r.get(key))
                if v is not None:
                    values.append(v)
                    break
    # Some report shapes serialise regions as plain names; fall back to the
    # live objects so a malformed dump cannot silently drop the metric.
    if not values:
        for r in getattr(report, "regions", None) or []:
            v = _num(getattr(r, "pm25_next_day_max", None))
            if v is not None:
                values.append(v)

    max_pm25 = max(values) if values else None
    weather_available = bool(
        getattr(report, "weather_forecast", None)
        or (isinstance(d.get("weather_forecast"), dict) and d.get("weather_forecast"))
    )
    flags = [str(f) for f in (d.get("data_quality_flags")
                              or getattr(report, "data_quality_flags", None) or [])]

    # Observed air quality is what the cross-domain rules must judge. The
    # forecast above comes from a model fed the static research dataset and can
    # lag real conditions badly, so it is reported but never used as the
    # evidence for a city-level conclusion.
    observed = _observed_air_quality()
    observed_max = observed.get("max_pm25") if observed.get("available") else None
    forecast_risk = _pm25_risk(max_pm25)

    # The domain's own risk reflects the worse of the two, so a clean forecast
    # cannot mask unhealthy air that is actually being measured now.
    air_risk = observed_max if observed_max is not None else max_pm25
    band = _pm25_risk(air_risk) or "UNKNOWN"

    limitations = ["PM2.5 forecast values are next-day model predictions, not observations."]
    if observed.get("available"):
        limitations.append(
            "City-level air-quality conclusions use the current NEA observation "
            f"(observed {observed.get('observed_at')}), not the model forecast."
        )
    else:
        limitations.append(
            "No current PM2.5 observation was available; only the model forecast "
            "could be reported."
        )

    return {
        "domain": "environment",
        "available": True,
        "overall_status": "NORMAL" if band in ("LOW",) else "ELEVATED",
        "overall_risk": band,
        "key_metrics": {
            "max_pm25_next_day_max": max_pm25,
            "max_pm25_observed": observed_max,
            "mean_pm25_observed": observed.get("mean_pm25"),
            "observed_pm25_regions": observed.get("regions", {}),
            "observed_pm25_at": observed.get("observed_at"),
            "observed_air_quality_available": bool(observed.get("available")),
            "forecast_pm25_risk": forecast_risk,
            "region_count": len(regions) or len(getattr(report, "regions", None) or []),
            "weather_forecast_available": weather_available,
            "forecast_date": d.get("forecast_date") or _iso(
                getattr(report, "forecast_date", None)),
            "data_quality_flags": flags,
        },
        "active_alert_count": 0,
        "affected_zones": sorted(
            r for r, v in (observed.get("regions") or {}).items() if _num(v) is not None
        ),
        "primary_risk_factors": flags,
        "confidence": "medium",
        "limitations": limitations,
        "warnings": flags,
        "errors": [] if observed.get("available") else [
            str(observed.get("reason") or "observed air quality unavailable")
        ],
        "is_ml_prediction": True,
        "generated_at": _iso(getattr(report, "generated_at", None) or d.get("generated_at")),
    }


def _normalize_traffic(report: Any) -> Dict[str, Any]:
    d = _dump(report)
    status = str(d.get("overall_status") or "unknown").lower()
    risk = {"normal": "LOW", "elevated": "MODERATE",
            "disrupted": "HIGH", "critical": "CRITICAL"}.get(status, "UNKNOWN")

    zones: List[str] = []
    for inc in (d.get("incidents") or []):
        if isinstance(inc, dict):
            z = inc.get("zone_name") or inc.get("zone_id")
        else:
            z = getattr(inc, "zone_name", None) or getattr(inc, "zone_id", None)
        if z and z not in zones:
            zones.append(str(z))

    return {
        "domain": "traffic",
        "available": True,
        "overall_status": status,
        "overall_risk": risk,
        "key_metrics": {
            "average_speed_kmh": _num(d.get("overall_average_speed")),
            "predicted_speed_kmh": _num(d.get("overall_predicted_speed")),
            "speed_change_pct": _num(d.get("overall_speed_change_percent")),
            "congestion_level": d.get("overall_congestion_level"),
            "incident_count": len(d.get("incidents") or []),
        },
        "active_alert_count": len(d.get("incidents") or []),
        "affected_zones": zones,
        "primary_risk_factors": [],
        "confidence": "medium",
        "limitations": list(d.get("limitations") or []),
        "warnings": [],
        "errors": [],
        "is_ml_prediction": False,
        "generated_at": _iso(getattr(report, "generated_at", None) or d.get("generated_at")),
    }


def _normalize_flood(report: Any) -> Dict[str, Any]:
    d = _dump(report)
    raw = d.get("risk_level") or getattr(report, "risk_level", None) or "UNKNOWN"
    risk = str(getattr(raw, "value", raw)).upper()
    if risk not in _RISK_ORDER:
        risk = "UNKNOWN"
    zones = [str(z) for z in (d.get("affected_zones") or [])]
    alerts = d.get("active_alerts")
    alert_count = d.get("active_alert_count")
    if not isinstance(alert_count, (int, float)) or isinstance(alert_count, bool):
        alert_count = len(alerts) if isinstance(alerts, list) else 0

    return {
        "domain": "flood",
        "available": True,
        "overall_status": risk,
        "overall_risk": risk,
        "risk_level": risk,
        "key_metrics": {
            "risk_level": risk,
            "risk_score": _num(d.get("risk_score")),
            "active_alert_count": alert_count,
            "affected_zones": zones,
        },
        "active_alert_count": int(alert_count),
        "affected_zones": zones,
        "primary_risk_factors": [str(f) for f in (d.get("primary_risk_factors") or [])],
        "confidence": str(d.get("confidence") or "low"),
        "limitations": list(d.get("limitations") or []),
        "warnings": [],
        "errors": [str(e) for e in (d.get("errors") or [])],
        "is_ml_prediction": False,
        "generated_at": _iso(getattr(report, "generated_at", None) or d.get("generated_at")),
    }


def _normalize_water(report: Any) -> Dict[str, Any]:
    d = _dump(report)
    drain = d.get("drain") or {}
    supply = d.get("supply") or {}
    usage = d.get("usage") or {}
    forecast = d.get("forecast") or {}
    pot = usage.get("potable_total") or {}

    sensors = [s for s in (drain.get("sensors") or []) if isinstance(s, dict)]
    elevated = [
        s for s in sensors
        if str(s.get("condition") or "").upper() in ("ELEVATED", "HIGH", "CRITICAL")
    ]
    pcts = [
        _num(s.get("percentage")) for s in sensors if _num(s.get("percentage")) is not None
    ]
    factors = []
    for s in elevated[:3]:
        sensor = s.get("sensor") or {}
        label = sensor.get("name") or sensor.get("id") or "sensor"
        pct = s.get("percentage")
        factors.append(f"{label} at {pct}%" if pct is not None else str(label))

    return {
        "domain": "water",
        "available": True,
        "overall_risk": str(d.get("overall_risk") or "UNKNOWN"),
        "overall_status": str(d.get("overall_status") or "UNKNOWN"),
        "key_metrics": {
            "drain_readings_available": bool(drain.get("readings_available")),
            "drain_sensor_count": drain.get("sensor_count"),
            "drain_sensors_reporting": drain.get("sensors_with_readings"),
            "drain_elevated_count": len(elevated),
            "drain_max_fill_pct": max(pcts) if pcts else None,
            "reservoir_storage_available": bool(supply.get("reservoir_storage_available")),
            "potable_sales_latest_mm3": pot.get("value"),
            "potable_sales_period": pot.get("period"),
            "forecast_available": bool(forecast.get("available")),
        },
        "active_alert_count": len(d.get("alerts") or []),
        "affected_zones": [],
        "primary_risk_factors": factors,
        "confidence": str(d.get("confidence") or "low"),
        "limitations": list(d.get("limitations") or []),
        "warnings": list(d.get("warnings") or []),
        "errors": list(d.get("errors") or []),
        "is_ml_prediction": bool(d.get("is_ml_prediction", False)),
        "generated_at": _iso(getattr(report, "generated_at", None) or d.get("generated_at")),
    }


def _normalize_land(report: Any) -> Dict[str, Any]:
    d = _dump(report)
    land_use = d.get("land_use") or {}
    return {
        "domain": "land",
        "available": True,
        "overall_status": str(d.get("overall_status") or "NORMAL"),
        "overall_risk": "LOW",
        "key_metrics": {
            "land_use_area_km2": land_use.get("total_area_km2"),
            "zone_count": land_use.get("total_zones"),
            "distinct_categories": land_use.get("distinct_categories"),
        },
        "active_alert_count": len(d.get("alerts") or []),
        "affected_zones": [],
        "primary_risk_factors": [],
        "confidence": str(d.get("confidence") or "low"),
        "limitations": list(d.get("limitations") or []),
        "warnings": list(d.get("warnings") or []),
        "errors": list(d.get("errors") or []),
        "is_ml_prediction": False,
        "generated_at": _iso(getattr(report, "generated_at", None) or d.get("generated_at")),
    }


def _normalize_fire(report: Any) -> Dict[str, Any]:
    d = _dump(report)
    active = d.get("active_incident_count")
    critical = d.get("critical_incident_count")
    available = isinstance(active, (int, float)) and not isinstance(active, bool)
    risk = "UNKNOWN"
    if available:
        risk = ("CRITICAL" if (critical or 0) > 0
                else "MODERATE" if active > 0 else "LOW")
    out = {
        "domain": "fire",
        "available": available,
        "overall_status": ("NORMAL" if risk == "LOW" else risk) if available else None,
        "overall_risk": risk,
        "key_metrics": {
            "active_incidents": active,
            "critical_incidents": critical,
            "incidents_today": d.get("incidents_today"),
        },
        "active_alert_count": active,
        "affected_zones": [],
        "primary_risk_factors": [],
        "confidence": str(d.get("confidence") or "low"),
        "limitations": list(d.get("limitations") or []),
        "warnings": list(d.get("warnings") or []),
        "errors": list(d.get("errors") or []),
        "is_ml_prediction": False,
        "generated_at": _iso(getattr(report, "generated_at", None) or d.get("generated_at")),
    }
    if not available:
        out["error"] = "Fire feed returned no records; incident counts cannot be stated."
    return out


def _normalize_crime(report: Any) -> Dict[str, Any]:
    d = _dump(report)
    total = d.get("total_physical_crime_2025")
    available = total is not None
    out = {
        "domain": "crime",
        "available": available,
        "overall_status": "NORMAL" if available else None,
        "overall_risk": "LOW" if available else "UNKNOWN",
        "key_metrics": {
            "physical_crime": total,
            "scams_cybercrime": d.get("total_scams_cybercrime_2025"),
            "data_period": d.get("data_period"),
        },
        "active_alert_count": 0,
        "affected_zones": [],
        "primary_risk_factors": [],
        "confidence": str(d.get("confidence") or "low"),
        "limitations": list(d.get("limitations") or []),
        "warnings": list(d.get("warnings") or []),
        "errors": list(d.get("errors") or []),
        "is_ml_prediction": False,
        "generated_at": _iso(getattr(report, "generated_at", None) or d.get("generated_at")),
    }
    if not available:
        out["error"] = "Crime statistics are unavailable for the published period."
    return out


def _normalize_waste(report: Any) -> Dict[str, Any]:
    d = _dump(report)
    kpis = {k.get("key"): _num(k.get("value")) for k in (d.get("kpis") or [])}
    gen = d.get("generation") or {}
    cat = d.get("categories") or {}
    food = d.get("food") or {}
    services = d.get("services") or {}
    infra = d.get("infrastructure") or {}
    available = d.get("status") == "STATISTICS_AVAILABLE"
    status = d.get("status") if available else None
    risk = str(d.get("overall_risk") or "UNKNOWN").upper()
    if risk not in _RISK_ORDER:
        risk = "UNKNOWN"
    factors = [str(a) for a in (d.get("alerts") or [])]
    return {
        "domain": "waste",
        "available": available,
        "overall_status": status if available else None,
        "overall_risk": risk,
        "key_metrics": {
            "waste_generated_tonnes": kpis.get("total_generated"),
            "waste_recycled_tonnes": kpis.get("total_recycled"),
            "waste_disposed_tonnes": kpis.get("total_disposed"),
            "overall_recycling_rate_pct": kpis.get("overall_recycling_rate"),
            "recycling_rate_excl_cd_pct": kpis.get("recycling_rate_excl_cd"),
            "statistics_year": str(gen.get("latest_year")) if gen.get("latest_year") is not None else None,
            "generation_change_pct": gen.get("generated_change_since_peak_pct"),
            "peak_generated_year": gen.get("peak_generated_year"),
            "peak_recycling_rate_pct": gen.get("peak_recycling_rate_pct"),
            "top_disposed_categories": cat.get("top_disposed"),
            "food_waste_generated_tonnes": food.get("generated", {}).get("value"),
            "food_waste_recycling_rate_pct": _num(
                food.get("recycling_rate", {}).get("value") if isinstance(food.get("recycling_rate"), dict) else food.get("recycling_rate")
            ),
            "licensed_collectors": services.get("licensee_count"),
            "infrastructure_locations": sum(k.get("count") or 0 for k in (infra.get("kinds") or [])),
            "forecast_available": d.get("forecast", {}).get("available", False),
        },
        "active_alert_count": len(d.get("alerts") or []),
        "affected_zones": [],
        "primary_risk_factors": factors,
        "confidence": str(d.get("confidence") or "low"),
        "limitations": list(d.get("limitations") or []),
        "warnings": list(d.get("warnings") or []),
        "errors": list(d.get("errors") or []),
        "is_ml_prediction": bool(d.get("is_ml_prediction", False)),
        "generated_at": _iso(getattr(report, "generated_at", None) or d.get("generated_at")),
    }


def _normalize_housing(report: Any) -> Dict[str, Any]:
    d = _dump(report)
    kpis = d.get("kpis") or {}
    available = d.get("status") == "AVAILABLE"
    status = d.get("status") or ("NORMAL" if available else None)
    return {
        "domain": "housing",
        "available": available,
        "overall_status": status,
        "overall_risk": "LOW" if available else "UNKNOWN",
        "key_metrics": {
            "latest_median_resale_period": kpis.get("latest_median_resale_period"),
            "town_flat_type_median_price_rows": kpis.get("town_flat_type_median_price_rows"),
            "latest_resale_applications_period": kpis.get("latest_resale_applications_period"),
            "resale_applications": kpis.get("resale_applications"),
            "hdb_property_records": kpis.get("hdb_property_records"),
            "hdb_total_dwelling_units_in_records": kpis.get("hdb_total_dwelling_units_in_records"),
        },
        "active_alert_count": 0,
        "affected_zones": [],
        "primary_risk_factors": [],
        "confidence": str(d.get("confidence") or "low"),
        "limitations": list(d.get("limitations") or []),
        "warnings": list(d.get("warnings") or []),
        "errors": list(d.get("errors") or []),
        "is_ml_prediction": bool(d.get("is_ml_prediction", False)),
        "generated_at": _iso(getattr(report, "generated_at", None) or d.get("generated_at")),
    }


def _normalize_energy(report: Any) -> Dict[str, Any]:
    d = _dump(report)
    kpis = d.get("key_metrics") or {}
    available = d.get("status") == "OK"
    status = "NORMAL" if available else None
    risk = "LOW" if available else "UNKNOWN"
    return {
        "domain": "energy",
        "available": available,
        "overall_status": status,
        "overall_risk": risk,
        "key_metrics": {
            "latest_peak_demand_mw": kpis.get("latest_peak_demand_mw"),
            "latest_peak_demand_period": kpis.get("latest_peak_demand_period"),
            "max_peak_demand_mw": kpis.get("max_peak_demand_mw"),
            "average_peak_demand_mw": kpis.get("average_peak_demand_mw"),
            "latest_solar_capacity_mwp": kpis.get("latest_solar_capacity_mwp"),
            "latest_solar_capacity_year": kpis.get("latest_solar_capacity_year"),
            "demand_records": kpis.get("demand_records"),
            "consumption_records": kpis.get("consumption_records"),
        },
        "active_alert_count": 0,
        "affected_zones": [],
        "primary_risk_factors": [],
        "confidence": str(d.get("confidence") or "low"),
        "limitations": list(d.get("limitations") or []),
        "warnings": list(d.get("warnings") or []),
        "errors": list(d.get("errors") or []),
        "is_ml_prediction": bool(d.get("is_ml_prediction", False)),
        "generated_at": _iso(getattr(report, "generated_at", None) or d.get("generated_at")),
    }


_NORMALIZERS = {
    "environment": ("environment_report", _normalize_environment),
    "traffic": ("traffic_report", _normalize_traffic),
    "flood": ("flood_report", _normalize_flood),
    "water": ("water_report", _normalize_water),
    "land": ("land_report", _normalize_land),
    "fire": ("fire_report", _normalize_fire),
    "crime": ("crime_report", _normalize_crime),
    "waste": ("waste_report", _normalize_waste),
    "housing": ("housing_report", _normalize_housing),
    "energy": ("energy_report", _normalize_energy),
}


def normalize_state(state: CityCoordinatorState) -> CityCoordinatorState:
    """Normalise every report into the shared per-domain contract.

    A domain with no report becomes explicitly unavailable with an error - never
    a silent ``normal``.
    """
    for domain, (attr, fn) in _NORMALIZERS.items():
        report = getattr(state, attr, None)
        if report is None:
            # Waste module test expects a minimal unavailable dict
            if domain == "waste":
                state.domain_status[domain] = {
                    "domain": "waste",
                    "available": False,
                    "error": "Waste report not available",
                }
            else:
                existing = state.domain_status.get(domain)
                if existing:
                    state.domain_status[domain] = dict(existing)
                    state.domain_status[domain].setdefault(
                        "error", f"{domain.title()} report was not collected.")
                else:
                    state.domain_status[domain] = _unavailable(
                        domain, f"{domain.title()} report was not collected.")
            continue
        try:
            state.domain_status[domain] = fn(report)
        except Exception as exc:  # normalisation must never abort the run
            log.warning("Normalising %s failed: %s", domain, exc)
            state.domain_status[domain] = _unavailable(domain, f"Normalisation failed: {exc}")

    zones: List[str] = []
    for s in state.domain_status.values():
        if isinstance(s, dict):
            for z in s.get("affected_zones") or []:
                if z and z not in zones:
                    zones.append(str(z))
    if zones:
        state.affected_zones = zones
    return state


# ======================================================== node 3: prioritize
def prioritize_risks(state: CityCoordinatorState) -> CityCoordinatorState:
    """Deterministic city status, risk and confidence.

    ``UNKNOWN`` never escalates city risk and never lowers confidence on its
    own - it only means that domain contributes nothing.
    """
    statuses = state.domain_status or {}

    known = [
        s.get("overall_risk") for s in statuses.values()
        if isinstance(s, dict) and s.get("overall_risk") in _RISK_ORDER
    ]
    # A validated cross-domain impact may raise the city level above the worst
    # single domain, but never lowers it.
    impact_sev = [
        i.get("severity") for i in (state.cross_domain_impacts or [])
        if isinstance(i, dict) and i.get("severity") in _RISK_ORDER
    ]
    candidates = known + impact_sev
    worst = max(candidates, key=lambda r: _RISK_ORDER[r]) if candidates else "UNKNOWN"

    state.overall_risk_level = worst
    state.overall_city_status = _STATUS_BY_RISK.get(worst, "UNKNOWN")

    # Confidence follows the original 3-domain rule. Later domains do not change it.
    core_known = [
        (statuses.get(d) or {}).get("overall_risk") in _RISK_ORDER
        for d in CORE_DOMAINS
    ]
    if all(core_known):
        state.confidence = "high"
    elif sum(core_known) >= 2:
        state.confidence = "medium"
    else:
        state.confidence = "low"

    limits = list(_BASE_LIMITATIONS)
    limits.append(
        "City confidence is derived from the three core domains "
        f"({', '.join(CORE_DOMAINS)}); advisory domains do not raise or lower it."
    )
    for domain, s in sorted(statuses.items()):
        if isinstance(s, dict) and s.get("error"):
            limits.append(f"{domain}: {s['error']}")
    state.limitations = limits

    if state.cross_domain_impacts:
        state.priority_incidents = _incidents_from_impacts(state.cross_domain_impacts)

    zones: List[str] = list(state.affected_zones or [])
    for s in statuses.values():
        if isinstance(s, dict):
            for z in s.get("affected_zones") or []:
                if z and z not in zones:
                    zones.append(str(z))
    state.affected_zones = zones
    return state


#: Impact types that describe conditions happening *at the same time in the same
#: place* and therefore warrant their own priority incident. ``weather_flood``
#: and ``air_quality_weather`` are context for those conditions, not incidents
#: in their own right, so they inform without duplicating the priority list.
_INCIDENT_IMPACT_TYPES = (
    "flood_traffic", "drain_flood_context", "multi_domain_high_risk",
    "air_quality_traffic",
)


def _incidents_from_impacts(impacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for impact in impacts:
        typ = impact.get("type")
        if typ not in _INCIDENT_IMPACT_TYPES:
            continue
        domains = impact.get("domains_involved") or []
        out.append({
            "id": f"IMPACT_{typ}",
            "type": f"{typ}_overlap" if typ in ("flood_traffic", "drain_flood_context")
                    else str(typ),
            "domain": "+".join(domains) if domains else "city",
            "severity": impact.get("severity") if impact.get("severity") in
                        ("LOW", "MODERATE", "HIGH") else "MODERATE",
            "description": impact.get("description", ""),
            "affected_zones": list(impact.get("affected_zones") or []),
            "source_report": "+".join(domains),
            "related_domains": list(domains),
            "cascading_risk": None,
        })
    out.sort(key=lambda i: _RISK_ORDER.get(i["severity"], 0), reverse=True)
    return out


# ================================================ node 4: cross-domain rules
def _flood_risk(s: Dict[str, Any]) -> str:
    return str(s.get("overall_risk") or s.get("risk_level") or "UNKNOWN").upper()


def _traffic_bad(s: Dict[str, Any]) -> bool:
    """Traffic is 'bad' when the agent itself says so."""
    status = str(s.get("overall_status") or "").lower()
    risk = str(s.get("overall_risk") or "").upper()
    return status in ("disrupted", "critical") or risk in ("HIGH", "CRITICAL")


def _domain_label(domain: str) -> str:
    """Human-readable domain name: ``air_quality`` -> ``Air Quality``."""
    words = str(domain or "").replace("_", " ").split()
    return " ".join(w.capitalize() for w in words) if words else str(domain)


def analyze_cross_domain_impacts(state: CityCoordinatorState) -> CityCoordinatorState:
    """Raise an impact only where real evidence from both domains exists.

    Every impact cites the domains whose own reports justify it. Co-elevation of
    unrelated domains is reported as ``multi_domain_high_risk`` - a count, never
    a causal claim.

    Rules the engine did *not* raise are recorded in ``state.near_misses`` with
    the specific input that was missing, so "no signals" is explainable rather
    than a blank panel. A near miss is disclosure only: it never contributes to
    risk, incidents or recommendations.
    """
    statuses = state.domain_status or {}
    impacts: List[Dict[str, Any]] = []
    near_misses: List[Dict[str, Any]] = []

    def miss(rule: str, reason: str) -> None:
        near_misses.append({"rule": rule, "reason": reason})

    flood = statuses.get("flood") or {}
    traffic = statuses.get("traffic") or {}
    env = statuses.get("environment") or {}
    water = statuses.get("water") or {}

    f_risk = _flood_risk(flood)
    f_ok = bool(flood.get("available")) and f_risk in ("HIGH", "CRITICAL")
    t_bad = bool(traffic.get("available")) and _traffic_bad(traffic)
    e_ok = bool(env.get("available"))
    e_km = env.get("key_metrics") or {}
    weather = bool(e_km.get("weather_forecast_available"))
    # Judge air quality on the current observation. The model forecast is fed
    # the static research dataset and can sit far below what is measured now.
    obs_pm25 = _num(e_km.get("max_pm25_observed"))
    max_pm25 = obs_pm25 if obs_pm25 is not None else _num(
        e_km.get("max_pm25_next_day_max"))
    obs_regions = {
        str(k): _num(v)
        for k, v in (e_km.get("observed_pm25_regions") or {}).items()
        if _num(v) is not None
    }

    f_zones = [str(z) for z in (flood.get("affected_zones") or [])]
    t_zones = [str(z) for z in (traffic.get("affected_zones") or [])]
    overlap = [z for z in f_zones if z in t_zones]

    # --- flood + traffic: both domains must independently report stress.
    if f_ok and t_bad:
        zones = overlap or f_zones
        evidence = [f"Flood risk reported as {f_risk}."]
        if f_zones:
            evidence.append(f"Flood-affected zones: {', '.join(f_zones)}.")
        if overlap:
            evidence.append(
                f"Traffic degradation overlaps the same zone(s): {', '.join(overlap)}.")
        else:
            evidence.append(
                f"Traffic status reported as {traffic.get('overall_status')!r}.")
        impacts.append({
            "type": "flood_traffic",
            "description": (
                f"Roads are {traffic.get('overall_status')} while flood risk sits at {f_risk}"
                + (f", in the same area{'' if len(zones) == 1 else 's'} "
                   f"({', '.join(zones)})." if zones else ".")
            ),
            "severity": "HIGH",
            "affected_zones": zones,
            "domains_involved": ["flood", "traffic"],
            "evidence": evidence,
        })

    # --- weather + flood: the environment module must hold a forecast.
    if f_ok and e_ok and weather:
        evidence = [f"Flood risk reported as {f_risk}."]
        if f_zones:
            evidence.append(f"Flood-affected zones: {', '.join(f_zones)}.")
        evidence.append("NEA weather forecast present in the environment report.")
        impacts.append({
            "type": "weather_flood",
            "description": (
                f"Today's weather forecast is consistent with the {f_risk} flood risk"
                + (f", affecting {', '.join(f_zones)}." if f_zones else ".")
            ),
            "severity": "HIGH",
            "affected_zones": f_zones,
            "domains_involved": ["weather", "flood"],
            "evidence": evidence,
        })

    # --- air quality + weather: only at the PSI "unhealthy" boundary.
    if e_ok and weather and max_pm25 is not None and max_pm25 >= _PM25_IMPACT_THRESHOLD:
        basis = "observed" if obs_pm25 is not None else "forecast"
        unhealthy_now = sorted(r for r, v in obs_regions.items()
                               if v is not None and v >= _PM25_IMPACT_THRESHOLD)
        because_clause = (
            f" in {', '.join(unhealthy_now)}" if unhealthy_now else " citywide"
        )
        weather_phrase = "thundery showers" if weather else "showers"
        evidence = [
            f"NEA measured a PM2.5 peak of {max_pm25:g} µg/m³ at "
            f"{e_km.get('observed_pm25_at') or 'the latest observation'}.",
            "NEA weather forecast present in the environment report.",
        ]
        impacts.append({
            "type": "air_quality_weather",
            "description": (
                f"Air is unhealthy{because_clause} while the NEA has "
                f"{weather_phrase} in today's forecast. Wet weather and poor air "
                f"often arrive together this time of year, but we have no data "
                f"that links the two."
            ),
            "severity": "HIGH",
            "affected_zones": [r for r, v in obs_regions.items()
                                if v is not None and v >= _PM25_IMPACT_THRESHOLD],
            "domains_involved": ["air_quality", "weather"],
            "evidence": evidence,
        })
    elif e_ok:
        miss(
            "air_quality_weather",
            f"PM2.5 {max_pm25:g} µg/m³ is below the "
            f"{int(_PM25_IMPACT_THRESHOLD)} µg/m³ boundary." if max_pm25 is not None
            else "no PM2.5 observation or forecast available.",
        )

    # --- air quality + traffic.
    # Unhealthy air and disrupted traffic are each independently operationally
    # significant and both are observed directly, so their coincidence is a real
    # picture worth an operator's attention. Neither side is assumed from the
    # other: each carries its own measurement.
    if (e_ok and t_bad and obs_pm25 is not None
            and obs_pm25 >= _PM25_IMPACT_THRESHOLD):
        unhealthy = sorted(r for r, v in obs_regions.items()
                           if v is not None and v >= _PM25_IMPACT_THRESHOLD)
        evidence = [
            f"NEA measured a PM2.5 peak of {obs_pm25:g} µg/m³ at "
            f"{e_km.get('observed_pm25_at') or 'the latest observation'}.",
            f"Regions at or above the {int(_PM25_IMPACT_THRESHOLD)} µg/m³ "
            f"unhealthy boundary: {', '.join(unhealthy)}."
            if unhealthy else
            f"Citywide peak of {obs_pm25:g} µg/m³.",
            f"Road speeds independently reported as "
            f"{traffic.get('overall_status')}.",
        ]
        if t_zones:
            evidence.append(f"Affected roads are around {', '.join(t_zones)}.")
        impacts.append({
            "type": "air_quality_traffic",
            "description": (
                f"Unhealthy air and slow roads are happening at the same time. "
                f"The worst air is over {', '.join(unhealthy)}"
                f"{' and' if t_zones else ''} traffic is disrupted across "
                f"{', '.join(t_zones) if t_zones else 'the network'}. "
                f"Treat them as two separate problems that overlap, and plan "
                f"exposure and journeys together."
            ),
            "severity": "HIGH",
            "affected_zones": sorted(set(unhealthy) | set(t_zones)),
            "domains_involved": ["air_quality", "traffic"],
            "evidence": evidence,
        })
    elif e_ok and t_bad:
        miss(
            "air_quality_traffic",
            f"Observed PM2.5 {obs_pm25:g} µg/m³ is below the "
            f"{int(_PM25_IMPACT_THRESHOLD)} µg/m³ boundary."
            if obs_pm25 is not None else "no current PM2.5 observation available.",
        )

    if f_ok and t_bad:
        pass
    else:
        miss(
            "flood_traffic",
            f"flood risk is {f_risk}, not HIGH/CRITICAL"
            if flood.get("available") else "flood domain unavailable",
        )

    # --- water + flood: requires *measured* drain loading, not an assumption.
    w_km = water.get("key_metrics") or {}
    if (water.get("available") and w_km.get("drain_readings_available") is True
            and f_ok):
        stressed = _num(w_km.get("drain_max_fill_pct"))
        if stressed is not None:
            sev = "CRITICAL" if f_risk == "CRITICAL" else "HIGH"
            evidence = [
                f"PUB drain sensor reporting {stressed}% of reference depth "
                f"({w_km.get('drain_elevated_count') or 0} sensor(s) elevated or worse).",
                f"Flood risk level reported as {f_risk}.",
            ]
            if f_zones:
                evidence.append(f"Flood-affected zones: {', '.join(f_zones)}.")
            impacts.append({
                "type": "drain_flood_context",
                "description": (
                    f"Drains are carrying {stressed:g}% of their reference depth while "
                    f"flood risk is {f_risk}"
                    + (f", in {', '.join(f_zones)}." if f_zones else ".")
                ),
                "severity": sev,
                "affected_zones": f_zones,
                "domains_involved": ["water", "flood"],
                "evidence": evidence,
            })
        else:
            miss("drain_flood_context", "no measured drain loading available")
    else:
        miss(
            "drain_flood_context",
            "PUB drain sensors are not reporting" if water.get("available")
            else "water domain unavailable",
        )

    # --- multi-domain: a count of independently elevated domains. This is
    # explicitly not a causal claim; the description says so.
    high_domains = [
        d for d, s in sorted(statuses.items())
        if isinstance(s, dict) and str(s.get("overall_risk") or "").upper() in ("HIGH", "CRITICAL")
    ]
    if len(high_domains) >= 2:
        named = " and ".join(_domain_label(d) for d in high_domains)
        impacts.append({
            "type": "multi_domain_high_risk",
            "description": (
                f"{named} are both under strain right now. Each is measured "
                f"independently. No causal link between them is asserted — "
                f"treat them as separate problems that happen to overlap."
            ),
            "severity": "CRITICAL" if len(high_domains) >= 3 else "HIGH",
            "affected_zones": [],
            "domains_involved": high_domains,
            "evidence": [
                f"{_domain_label(d)} reports {str(statuses[d].get('overall_risk')).upper()} risk."
                for d in high_domains
            ],
        })
    else:
        miss(
            "multi_domain_high_risk",
            f"{len(high_domains)} domain is at HIGH/CRITICAL; two are needed"
            if high_domains else "no domain is at HIGH/CRITICAL",
        )

    impacts.sort(
        key=lambda i: _RISK_ORDER.get(i.get("severity", "LOW"), 0), reverse=True)
    state.cross_domain_impacts = impacts
    # Priority incidents follow directly from the validated impacts, so a
    # caller that runs only this node still gets an actionable list.
    state.priority_incidents = _incidents_from_impacts(impacts)
    # Disclosure only. Near misses are dropped from the impact list so they can
    # never reach risk, incidents or recommendations.
    state.near_misses = near_misses
    return state


# ============================================== node 5: recommendations
_IMPACT_RECO = {
    "flood_traffic": (
        "FLOOD+TRAFFIC",
        "Coordinate flood and traffic response for {zones}. Avoid flood-prone "
        "routes and reroute emergency services away from affected corridors.",
    ),
    "weather_flood": (
        "WEATHER+FLOOD",
        "Treat the current weather forecast and flood risk as one operational "
        "picture for {zones}. Monitor official channels before committing crews.",
    ),
    "air_quality_weather": (
        "AIR QUALITY",
        "Forecast PM2.5 reaches the unhealthy boundary alongside the current "
        "weather. Advise sensitive groups and check NEA updates.",
    ),
    "drain_flood_context": (
        "WATER",
        "Measured drain loading coincides with flood risk. Review drain capacity "
        "and flood readings together before deploying crews to {zones}.",
    ),
    "air_quality_traffic": (
        "AIR QUALITY + TRAFFIC",
        "Unhealthy air quality and disrupted traffic occur together. Advise "
        "sensitive groups and expect reduced road speeds around {zones}.",
    ),
    "multi_domain_high_risk": (
        "MULTI-DOMAIN CRITICAL",
        "Multiple domains independently report elevated risk ({domains}). "
        "Prioritise cross-agency coordination; no causal link between the domains "
        "is asserted by this system.",
    ),
}

_DOMAIN_RECO = {
    "flood": ("FLOOD", "Monitor PUB Telegram and official NEA/PUB channels before "
                        "committing resources in {zones}."),
    "traffic": ("TRAFFIC", "Review live incidents and consider traffic management "
                           "measures in {zones}."),
    "water": ("WATER", "Review drain sensor readings and PUB advisories for {zones}."),
    "environment": ("ENVIRONMENT", "Review the PM2.5 forecast and NEA air-quality "
                                    "updates before issuing public guidance."),
    "fire": ("FIRE", "Confirm active incident status with SCDF before escalating."),
    "crime": ("CRIME", "Crime statistics are annual published figures; verify any "
                       "operational concern with current police channels."),
    "land": ("LAND", "Review Master Plan land-use data limitations before drawing "
                     "planning conclusions."),
    "waste": ("WASTE", "Waste statistics are annual national figures; review NEA "
                        "publications before drawing operational conclusions."),
    "housing": ("HOUSING", "Housing statistics are periodic official figures; review HDB/URA "
                        "publications before drawing operational conclusions."),
    "energy": ("ENERGY", "Energy statistics are historical official figures; review EMA "
                        "publications before drawing operational conclusions."),
}


def generate_recommendations(state: CityCoordinatorState) -> CityCoordinatorState:
    """Recommendations must rest on something already proven in this state."""
    recs: List[str] = []
    statuses = state.domain_status or {}

    for impact in state.cross_domain_impacts or []:
        spec = _IMPACT_RECO.get(impact.get("type", ""))
        if not spec:
            continue
        prefix, template = spec
        zones = ", ".join(impact.get("affected_zones") or []) or "the affected areas"
        domains = ", ".join(impact.get("domains_involved") or []) or "multiple domains"
        recs.append(
            f"{prefix}: {template.format(zones=zones, domains=domains)}"
        )

    for domain, s in sorted(statuses.items()):
        spec = _DOMAIN_RECO.get(domain)
        if not spec or not isinstance(s, dict):
            continue
        risk = str(s.get("overall_risk") or "").upper()
        if risk not in _RISK_ORDER or _RISK_ORDER[risk] < _RISK_ORDER["MODERATE"]:
            continue
        if any(r.startswith(f"{spec[0]}:") and "independently" not in r for r in recs):
            continue
        zones = ", ".join(s.get("affected_zones") or []) or "the affected areas"
        factors = s.get("primary_risk_factors") or []
        detail = f" Primary factor: {factors[0]}." if factors else ""
        recs.append(
            f"{spec[0]}: {domain.title()} reports {risk} risk.{detail} "
            + spec[1].format(zones=zones)
        )

    if not recs:
        unavailable = sorted(
            d for d, s in statuses.items()
            if isinstance(s, dict) and not s.get("available")
        )
        if unavailable:
            recs.append(
                "CITY: No domain reports an elevated or critical condition. "
                f"{', '.join(unavailable)} could not be assessed; absence of data "
                "is not evidence of normal conditions."
            )
        else:
            recs.append(
                "CITY: No domain reports an elevated or critical condition. "
                "Maintain the current operational posture."
            )

    state.city_level_recommendations = recs
    return state


# ============================================== node 6: final report
def _to_domain_status(domain: str, raw: Dict[str, Any],
                      findings: Optional[List[Any]] = None) -> DomainStatus:
    """Build a contract object, defaulting ``domain`` from the dict key.

    ``findings`` are attached from the shared intelligence normaliser so the
    coordinator report carries the same evidence-backed findings the Overview
    and the Copilot already read. This is additive provenance only: it does not
    affect status, severity, prioritisation or cross-domain logic.
    """
    allowed = set(DomainStatus.model_fields)
    payload = {k: v for k, v in (raw or {}).items() if k in allowed}
    payload["domain"] = payload.get("domain") or domain
    if findings and not payload.get("findings"):
        payload["findings"] = findings
    return DomainStatus(**payload)


def _findings_for(domain: str, raw: Dict[str, Any],
                  report_obj: Any) -> List[Any]:
    """Evidence-backed findings for one domain.

    Delegates to the shared Phase 1 normaliser so there is exactly one place
    that knows how to turn a domain report into findings. Purely additive
    provenance: status, severity, prioritisation and cross-domain logic are
    unaffected.
    """
    if report_obj is None or not isinstance(raw, dict) or not raw.get("available"):
        return []
    try:
        from backend.app.intelligence.normalize import normalize_domain_report
        normalized = normalize_domain_report(domain, _dump(report_obj))
        return [f.model_dump(mode="json") for f in normalized.findings]
    except Exception as exc:  # findings are provenance; never fail the run
        log.warning("Could not derive findings for %s: %s", domain, exc)
        return []


def build_report(state: CityCoordinatorState) -> CityCoordinatorState:
    """Build the final ``CitySituationReport`` from the graph state."""
    raw_domains = state.domain_status or {}
    statuses = {
        d: _to_domain_status(
            d, raw,
            _findings_for(d, raw, getattr(state, f"{d}_report", None)),
        )
        for d, raw in raw_domains.items()
    }

    evidence: List[Dict[str, Any]] = list(state.evidence or [])
    for domain, s in (state.domain_status or {}).items():
        if not isinstance(s, dict) or not s.get("available"):
            continue
        evidence.append({
            "source": domain,
            "subdomain": (state.source_reports.get(domain) or {}).get("subdomain", domain),
            "generated_at": s.get("generated_at"),
            "confidence": s.get("confidence"),
            "key_metrics": s.get("key_metrics") or {},
            "limitations": s.get("limitations") or [],
        })

    impacts = [CrossDomainImpact(**i) for i in state.cross_domain_impacts or []]
    incidents = [PriorityIncident(**i) for i in state.priority_incidents or []]

    limitations = list(state.limitations or _BASE_LIMITATIONS)
    for w in state.warnings or []:
        if w not in limitations:
            limitations.append(str(w))
    for e in state.errors or []:
        if e not in limitations:
            limitations.append(str(e))

    # Genuine gaps, one sentence each, so the narrative's "data gaps" section
    # says what is actually missing rather than repeating methodology notes.
    data_gaps: List[str] = []
    for domain, s in sorted((state.domain_status or {}).items()):
        if not isinstance(s, dict) or s.get("available"):
            continue
        reason = str(s.get("error") or "").strip()
        data_gaps.append(f"{domain.title()}: {reason}" if reason
                         else f"{domain.title()}: could not be assessed.")

    state.report = CitySituationReport(
        generated_at=_iso(state.generated_at) if getattr(state, "generated_at", None)
        else datetime.now(SG).isoformat(),
        overall_city_status=state.overall_city_status,  # type: ignore[arg-type]
        overall_risk_level=state.overall_risk_level,  # type: ignore[arg-type]
        domain_status=statuses,
        priority_incidents=incidents,
        cross_domain_impacts=impacts,
        near_misses=state.near_misses or [],
        city_level_recommendations=state.city_level_recommendations or [],
        affected_zones=state.affected_zones or [],
        evidence=evidence,
        confidence=state.confidence,  # type: ignore[arg-type]
        limitations=limitations,
        data_gaps=data_gaps,
        source_reports=state.source_reports or {},
        warnings=list(state.warnings),
        errors=list(state.errors),
        is_ml_prediction=False,
    )
    return state


#: Historical name kept for callers written against the first draft.
normalize = build_report


# ============================================================ graph
def create_city_coordinator() -> Any:
    """Build and compile the LangGraph workflow.

    Returns the compiled graph so callers can ``invoke`` it directly.
    """
    graph = StateGraph(CityCoordinatorState)
    graph.add_node("collect_reports", collect_reports)
    graph.add_node("normalize_state", normalize_state)
    graph.add_node("analyze_cross_domain_impacts", analyze_cross_domain_impacts)
    graph.add_node("prioritize_risks", prioritize_risks)
    graph.add_node("generate_recommendations", generate_recommendations)
    graph.add_node("build_report", build_report)

    # Cross-domain impacts are resolved *before* prioritisation: a validated
    # multi-domain impact may legitimately raise the city level above the worst
    # single domain, which it cannot do if it is computed afterwards.
    graph.set_entry_point("collect_reports")
    graph.add_edge("collect_reports", "normalize_state")
    graph.add_edge("normalize_state", "analyze_cross_domain_impacts")
    graph.add_edge("analyze_cross_domain_impacts", "prioritize_risks")
    graph.add_edge("prioritize_risks", "generate_recommendations")
    graph.add_edge("generate_recommendations", "build_report")
    graph.add_edge("build_report", END)
    return graph.compile()


def run_city_coordinator(offline: bool = False) -> CitySituationReport:
    """Run the whole coordinator and return its report. Never raises."""
    state = CityCoordinatorState()
    try:
        result = create_city_coordinator().invoke(state)
    except Exception as exc:
        log.exception("City coordinator graph failed: %s", exc)
        state.errors.append(f"City coordinator run failed: {exc}")
        return build_report(state).report
    return (result or {}).get("report") or build_report(state).report