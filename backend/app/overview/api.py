"""UrbanOS Overview API endpoints - direct service aggregation (no HTTP loopback)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Path, Query, status, Request
from pydantic import BaseModel, Field

from backend.app.ai.copilot import (
    MAX_HISTORY_CHARS, MAX_HISTORY_TURNS, MAX_QUESTION_CHARS,
    build_copilot_context, grounded_fallback,
)
from backend.app.ai.narrative import (
    build_narrative_input, deterministic_summary,
    deterministic_summary_from_domains,
)
from backend.app.ai.service import get_ai_service, UrbanOSAIService
from backend.app.coordinator.access import city_report_cached
from backend.app.intelligence.contracts import DomainStatus
from backend.app.intelligence.normalize import (
    DOMAIN_NAMES, DOMAIN_ROUTES, build_kpi, determine_status, normalize_domain_report,
)

log = logging.getLogger(__name__)

# Singapore timezone offset (UTC+8)
SG_OFFSET = timezone(timedelta(hours=8))

router = APIRouter(prefix="/api/overview", tags=["overview"])

# Keys under which expensive per-request results are memoised. The dict holding
# them is created fresh by each route handler and discarded when the response is
# built, so one caller can never see another's data.
#: A full flood assessment costs several live API calls and is needed twice.
_FLOOD_ASSESSMENT_KEY = "flood_assessment"
#: The crime report costs four data.gov.sg dataset fetches and is needed twice.
_CRIME_REPORT_KEY = "crime_report"


# ============================================================
# Response Models (matching frontend expectations)
# ============================================================

class ModuleKPI(BaseModel):
    label: str
    value: Any
    unit: str


class ModuleSummary(BaseModel):
    id: str
    name: str
    status: str  # "normal" | "elevated" | "critical" | "unavailable"
    kpi: Optional[ModuleKPI] = None
    updated_at: Optional[str] = None
    detail_route: str


class AlertItem(BaseModel):
    domain: str
    severity: str
    title: str
    description: str
    timestamp: str
    affected_zones: List[str] = []


class CityOverviewResponse(BaseModel):
    generated_at: str
    modules: List[ModuleSummary]
    alerts: List[AlertItem]
    ai_brief: Optional[str] = None
    #: Normalised per-domain intelligence. The single source consumed by the
    #: coordinator, the KPI insight panels and the Copilot.
    domain_status: Dict[str, DomainStatus] = {}
    #: True only when ``ai_brief`` is a coordinator-backed city assessment.
    #: False means the coordinator had not finished when this response was
    #: built, so the brief is per-domain evidence that claims no city status.
    #: The dashboard reads this to decide whether to reconcile, rather than
    #: guessing from the brief's wording.
    city_assessment_ready: bool = False


class CityNarrativeResponse(BaseModel):
    """Just the city assessment, so reconciliation does not re-run every domain.

    The full Overview endpoint re-runs all ten domain agents, which costs
    several live API calls. Fetching it a second time purely to pick up a
    narrative the coordinator finished after the first call answered would be
    wasteful, so this endpoint reads only the cached coordinator report and the
    cached narrative.
    """

    ai_brief: Optional[str] = None
    city_assessment_ready: bool = False
    #: Generation time of the coordinator report behind this narrative, so a
    #: caller can tell whether it is describing the same assessment it holds.
    report_generated_at: Optional[str] = None


class ModuleDetailResponse(BaseModel):
    module_id: str
    module_name: str
    status: str
    kpi: Optional[ModuleKPI] = None
    updated_at: Optional[str] = None
    summary: str
    alerts: List[AlertItem] = []
    cross_domain: List[str] = []
    detail_route: str


class ChatTurn(BaseModel):
    role: str = "user"
    text: str = ""


class ChatRequest(BaseModel):
    message: str
    module_id: Optional[str] = None
    #: Optional prior turns. Bounded server-side; never used as evidence.
    history: List[ChatTurn] = Field(default_factory=list)


class ChatResponse(BaseModel):
    response: str


# ============================================================
# Helper: AI Brief Generation
# ============================================================

async def _generate_ai_brief(ai_service: UrbanOSAIService, context: Dict[str, Any], brief_type: str = "city") -> Optional[str]:
    """Generate AI brief with timeout and fallback."""
    if not ai_service.is_available():
        return None
    try:
        if brief_type == "city":
            return await asyncio.wait_for(
                ai_service.generate_city_brief(context),
                timeout=10.0
            )
        else:
            return await asyncio.wait_for(
                ai_service.generate_module_brief(context),
                timeout=10.0
            )
    except asyncio.TimeoutError:
        log.warning("AI brief generation timed out")
        return None
    except Exception as e:
        log.warning("AI brief generation failed: %s", e)
        return None


async def _copilot_answer(ai_service, ctx) -> tuple:
    """Generate and validate a Copilot answer. Never raises."""
    try:
        return await asyncio.wait_for(
            ai_service.generate_copilot_answer(ctx), timeout=25.0
        )
    except asyncio.TimeoutError:
        log.warning("Copilot answer timed out; using grounded fallback.")
    except Exception as e:
        log.warning("Copilot answer failed: %s", e)
    from backend.app.ai.narrative import NarrativeValidation
    return None, NarrativeValidation(ok=False, reasons=["generation failed"])


# ============================================================
# City Situation narrative
# ============================================================

#: Seconds the Overview request will wait for an LLM narrative before serving
#: the deterministic summary instead. This is a UI responsiveness budget, not a
#: guess at provider latency: the deterministic summary is always available and
#: correct, so the narrative is only worth waiting briefly for.
_NARRATIVE_BUDGET_S = 6.0

async def _narrative_or_fallback(ai_service, city_report) -> Optional[str]:
    """Grounded narrative when the LLM can produce a verifiable one.

    Any failure - unavailable provider, rejected output, timeout - falls back to
    the deterministic summary built from the same coordinator report. The
    dashboard therefore always shows something true.

    The LLM is given a short budget because the deterministic summary is
    *always* available: a narrative that has not arrived within
    ``_NARRATIVE_BUDGET_S`` is worth less than an instant, correct one. The
    provider call itself is still bounded by the httpx client timeout.
    """
    fallback = deterministic_summary(city_report)
    if not ai_service.is_available():
        return fallback
    try:
        narrative, _validation = await asyncio.wait_for(
            ai_service.generate_city_narrative(city_report),
            timeout=_NARRATIVE_BUDGET_S,
        )
    except asyncio.TimeoutError:
        log.warning("City narrative generation timed out; using deterministic summary.")
        return fallback
    except Exception as e:
        log.warning("City narrative generation failed: %s", e)
        return fallback
    return narrative or fallback


async def _coordinator_assessment() -> Tuple[Optional[str], bool, Optional[str]]:
    """Grounded city assessment from the cached coordinator report.

    Returns ``(narrative, ready, report_generated_at)``.

    ``ready`` is ``False`` whenever the coordinator report is unavailable or
    carries no usable evidence. That distinction is the whole point: a pending
    assessment must never be presented as a completed one, so the caller decides
    what to show and can tell the dashboard that reconciliation is needed.

    The report is read through the same cached accessor ``/api/city/report``
    uses, so both routes share one coordinator run, and the narrative is keyed
    on a hash of the evidence, so repeating this call within the cache window
    costs no provider quota.

    Regression note: the accessor returns a ``(report, json_payload)`` tuple.
    Passing that tuple straight to :func:`build_narrative_input` looks up
    attributes on the tuple, finds none, and returns ``None`` - so this endpoint
    fell back to per-domain prose on *every* request, not only cold ones. The
    report object must be unpacked first.
    """
    try:
        cached = city_report_cached(block=False)
    except Exception as e:
        log.warning("Coordinator report unavailable: %s", e)
        return None, False, None

    if cached is None:
        # Cold cache. The accessor has started a single background run; this
        # caller deliberately does not wait for it.
        return None, False, None

    report = cached[0] if isinstance(cached, tuple) else cached
    if report is None:
        return None, False, None

    # A report with no available domain and no validated finding yields only a
    # placeholder, which is strictly worse than per-domain evidence.
    if build_narrative_input(report) is None:
        return None, False, getattr(report, "generated_at", None)

    narrative = await _narrative_or_fallback(get_ai_service(), report)
    return narrative, True, getattr(report, "generated_at", None)


# ============================================================
# Module summary helpers (single source of truth)
# ============================================================
# The status / KPI / brief logic used to be duplicated between this module and
# overview/context.py, and the two copies had already drifted (the Roads
# "critical" branch was unreachable here). All three now live in
# backend.app.intelligence.normalize so the overview cards, the coordinator and
# the KPI insight panels can never disagree.

def _determine_module_status(module_id: str, data: Dict[str, Any]) -> str:
    """normal | elevated | critical | unavailable."""
    return determine_status(module_id, data)


def _extract_module_kpi(module_id: str, data: Dict[str, Any]) -> Optional[ModuleKPI]:
    """Single headline metric for a module card, or None when unsupported."""
    kpi = build_kpi(module_id, data)
    return ModuleKPI(**kpi) if kpi else None


def _generate_deterministic_module_brief(module_id: str, module_data: Dict[str, Any]) -> str:
    """Plain-language module summary built from real values only.

    Falls back to the module's own evidence-backed findings, so Water, Land and
    Crime no longer produce an empty "<Name> module update." string.
    """
    name = DOMAIN_NAMES.get(module_id, module_id.capitalize())
    if module_data.get("error"):
        return f"{name} module: data currently unavailable."

    parts: List[str] = []
    if module_id == "traffic":
        congestion = module_data.get("overall_congestion_level")
        speed = module_data.get("overall_average_speed")
        if congestion and speed is not None:
            parts.append(f"Congestion: {congestion}, avg speed {speed:.1f} km/h.")
        elif congestion:
            parts.append(f"Congestion: {congestion}.")
        elif speed is not None:
            parts.append(f"Avg speed: {speed:.1f} km/h.")
    elif module_id == "roads":
        rw = module_data.get("road_works")
        if isinstance(rw, dict):
            parts.append(
                f"{rw.get('active', 0)} active road works, {rw.get('upcoming', 0)} upcoming.")
    elif module_id == "transit":
        alerts = module_data.get("active_train_alerts") or 0
        if alerts:
            parts.append(f"{alerts} active train alerts.")
    elif module_id == "pm25":
        regions = module_data.get("regions") or {}
        values = [
            v.get("value") for v in regions.values()
            if isinstance(v, dict) and v.get("value") is not None
        ]
        if values:
            parts.append(f"Current avg PM2.5: {sum(values) / len(values):.1f} µg/m³.")
    elif module_id == "weather":
        temp = (module_data.get("general") or {}).get("temperature_c")
        if temp is not None:
            parts.append(f"Current temp: {temp}°C.")
    elif module_id == "flood":
        risk = module_data.get("risk_level")
        if risk:
            parts.append(f"Flood risk: {risk}.")
    elif module_id == "fire":
        active = module_data.get("active_incident_count")
        if active is not None:
            parts.append(f"{active} active fire incidents.")

    if parts:
        return f"{name} module update. " + " ".join(parts)

    # No dedicated phrasing: use the domain's own evidence-backed findings.
    status = normalize_domain_report(module_id, module_data)
    usable = [f for f in status.findings if f.data_kind != "unavailable"]
    if usable:
        return f"{name} module update. " + " ".join(f.answer for f in usable[:2])
    if status.findings:
        return f"{name} module: {status.findings[0].answer}"
    return f"{name} module update."


# ============================================================
# Direct Service Access Helpers (NO HTTP LOOPBACK)
# ============================================================

async def _fetch_traffic_overview(app_state) -> Dict[str, Any]:
    """Fetch lightweight traffic overview using shared prediction service."""
    try:
        service = app_state.traffic_prediction_service
        bundle = await asyncio.to_thread(service.get_bundle)
        
        if bundle is None or not bundle.link_preds:
            return {"error": "No traffic prediction data available"}
        
        link_preds = bundle.link_preds
        
        # Compute overall metrics
        current_speeds = [lp.current_speed for lp in link_preds if lp.current_speed is not None]
        predicted_speeds = [lp.predicted_speed for lp in link_preds if lp.predicted_speed is not None]
        
        overall_current = sum(current_speeds) / len(current_speeds) if current_speeds else None
        overall_predicted = sum(predicted_speeds) / len(predicted_speeds) if predicted_speeds else None
        
        # Determine congestion level
        speed_for_congestion = overall_predicted if overall_predicted is not None else overall_current
        if speed_for_congestion is not None:
            if speed_for_congestion >= 70:
                congestion = "free_flow"
            elif speed_for_congestion >= 50:
                congestion = "moderate"
            elif speed_for_congestion >= 30:
                congestion = "heavy"
            else:
                congestion = "severe"
        else:
            congestion = "unknown"
        
        # Count incidents using existing client
        try:
            incidents_client = app_state.traffic_incidents_client
            incidents_snap = await asyncio.to_thread(incidents_client.fetch)
            incident_count = len(incidents_snap.incidents) if incidents_snap and incidents_snap.incidents else 0
        except Exception:
            incident_count = 0
        
        return {
            "overall_average_speed": round(overall_current, 1) if overall_current else None,
            "overall_predicted_speed": round(overall_predicted, 1) if overall_predicted else None,
            "overall_congestion_level": congestion,
            "incident_count": incident_count,
            "prediction_timestamp": bundle.link_preds[0].prediction_timestamp if link_preds else None,
            "target_timestamp": bundle.link_preds[0].target_timestamp if link_preds else None,
        }
    except Exception as e:
        log.warning("Traffic overview fetch failed: %s", e)
        return {"error": str(e)}


def _roads_overview_sync() -> Dict[str, Any]:
    """Blocking roads aggregation. Runs in a worker thread, never on the loop.

    Delegates to the Roads aggregator, which bounds each LTA sub-source,
    isolates their failures and can serve a clearly-marked stale payload when the
    upstream is down. The three feeds used to be fetched sequentially with no
    bound on total time.
    """
    from backend.app.mobility.roads.aggregator import get_roads_snapshot

    snapshot = get_roads_snapshot()
    return {
        "road_works": snapshot.get("road_works"),
        "road_openings": snapshot.get("road_openings"),
        "taxi_stands": snapshot.get("taxi_stands"),
        "timestamp": snapshot.get("fetched_at"),
        "source_status": snapshot.get("source_status"),
        "partial": snapshot.get("partial", False),
        "stale": snapshot.get("stale", False),
        "age_seconds": snapshot.get("age_seconds"),
        "unavailable_sources": snapshot.get("unavailable_sources", []),
        "warnings": snapshot.get("warnings", []),
    }


async def _fetch_roads_overview(app_state) -> Dict[str, Any]:
    """Roads overview, aggregated off the event loop.

    The three upstream clients are synchronous HTTP. Running them inline on the
    loop blocked every other request for the duration: measured, a 2.1s
    ``/api/mobility/transit/status`` took 24.1s while this fetcher was running,
    and the Overview itself took 45s.
    """
    try:
        return await asyncio.to_thread(_roads_overview_sync)
    except Exception as e:
        log.warning("Roads overview fetch failed: %s", e)
        return {"error": str(e)}


async def _fetch_transit_overview(app_state) -> Dict[str, Any]:
    """Fetch lightweight transit overview."""
    try:
        from backend.app.mobility.transit.data import TransitDataStore
        store = TransitDataStore()
        stats = store.get_stats()
        all_alerts = store.get_latest_train_alerts(limit=60)
        train_alerts = [a for a in all_alerts if a.category in ("metro", "rail")]
        active_train_count = sum(1 for a in all_alerts if a.category in ("metro", "rail"))
        
        return {
            "bus_services_count": stats["bus_services"],
            "bus_routes_count": stats["bus_routes"],
            "bus_stops_count": stats["bus_stops"],
            "active_train_alerts": active_train_count,
            "train_alerts_count": len(train_alerts),
        }
    except Exception as e:
        log.warning("Transit overview fetch failed: %s", e)
        return {"error": str(e)}


async def _fetch_pm25_overview(app_state) -> Dict[str, Any]:
    """Fetch lightweight PM2.5 overview from live snapshot service."""
    try:
        snap = app_state.pm25_live_service.snapshot()
        if snap is None:
            return {"error": "No PM2.5 live snapshot available"}
        return snap.to_dict()
    except Exception as e:
        log.warning("PM2.5 overview fetch failed: %s", e)
        return {"error": str(e)}


async def _fetch_weather_overview(app_state) -> Dict[str, Any]:
    """Fetch lightweight weather overview from weather client. Handle 429 gracefully."""
    try:
        client = app_state.weather_client
        snap = await asyncio.to_thread(client.fetch)
        return snap.to_dict()
    except Exception as e:
        # Check if it's a 429 rate limit
        if "429" in str(e):
            log.warning("Weather API rate limited (429): %s", e)
            return {"error": "rate_limited", "message": "Weather API rate limited"}
        log.warning("Weather overview fetch failed: %s", e)
        return {"error": str(e)}


async def _fetch_flood_overview(app_state, cache: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Full flood assessment from the Flood & Rain agent.

    The Overview card and the City Coordinator must read the *same* assessment.
    It used to read ``app.state.flood_client``, which is a PUB flood-alert
    client: that payload carries no ``risk_level`` at all, so the card reported
    "Normal" whenever the PUB call succeeded - including when every rainfall
    source was unavailable and the agent had correctly assessed nothing.

    The agent's own report keeps the four inputs distinct
    (``singapore_rainfall``, ``sumatra_rainfall``, ``active_alerts``,
    ``regional_weather``), so the Overview inherits that separation instead of
    collapsing it onto one alert feed.
    """
    if cache is not None and _FLOOD_ASSESSMENT_KEY in cache:
        return cache[_FLOOD_ASSESSMENT_KEY]

    try:
        from backend.app.environment.flood.agent import run_flood_agent_v3
        # mode="json" so FloodRiskLevel (a str Enum) arrives as a plain string.
        # In python mode it stays a member, str() yields "FloodRiskLevel.LOW",
        # and no status rule would match it.
        report = await asyncio.to_thread(run_flood_agent_v3)
        data = report.model_dump(mode="json")
    except Exception as e:
        log.warning("Flood overview fetch failed: %s", e)
        data = {"error": str(e)}

    if cache is not None:
        cache[_FLOOD_ASSESSMENT_KEY] = data
    return data


async def _fetch_fire_overview(app_state) -> Dict[str, Any]:
    """Fetch lightweight fire overview using fire agent."""
    try:
        from backend.app.safety.fire.agent import run_fire_agent
        report = await asyncio.to_thread(run_fire_agent)
        return report.model_dump()
    except Exception as e:
        log.warning("Fire overview fetch failed: %s", e)
        return {"error": str(e)}


async def _fetch_water_overview(app_state) -> Dict[str, Any]:
    """Fetch lightweight water overview using water agent."""
    try:
        from backend.app.infrastructure.water.agent import run_water_agent
        report = await asyncio.to_thread(run_water_agent)
        return report.model_dump()
    except Exception as e:
        log.warning("Water overview fetch failed: %s", e)
        return {"error": str(e)}


async def _fetch_crime_overview(app_state, cache: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Crime module card, built from the published police statistics.

    The report is memoised so the alert summary in the same request reuses it
    instead of repeating four data.gov.sg dataset fetches.
    """
    try:
        from backend.app.safety.crime.agent import run_crime_agent
        if cache is not None and _CRIME_REPORT_KEY in cache:
            report = cache[_CRIME_REPORT_KEY]
        else:
            report = await asyncio.to_thread(run_crime_agent)
            if cache is not None:
                cache[_CRIME_REPORT_KEY] = report
        return report.model_dump()
    except Exception as e:
        log.warning("Crime overview fetch failed: %s", e)
        return {"error": str(e)}


async def _fetch_land_overview(app_state) -> Dict[str, Any]:
    """Fetch lightweight land overview using land agent."""
    try:
        from backend.app.planning.land.agent import run_land_agent
        report = await asyncio.to_thread(run_land_agent)
        return report.model_dump()
    except Exception as e:
        log.warning("Land overview fetch failed: %s", e)
        return {"error": str(e)}


# ============================================================
# Alert Fetching (direct service calls, NO HTTP LOOPBACK)
# ============================================================

class AlertBatch(List[Dict[str, Any]]):
    """Alerts from one source, plus whether that source was reachable.

    Subclasses ``list`` so every existing consumer - ``isinstance(result, list)``
    and ``all_alerts.extend(...)`` - keeps working unchanged. The extra
    attributes exist so a source that was *unavailable* can be told apart from
    one that genuinely returned zero records: the first is a data gap that must
    be logged and treated as degraded, the second is a real "nothing is
    happening right now".
    """

    def __init__(self, alerts: Iterable[Dict[str, Any]] = (), *,
                 source_ok: bool = True, source_error: Optional[str] = None) -> None:
        super().__init__(alerts)
        self.source_ok = source_ok
        self.source_error = source_error

    @classmethod
    def unavailable(cls, source: str) -> "AlertBatch":
        """Empty and flagged as unreachable.

        ``source_error`` is a fixed, non-leaky label. The raw exception may name
        hosts, URLs or credential problems, so it goes to the log only and never
        reaches an API response.
        """
        return cls((), source_ok=False, source_error=f"{source} alert source unavailable")


def _alert_timestamp(value: Any) -> str:
    """Normalise a source timestamp to an ISO string for sorting and display."""
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


async def _fetch_traffic_incidents(cache: Optional[Dict[str, Any]] = None) -> AlertBatch:
    """Live traffic incidents from the LTA DataMall adapter.

    ``TrafficIncident`` exposes ``incident_type`` (not ``type``) and carries no
    per-incident timestamp at all, so the observation time of the snapshot the
    record came from is used instead of inventing one.

    The feed publishes no severity, so none is inferred: ``"info"`` says
    "reported" without ranking something the source never ranked.

    ``cache`` is accepted (and unused) so every alert fetcher has the same
    signature as the one the endpoint calls. A mismatch here previously raised
    ``TypeError`` inside the endpoint and silently emptied this source.
    """
    try:
        from backend.app.mobility.traffic.api import TrafficIncidentsApiClient
        client = TrafficIncidentsApiClient(offline=False)
        snap = await asyncio.to_thread(client.fetch)
    except Exception as exc:
        log.warning("Traffic incident source unavailable: %s", exc)
        return AlertBatch.unavailable("traffic")

    snapshot_at = getattr(snap, "snapshot_at", None)
    alerts: List[Dict[str, Any]] = []
    for inc in (snap.incidents or [])[:3]:
        incident_type = getattr(inc, "incident_type", None) or "Traffic Incident"
        description = getattr(inc, "message", None) or incident_type
        # Prefer the human-readable zone name in prose; keep the canonical id
        # in affected_zones so downstream consumers match on a stable value.
        zone_label = inc.zone_name or inc.zone_id
        if zone_label:
            description = f"{description} ({zone_label})"
        alerts.append({
            "domain": "traffic",
            "severity": "info",
            "title": incident_type,
            "description": description,
            # The snapshot this record was read from - the only real time the
            # adapter exposes for the incident.
            "timestamp": _alert_timestamp(snapshot_at),
            "affected_zones": [inc.zone_id] if inc.zone_id else [],
        })
    return AlertBatch(alerts)


async def _fetch_fire_incidents(cache: Optional[Dict[str, Any]] = None) -> List[Dict]:
    """Fetch fire incidents for alerts.

    The SCDF feed already carries a severity and a report time per incident, so
    both are passed through unchanged. ``cache`` is accepted only to match the
    other alert fetchers; fire is not memoised here.
    """
    try:
        from backend.app.safety.fire.agent import run_fire_agent
        report = await asyncio.to_thread(run_fire_agent)
        incidents = []
        for inc in (report.active_incidents or [])[:3]:
            incidents.append({
                "domain": "fire",
                "severity": inc.severity,
                "title": inc.title,
                "description": inc.summary or inc.title,
                "timestamp": inc.reported_at,
                "affected_zones": [inc.region] if inc.region else [],
            })
        return incidents
    except Exception:
        return []


async def _fetch_flood_alerts(cache: Optional[Dict[str, Any]] = None) -> AlertBatch:
    """Live PUB flood alerts.

    ``FloodAlert`` names the field ``alert_type`` (its ``to_dict`` renames it to
    ``"type"``, which is what made the dataclass read look wrong).

    PUB publishes a real severity per alert, so it is passed through rather than
    mapped onto the platform's own vocabulary. The alert's own issue time is
    used, falling back to the snapshot time when it is absent.

    ``allow_fallback_fixture=False`` is deliberate. With it, an unreachable PUB
    endpoint used to return the deterministic fixture instead - two invented
    "Flash Flood" advisories for Orchard Road and Bukit Timah dated 2024-12-01 -
    which the Overview then published as live High-severity flood alerts. A
    source that cannot be reached is now reported as unavailable.

    ``cache`` is accepted (and unused) so every alert fetcher has the same
    signature as the one the endpoint calls.
    """
    try:
        from backend.app.environment.flood.api import FloodAlertsApiClient
        client = FloodAlertsApiClient(offline=False, allow_fallback_fixture=False)
        snap = await asyncio.to_thread(client.fetch)
    except Exception as exc:
        log.warning("Flood alert source unavailable: %s", exc)
        return AlertBatch.unavailable("flood")

    snapshot_at = getattr(snap, "snapshot_at", None)
    alerts: List[Dict[str, Any]] = []
    for alert in (snap.alerts or [])[:2]:
        alert_type = getattr(alert, "alert_type", None) or "Flood Alert"
        description = getattr(alert, "message", None) or alert_type
        if alert.location:
            description = f"{description} ({alert.location})"
        alerts.append({
            "domain": "flood",
            # The publisher's own severity, verbatim.
            "severity": alert.severity or "UNKNOWN",
            "title": alert_type,
            "description": description,
            "timestamp": _alert_timestamp(alert.issued_at or snapshot_at),
            "affected_zones": [alert.zone_id] if alert.zone_id else [],
        })
    # Zero alerts from a successful call is a real, healthy answer.
    return AlertBatch(alerts)


async def _fetch_crime_incidents(cache: Optional[Dict[str, Any]] = None) -> AlertBatch:
    """One clearly-labelled summary of the published crime statistics.

    There is no live crime-incident feed in this system. The data.gov.sg
    datasets are *annual aggregate tables*: rows keyed by ``DataSeries`` with one
    column per year. Iterating them yields statistical series, not incidents -
    which is why the previous version rendered three identical
    ``"Crime Case" / "Incident - N/A"`` rows with an empty timestamp, an
    invented ``"elevated"`` severity and no location.

    So the real information is preserved as a single statistics entry instead,
    with no invented identifier, location, incident timestamp or severity. The
    timestamp is the retrieval time and the description states the data period,
    so an annual figure can never read as a live incident.
    """
    try:
        from backend.app.safety.crime.agent import run_crime_agent
        if cache is not None and _CRIME_REPORT_KEY in cache:
            report = cache[_CRIME_REPORT_KEY]
        else:
            report = await asyncio.to_thread(run_crime_agent)
            if cache is not None:
                cache[_CRIME_REPORT_KEY] = report
    except Exception as exc:
        log.warning("Crime statistics source unavailable: %s", exc)
        return AlertBatch.unavailable("crime")

    if report.source_status == "unavailable":
        log.warning("Crime statistics unavailable: no official dataset was loaded.")
        return AlertBatch.unavailable("crime")

    parts: List[str] = []
    if report.total_physical_crime_2025 is not None:
        parts.append(f"{report.total_physical_crime_2025:,} physical crimes")
    if report.total_scams_cybercrime_2025 is not None:
        parts.append(f"{report.total_scams_cybercrime_2025:,} scams and cybercrime")
    if not parts:
        # Loaded successfully but carries nothing to summarise.
        log.info("Crime statistics loaded but hold no reportable 2025 totals.")
        return AlertBatch(())

    period = report.data_period if report.data_period != "unknown" else "period not stated"
    return AlertBatch([{
        "domain": "crime",
        # The police statistics carry no severity feed, so none is inferred.
        "severity": "info",
        "title": "Crime: published annual statistics",
        "description": (
            f"Police statistics ({period}): " + " and ".join(parts)
            + ". Annual published figures, not live incidents - this system "
              "has no incident-level crime feed."
        ),
        "timestamp": _alert_timestamp(report.generated_at),
        "affected_zones": [],
    }])


async def _fetch_water_incidents(cache: Optional[Dict[str, Any]] = None) -> List[Dict]:
    """Fetch water alerts from water agent (drain conditions, quality exceedances, usage changes).

    ``cache`` is accepted only to match the other alert fetchers; water is not
    memoised here.
    """
    try:
        from backend.app.infrastructure.water.agent import run_water_agent
        report = await asyncio.to_thread(run_water_agent)
        incidents = []
        for alert in (report.alerts or [])[:5]:
            incidents.append({
                "domain": "water",
                "severity": alert.severity.lower(),
                "title": f"Water: {alert.category}",
                "description": alert.message,
                "timestamp": alert.evidence[0] if alert.evidence else report.generated_at.isoformat(),
                "affected_zones": [],
            })
        return incidents
    except Exception:
        return []


# ============================================================
# Main Endpoints
# ============================================================

@router.get("/city", response_model=CityOverviewResponse)
async def get_overview_city(request: Request) -> CityOverviewResponse:
    """
    Get lightweight city overview using direct service calls (NO HTTP LOOPBACK).
    Part 1: Base city/module data only. No AI, no alerts, no cross-domain intelligence.
    """
    app_state = request.app.state
    
    # Fetch all modules concurrently with error isolation
    module_ids = ["traffic", "roads", "transit", "pm25", "weather", "flood",
                  "fire", "crime", "water", "land"]
    fetchers = {
        "traffic": _fetch_traffic_overview,
        "roads": _fetch_roads_overview,
        "transit": _fetch_transit_overview,
        "pm25": _fetch_pm25_overview,
        "weather": _fetch_weather_overview,
        "flood": _fetch_flood_overview,
        "fire": _fetch_fire_overview,
        "crime": _fetch_crime_overview,
        "water": _fetch_water_overview,
        "land": _fetch_land_overview,
    }
    # Flood and crime both cost several live API calls, and each is needed
    # twice in this request (module card + alert summary). Memoise them for the
    # lifetime of this request only: the dict is created here and goes out of
    # scope with the response, so it can never leak between requests.
    request_cache: Dict[str, Any] = {}

    async def fetch_module(module_id: str) -> Dict[str, Any]:
        fetcher = fetchers[module_id]
        if module_id == "flood":
            return await fetcher(request.app.state, request_cache)
        if module_id == "crime":
            return await fetcher(request.app.state, request_cache)
        return await fetcher(request.app.state)

    results = await asyncio.gather(
        *(fetch_module(m) for m in module_ids),
        return_exceptions=True,
    )

    module_data = {}
    for module_id, result in zip(module_ids, results):
        if isinstance(result, Exception):
            log.exception("Module %s failed with exception: %s", module_id, result)
            module_data[module_id] = {"error": str(result)}
        else:
            module_data[module_id] = result
    
    # Build module summaries through the shared normaliser, so the overview
    # cards, the coordinator and the KPI insight panels read one source.
    modules = []
    domain_status: Dict[str, DomainStatus] = {}
    for module_id in module_ids:
        data = module_data.get(module_id, {"error": "No data"})
        status = normalize_domain_report(module_id, data)
        domain_status[module_id] = status

        updated_at = None
        if isinstance(data, dict):
            updated_at = data.get("timestamp") or data.get("snapshot_at") or data.get("generated_at")
            if updated_at is not None and hasattr(updated_at, "isoformat"):
                updated_at = updated_at.isoformat()

        modules.append(ModuleSummary(
            id=module_id,
            name=DOMAIN_NAMES.get(module_id, module_id.title()),
            status=("unavailable" if not status.available else
                    _determine_module_status(module_id, data)),
            kpi=_extract_module_kpi(module_id, data),
            updated_at=updated_at,
            detail_route=DOMAIN_ROUTES.get(module_id, "/"),
        ))
    
    # Part 2: Fetch real alerts from all sources with error isolation.
    # Each source is independent: one failing source degrades only its own
    # contribution. A source that could not be reached is logged as a data gap;
    # a source that was reached and had nothing to report is logged as zero.
    all_alerts: List[Dict[str, Any]] = []
    for name, fetch_fn in [
        ("traffic", _fetch_traffic_incidents),
        ("fire", _fetch_fire_incidents),
        ("flood", _fetch_flood_alerts),
        ("crime", _fetch_crime_incidents),
        ("water", _fetch_water_incidents),
    ]:
        try:
            result = await asyncio.wait_for(
                fetch_fn(request_cache), timeout=8.0
            )
            if isinstance(result, list):
                if isinstance(result, AlertBatch) and not result.source_ok:
                    log.warning("Alert source %s unavailable: %s", name, result.source_error)
                else:
                    log.info("Alert source %s returned %d alerts", name, len(result))
                all_alerts.extend(result)
        except asyncio.TimeoutError:
            log.warning("Alert source %s timed out after 8 seconds", name)
        except Exception as e:
            log.warning("Alert source %s failed: %s", name, e)
    
    # Surface status for non-normal modules.
    # An unavailable module is NOT turned into an alert: a missing feed is a
    # data-quality fact already carried by its finding, not a city risk signal.
    for module in modules:
        if module.status in ("elevated", "critical"):
            data = module_data.get(module.id, {})
            all_alerts.append({
                "domain": module.id,
                "severity": module.status,
                "title": f"{module.name} Status: {module.status.capitalize()}",
                "description": _generate_deterministic_module_brief(module.id, data),
                "timestamp": datetime.now(SG_OFFSET).isoformat(),
                "affected_zones": domain_status[module.id].affected_zones,
            })
    
    # Sort by timestamp descending, take top 20
    all_alerts.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    top_alerts = all_alerts[:20]

    # ---- City Situation narrative (Phase 3) ---------------------------------
    # The deterministic coordinator report is the only permitted source for the
    # city-level narrative, and it is shared with /api/city/report through the
    # cached accessor, so the two never run the coordinator twice.
    #
    # Non-blocking on purpose: a measured coordinator run takes ~74s, far longer
    # than a dashboard refresh may wait. When the cache is cold this response
    # carries per-domain evidence only and says so via
    # ``city_assessment_ready=False``; the dashboard reconciles once the report
    # it is already waiting on completes.
    narrative, assessment_ready, _report_at = await _coordinator_assessment()

    if assessment_ready:
        ai_brief = narrative
    else:
        # Cold start, or a coordinator report carrying no usable evidence: fall
        # back to the per-domain readings rather than showing nothing. This
        # never claims a city status or risk level.
        ai_brief = deterministic_summary_from_domains(domain_status)

    return CityOverviewResponse(
        generated_at=datetime.now(SG_OFFSET).isoformat(),
        modules=modules,
        domain_status=domain_status,
        alerts=[
            AlertItem(
                domain=a["domain"],
                severity=a["severity"],
                title=a["title"],
                description=a["description"],
                timestamp=a["timestamp"],
                affected_zones=a.get("affected_zones", []),
            )
            for a in top_alerts
        ],
        ai_brief=ai_brief,
        city_assessment_ready=assessment_ready,
    )


@router.get("/city-narrative", response_model=CityNarrativeResponse)
async def get_city_narrative() -> CityNarrativeResponse:
    """Reconcile the City Situation against a finished coordinator report.

    The Overview endpoint cannot simply be called twice to pick up a report
    that finished after it answered, because it re-runs all ten domain agents -
    several live API calls. This endpoint reads only the cached coordinator
    report and the cached narrative, so reconciliation is cheap and costs no
    provider quota when the evidence has not changed.
    """
    narrative, ready, report_at = await _coordinator_assessment()
    return CityNarrativeResponse(
        ai_brief=narrative,
        city_assessment_ready=ready,
        report_generated_at=_iso_or_none(report_at),
    )


def _iso_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


@router.get("/module/{module_id}", response_model=ModuleDetailResponse)
async def get_overview_module(
    request: Request,
    module_id: str = Path(..., description="Module ID"),
) -> ModuleDetailResponse:
    """
    Get detailed overview for a specific module using direct service calls.
    """
    fetch_functions = {
        "traffic": _fetch_traffic_overview,
        "roads": _fetch_roads_overview,
        "transit": _fetch_transit_overview,
        "pm25": _fetch_pm25_overview,
        "weather": _fetch_weather_overview,
        "flood": _fetch_flood_overview,
        "fire": _fetch_fire_overview,
        "crime": _fetch_crime_overview,
        "water": _fetch_water_overview,
        "land": _fetch_land_overview,
    }

    if module_id not in fetch_functions:
        raise HTTPException(status_code=404, detail=f"Module '{module_id}' not found")

    fetch_fn = fetch_functions[module_id]

    try:
        data = await fetch_fn(request.app.state)
    except Exception as e:
        log.warning("Failed to fetch module %s: %s", module_id, e)
        data = {"error": str(e)}

    if data.get("error"):
        status = "unavailable"
        kpi = None
    else:
        status = _determine_module_status(module_id, data)
        kpi = _extract_module_kpi(module_id, data)

    # The module detail summary is the deterministic, evidence-backed brief.
    # Phase 3 layers optional LLM phrasing on top of the same findings; it is
    # never the only source of truth for this panel.
    summary = _generate_deterministic_module_brief(module_id, data)

    alerts = []
    if module_id == "traffic":
        alerts = await _fetch_traffic_incidents()
    elif module_id == "fire":
        alerts = await _fetch_fire_incidents()
    elif module_id == "flood":
        alerts = await _fetch_flood_alerts()
    elif module_id == "crime":
        alerts = await _fetch_crime_incidents()

    # Some agents emit datetimes, others ISO strings; normalise once here.
    status_obj = normalize_domain_report(module_id, data)

    return ModuleDetailResponse(
        module_id=module_id,
        module_name=DOMAIN_NAMES.get(module_id, module_id.title()),
        status=status,
        kpi=kpi,
        updated_at=status_obj.generated_at,
        summary=summary,
        alerts=[AlertItem(**a) for a in alerts[:3]],
        cross_domain=[],
        detail_route=DOMAIN_ROUTES.get(module_id, "/"),
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, chat_request: ChatRequest) -> ChatResponse:
    """Grounded Copilot.

    Answers only from the validated City Coordinator report. The user's text
    and the retrieved evidence are both treated as untrusted data and are never
    interpolated into system instructions. Every answer is validated before it
    is returned, and a grounded deterministic fallback is used whenever the
    model cannot produce something verifiable.
    """
    from backend.app.ai.copilot import (
        build_copilot_context, grounded_fallback,
    )

    user_message = (chat_request.message or "").strip()[:MAX_QUESTION_CHARS]
    if not user_message:
        return ChatResponse(response="Please enter a question.")

    history = [
        {"role": h.role, "text": (h.text or "")[:MAX_HISTORY_CHARS]}
        for h in (chat_request.history or [])[-MAX_HISTORY_TURNS:]
    ]

    # Single shared, cached coordinator run - no duplicate agent execution.
    report = None
    try:
        report, _payload = await asyncio.wait_for(
            asyncio.to_thread(city_report_cached), timeout=20.0
        )
    except asyncio.TimeoutError:
        log.warning("Copilot: coordinator report unavailable within 20s.")
    except Exception as e:
        log.warning("Copilot: coordinator report unavailable: %s", e)

    ctx = build_copilot_context(
        report, user_message, chat_request.module_id, history
    )
    fallback = grounded_fallback(ctx)

    ai_service = get_ai_service()
    answer, _validation = await _copilot_answer(ai_service, ctx)
    return ChatResponse(response=answer or fallback)


log.info("UrbanOS Overview API router initialized (direct service mode, no HTTP loopback).")
