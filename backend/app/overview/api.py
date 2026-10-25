"""UrbanOS Overview API endpoints - direct service aggregation (no HTTP loopback)."""

from __future__ import annotations

import asyncio
import copy
import logging
import math
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Path, Query, status, Request
from pydantic import BaseModel, Field

from backend.app.ai.copilot import (
    MAX_HISTORY_CHARS, MAX_HISTORY_TURNS, MAX_QUESTION_CHARS,
    build_copilot_context, detect_domains, grounded_fallback,
)
from backend.app.ai.narrative import (
    build_narrative_input, deterministic_summary,
    deterministic_summary_from_domains,
)
from backend.app.ai.service import get_ai_service, UrbanOSAIService
# ``city_report_cached`` is deliberately still imported even though this
# module no longer calls it: the chat route must only ever *peek* at the
# coordinator cache (starting a ~74s run inside a chat request is what blew
# its latency budget), and tests assert on this attribute to enforce that.
from backend.app.coordinator.access import city_report_cached, peek_city_report_cached  # noqa: F401
from backend.app.intelligence.contracts import DomainStatus
from backend.app.intelligence.normalize import (
    CANONICAL_MODULES, DOMAIN_NAMES, DOMAIN_ROUTES, build_card_metrics,
    build_kpi, determine_status, normalize_domain_report,
)

log = logging.getLogger(__name__)

# Singapore timezone offset (UTC+8)
SG_OFFSET = timezone(timedelta(hours=8))

router = APIRouter(prefix="/api/overview", tags=["overview"])

# Optional legacy per-call memo keys accepted by helper functions. Active
# summary requests use ``_OVERVIEW_SUMMARY_CACHE`` so independent HTTP requests
# share in-flight work and short-lived results.
#: A full flood assessment costs several live API calls and is needed twice.
_FLOOD_ASSESSMENT_KEY = "flood_assessment"
#: The crime report costs four data.gov.sg dataset fetches and is needed twice.
_CRIME_REPORT_KEY = "crime_report"


class _OverviewSummaryCache:
    """Process-local cache and single-flight gate for domain summaries.

    The cache is deliberately outside the route-local data dict: separate
    Overview, module-detail, and Copilot requests for the same module now share
    one computation. Values are copied at the boundary because graph reports
    contain mutable dictionaries. Failed/unavailable results get a short
    cooldown so a provider outage cannot become a request storm.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: Dict[Tuple[int, str], Tuple[float, Any, Dict[str, Any]]] = {}
        self._in_flight: Dict[Tuple[int, str], Tuple[Any, asyncio.Task, asyncio.Event]] = {}

    async def get(
        self,
        app_state: Any,
        module_id: str,
        loader: Any,
        *,
        started: Optional[asyncio.Event] = None,
        timeout_after_start: Optional[float] = None,
    ) -> Dict[str, Any]:
        key = (id(app_state), module_id)
        now = time.monotonic()
        with self._lock:
            for expired_key, expired in list(self._entries.items()):
                if expired[0] <= now:
                    self._entries.pop(expired_key, None)
            entry = self._entries.get(key)
            if entry and entry[1] is app_state and entry[0] > now:
                return copy.deepcopy(entry[2])
            if entry:
                self._entries.pop(key, None)
            in_flight = self._in_flight.get(key)
            if in_flight and in_flight[0] is app_state:
                task, operation_started = in_flight[1], in_flight[2]
            else:
                operation_started = started or asyncio.Event()
                # Ordinary detail/chat loaders are not queued behind the
                # city-summary semaphore, so their work is already started.
                if started is None:
                    operation_started.set()
                task = asyncio.create_task(
                    self._load(key, app_state, module_id, loader, operation_started)
                )
                self._in_flight[key] = (app_state, task, operation_started)

        if timeout_after_start is not None:
            # The city route bounds provider execution, not queue wait time.
            # Queued modules must not all time out merely because three other
            # modules currently own the bounded provider slots.
            await operation_started.wait()
            result = await asyncio.wait_for(asyncio.shield(task), timeout_after_start)
        else:
            result = await asyncio.shield(task)
        return copy.deepcopy(result)

    async def _load(self, key, app_state, module_id, loader, operation_started) -> Dict[str, Any]:
        try:
            # The route-level timeout may expire while a synchronous provider
            # call is still running in asyncio.to_thread. Shielding keeps the
            # single-flight marker alive until that real work completes, so a
            # following Overview request cannot launch a duplicate fetch.
            value = await loader()
            if not isinstance(value, dict):
                value = {"error": "invalid_domain_response"}
        except asyncio.CancelledError:
            with self._lock:
                current = self._in_flight.get(key)
                if current and current[0] is app_state:
                    self._in_flight.pop(key, None)
            raise
        except Exception as exc:
            log.warning("Overview %s summary failed: %s", module_id, exc)
            value = {"error": "summary_unavailable"}
        finally:
            # Prevent waiters from hanging if a loader fails before it signals
            # that its provider operation has acquired a concurrency slot.
            operation_started.set()

        self._finish(key, app_state, module_id, value)
        return value

    def _finish(self, key, app_state, module_id, value) -> None:
        failed = bool(value.get("error")) or str(value.get("source_status") or "").lower() == "unavailable"
        # Successful values are cached briefly at this layer. Domains with
        # report APIs still retain their longer source-aware TTL in those APIs;
        # the short overview TTL also bounds data without a report cache.
        ttl = _OVERVIEW_FAILURE_TTL_S if failed else _OVERVIEW_SUCCESS_TTLS_S.get(module_id, _OVERVIEW_DEFAULT_SUCCESS_TTL_S)
        with self._lock:
            self._entries[key] = (time.monotonic() + ttl, app_state, copy.deepcopy(value))
            current = self._in_flight.get(key)
            if current and current[0] is app_state:
                self._in_flight.pop(key, None)

    def clear(self) -> None:
        """Clear cached summaries; useful for explicit refresh and isolated tests."""
        with self._lock:
            self._entries.clear()


_OVERVIEW_SUMMARY_CACHE = _OverviewSummaryCache()
_OVERVIEW_DEFAULT_SUCCESS_TTL_S = 15.0
_OVERVIEW_FAILURE_TTL_S = 30.0
# Keep these no longer than the corresponding live source/report freshness
# windows. Existing report APIs below remain the authority for long-lived data.
_OVERVIEW_SUCCESS_TTLS_S = {"weather": 60.0, "flood": 30.0, "fire": 30.0, "crime": 60.0}


# ============================================================
# Response Models (matching frontend expectations)
# ============================================================

class ModuleKPI(BaseModel):
    label: str
    value: Any
    unit: str


class ModuleMetric(BaseModel):
    """One Overview card metric, independently available or unavailable.

    ``value`` is ``None`` exactly when this metric could not be obtained -
    the card then renders an explicit unavailable placeholder for THIS metric
    without hiding its sibling metrics. An explicit ``0`` is a real reading
    and is preserved.
    """
    key: str
    label: str
    value: Optional[Any] = None
    unit: str = ""


class ModuleSummary(BaseModel):
    id: str
    name: str
    status: str  # "normal" | "elevated" | "critical" | "unavailable"
    kpi: Optional[ModuleKPI] = None
    #: All intended card metrics for this module, each independently
    #: available or unavailable. Empty when the module has no usable data.
    metrics: List[ModuleMetric] = Field(default_factory=list)
    updated_at: Optional[str] = None
    detail_route: str
    #: Data availability/freshness is separate from the domain risk status.
    data_state: str = "unavailable"  # available | partial | stale | unavailable
    age_seconds: Optional[float] = None


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


#: Seconds the chat route will wait for the LLM answer before serving the
#: grounded deterministic fallback. The fallback is always available and
#: correct, so a slow provider is not worth the wait - and the budget plus the
#: domain-summary fetch budget must stay under the frontend's 30s abort.
_CHAT_LLM_BUDGET_S = 15.0


async def _copilot_answer(ai_service, ctx) -> tuple:
    """Generate and validate a Copilot answer. Never raises."""
    try:
        return await asyncio.wait_for(
            ai_service.generate_copilot_answer(ctx), timeout=_CHAT_LLM_BUDGET_S
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

    This is a cache-only read. It never launches a report run; only the explicit
    ``/api/city/report`` request starts the coordinator. The narrative is keyed
    on evidence so repeated reads reuse its cached text.

    Regression note: the accessor returns a ``(report, json_payload)`` tuple.
    Passing that tuple straight to :func:`build_narrative_input` looks up
    attributes on the tuple, finds none, and returns ``None`` - so this endpoint
    fell back to per-domain prose on *every* request, not only cold ones. The
    report object must be unpacked first.
    """
    try:
        cached = peek_city_report_cached()
    except Exception as e:
        log.warning("Coordinator report unavailable: %s", e)
        return None, False, None

    if cached is None:
        # Cold cache. This endpoint does not start or wait for domain work.
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
    """Summarize observed LTA speed bands; predictions stay on the detail page.

    The per-segment midpoint is an approximation because DataMall publishes a
    speed interval, not an exact speed. Each valid segment receives equal
    weight; missing, non-finite, or reversed intervals are omitted.
    """
    try:
        from backend.app.mobility.traffic.api import TrafficSpeedBandsV2ApiClient

        snapshot = await asyncio.to_thread(TrafficSpeedBandsV2ApiClient().fetch)
        valid_speeds = []
        for segment in snapshot.segments:
            speed = segment.speed_midpoint
            if (speed is not None and math.isfinite(speed) and speed >= 0
                    and segment.minimum_speed is not None
                    and segment.maximum_speed is not None
                    and segment.minimum_speed <= segment.maximum_speed):
                valid_speeds.append(speed)
        if not snapshot.is_live or not valid_speeds:
            return {"error": "No valid live LTA speed-band observations"}
        average = sum(valid_speeds) / len(valid_speeds)
        return {
            "overall_average_speed": round(average, 1),
            "generated_at": snapshot.snapshot_at,
            "timestamp": snapshot.snapshot_at,
            "source_status": "live",
            "source": snapshot.source,
            "limitations": [
                "Equal-weight average of valid LTA speed-band midpoints; each midpoint approximates a published speed interval."
            ],
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
        data = snap.to_dict()
        data["generated_at"] = snap.raw_issue_timestamp or snap.snapshot_at
        data["source_status"] = "live" if snap.is_live else "stale"
        return data
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
    """Fetch Water using the same TTL report cache as its detail endpoint."""
    try:
        from backend.app.infrastructure.water.api import get_water_report
        report = await asyncio.to_thread(get_water_report)
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
    """Fetch Land using the same TTL report cache as its detail endpoint."""
    try:
        from backend.app.planning.land.api import get_land_report
        report = await asyncio.to_thread(get_land_report)
        return report.model_dump()
    except Exception as e:
        log.warning("Land overview fetch failed: %s", e)
        return {"error": str(e)}


async def _fetch_waste_overview(app_state) -> Dict[str, Any]:
    """Fetch Waste using the same TTL report cache as its detail endpoint."""
    try:
        from backend.app.infrastructure.waste.api import get_waste_report
        report = await asyncio.to_thread(get_waste_report)
        return report.model_dump()
    except Exception as e:
        log.warning("Waste overview fetch failed: %s", e)
        return {"error": str(e)}


async def _fetch_energy_overview(app_state) -> Dict[str, Any]:
    """Fetch Energy using the same TTL report cache as its detail endpoint."""
    try:
        from backend.app.infrastructure.energy.api import get_energy_report
        report = await asyncio.to_thread(get_energy_report)
        return report.model_dump()
    except Exception as e:
        log.warning("Energy overview fetch failed: %s", e)
        return {"error": str(e)}


async def _fetch_housing_overview(app_state) -> Dict[str, Any]:
    """Fetch Housing using the same TTL report cache as its detail endpoint."""
    try:
        from backend.app.planning.housing.api import get_housing_report
        report = await asyncio.to_thread(get_housing_report)
        return report.model_dump()
    except Exception as e:
        log.warning("Housing overview fetch failed: %s", e)
        return {"error": str(e)}


async def _fetch_construction_overview(app_state) -> Dict[str, Any]:
    """Fetch Construction using its shared detail-report TTL cache."""
    try:
        from backend.app.planning.construction.api import get_construction_report
        report = await asyncio.to_thread(get_construction_report)
        return _construction_overview_data(report)
    except Exception as e:
        log.warning("Construction overview fetch failed: %s", e)
        return {"error": str(e)}


# ============================================================
# Module cache peeks (NO fetches, NO workflow starts)
# ============================================================
# The Overview city endpoint must stay cheap, so a card may only read caches
# that something else has already populated (a domain page visit, a shared
# domain service, or a previous coordinator run). Every helper below is a
# pure read: cold caches return None and the card honestly reports
# "unavailable". None of them runs an agent or contacts an upstream API.

def _peek_pm25_summary(app_state) -> Optional[Dict[str, Any]]:
    """Latest PM2.5 snapshot from the shared live-snapshot service."""
    service = getattr(app_state, "pm25_live_service", None)
    snapshot = service.snapshot() if service is not None else None
    if snapshot is None:
        return None
    data = snapshot.to_dict()
    data["generated_at"] = snapshot.raw_issue_timestamp or snapshot.snapshot_at
    data["source_status"] = "live" if snapshot.is_live else "stale"
    return data


def _peek_water_summary(app_state) -> Optional[Dict[str, Any]]:
    """Water report from the water router's TTL cache (never runs the agent)."""
    from backend.app.infrastructure.water.api import peek_water_report

    report = peek_water_report()
    if report is None:
        return None
    return report.model_dump()


def _peek_roads_summary(app_state) -> Optional[Dict[str, Any]]:
    """Roads snapshot from the aggregator's fresh cache (never refreshes)."""
    from backend.app.mobility.roads.aggregator import peek_roads_snapshot

    snapshot = peek_roads_snapshot()
    if snapshot is None:
        return None
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


def _peek_waste_summary(app_state) -> Optional[Dict[str, Any]]:
    """Waste report from the waste router's TTL cache (never runs the agent)."""
    from backend.app.infrastructure.waste.api import peek_waste_report

    report = peek_waste_report()
    if report is None:
        return None
    return report.model_dump()


def _peek_energy_summary(app_state) -> Optional[Dict[str, Any]]:
    """Energy report from the energy router's TTL cache (never runs the agent)."""
    from backend.app.infrastructure.energy.api import peek_energy_report

    report = peek_energy_report()
    if report is None:
        return None
    return report.model_dump()


def _peek_housing_summary(app_state) -> Optional[Dict[str, Any]]:
    """Housing report from the housing router's TTL cache (never runs the agent)."""
    from backend.app.planning.housing.api import peek_housing_report

    report = peek_housing_report()
    if report is None:
        return None
    return report.model_dump()


def _peek_construction_summary(app_state) -> Optional[Dict[str, Any]]:
    """Construction report from the router's TTL cache (never runs the agent)."""
    from backend.app.planning.construction.api import peek_construction_report

    report = peek_construction_report()
    if report is None:
        return None
    return _construction_overview_data(report)


def _construction_overview_data(report) -> Dict[str, Any]:
    """Use source publication time when supplied; agent time is not publication."""
    data = report.model_dump()
    published = []
    for source in data.get("sources") or []:
        value = source.get("last_updated_at") if isinstance(source, dict) else None
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if parsed.tzinfo is None:
            continue
        published.append((parsed, str(value)))
    data["generated_at"] = max(published, key=lambda item: item[0])[1] if published else None
    if str(data.get("status") or "").upper() == "PARTIAL":
        data["source_status"] = "partial"
    return data


def _peek_land_summary(app_state) -> Optional[Dict[str, Any]]:
    """Land report from the planning router's TTL cache (never runs the agent)."""
    from backend.app.planning.land.api import peek_land_report

    report = peek_land_report()
    if report is None:
        return None
    data = report.model_dump()
    if str(data.get("source_status") or "").lower() == "unavailable":
        data["error"] = "Land data sources are unavailable"
    return data


#: Module -> cache-only peek. A module absent from this map has no warm-on-
#: visit cache and its card can only be populated by the coordinator report.
_MODULE_PEEKS = {
    "pm25": _peek_pm25_summary,
    "water": _peek_water_summary,
    "roads": _peek_roads_summary,
    "waste": _peek_waste_summary,
    "energy": _peek_energy_summary,
    "housing": _peek_housing_summary,
    "construction": _peek_construction_summary,
    "land": _peek_land_summary,
}


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


def _crime_incidents_from_summary(data: Dict[str, Any]) -> AlertBatch:
    """Build the module's statistics alert from its already-loaded report."""
    if str(data.get("source_status") or "").lower() == "unavailable" or data.get("error"):
        return AlertBatch.unavailable("crime")
    parts: List[str] = []
    physical = data.get("total_physical_crime_2025")
    cyber = data.get("total_scams_cybercrime_2025")
    if physical is not None:
        parts.append(f"{physical:,} physical crimes")
    if cyber is not None:
        parts.append(f"{cyber:,} scams and cybercrime")
    if not parts:
        return AlertBatch(())
    period = data.get("data_period") or "period not stated"
    return AlertBatch([{
        "domain": "crime",
        "severity": "info",
        "title": "Crime: published annual statistics",
        "description": (
            f"Police statistics ({period}): " + " and ".join(parts)
            + ". Annual published figures, not live incidents - this system "
              "has no incident-level crime feed."
        ),
        "timestamp": _alert_timestamp(data.get("generated_at")),
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

def _card_metrics_for_status(module_id: str, status: DomainStatus) -> List[ModuleMetric]:
    """The card metric list for one resolved DomainStatus.

    ``normalize_domain_report`` embeds the full metric list (extracted from
    the raw report) into ``key_metrics["metrics"]``; the coordinator's
    bespoke per-domain normalizers instead publish flat ``key_metrics``
    entries. Prefer the embedded list when present, otherwise rebuild from
    the flat entries with the same spec table - one canonical metric
    definition, never two.
    """
    key_metrics = status.key_metrics or {}
    embedded = key_metrics.get("metrics")
    if isinstance(embedded, list) and embedded:
        out: List[ModuleMetric] = []
        for m in embedded:
            if isinstance(m, dict) and m.get("key") and m.get("label") is not None:
                out.append(ModuleMetric(
                    key=str(m["key"]),
                    label=str(m["label"]),
                    value=m.get("value"),
                    unit=str(m.get("unit") or ""),
                ))
        if out:
            return out

    flat = {k: v for k, v in key_metrics.items()
            if k not in ("headline", "metrics")}
    return [
        ModuleMetric(key=str(m["key"]), label=str(m["label"]),
                     value=m.get("value"), unit=str(m.get("unit") or ""))
        for m in build_card_metrics(module_id, flat)
    ]


def _card_data_state(status: DomainStatus, metrics: List[ModuleMetric]) -> str:
    """Report measurement availability separately from assessed risk."""
    key_metrics = status.key_metrics or {}
    source_status = str(status.source_status or "").strip().lower()
    if key_metrics.get("stale") is True or source_status in {"stale", "cached_stale"}:
        return "stale"
    has_values = any(metric.value is not None for metric in metrics)
    # A Water report can retain historical metrics while live drain risk is
    # unassessed. Keep the risk unavailable and show the data as partial.
    if has_values and str(status.overall_status or "").upper() == "UNAVAILABLE":
        return "partial"
    if source_status == "partial" or key_metrics.get("partial") is True \
            or (has_values and (not status.available or status.warnings)):
        return "partial"
    if status.available and has_values:
        return "available"
    return "unavailable"


@router.get("/city", response_model=CityOverviewResponse)
async def get_overview_city(request: Request) -> CityOverviewResponse:
    """
    Load the canonical module summaries on an explicit Overview request.

    This restores the pushed data-loading path: Overview calls each module's
    existing lightweight summary fetcher, rather than requiring a prior
    detail-page visit or a full City Coordinator run. Calls are bounded and
    isolated per module. The coordinator report remains an explicit action
    and is only read here for its grounded city-level narrative/incidents.
    """
    app_state = request.app.state

    fetchers = _module_fetcher_map()
    semaphore = asyncio.Semaphore(_OVERVIEW_DOMAIN_CONCURRENCY)

    async def fetch_one(module_id: str) -> tuple[str, Dict[str, Any]]:
        try:
            provider_started = asyncio.Event()

            async def load_bounded() -> Dict[str, Any]:
                async with semaphore:
                    provider_started.set()
                    return await fetchers[module_id](app_state)

            data = await _OVERVIEW_SUMMARY_CACHE.get(
                app_state,
                module_id,
                load_bounded,
                started=provider_started,
                timeout_after_start=_OVERVIEW_DOMAIN_TIMEOUT_S,
            )
            if not isinstance(data, dict):
                return module_id, {"error": "invalid_domain_response"}
            # Preserve explicit provider unavailability. A report with no
            # records from an unavailable provider is not a NORMAL/zero report.
            if str(data.get("source_status") or "").lower() == "unavailable":
                data = {**data, "error": "source_unavailable"}
            return module_id, data
        except asyncio.TimeoutError:
            log.warning("Overview %s summary timed out", module_id)
            return module_id, {"error": "summary_timeout"}
        except Exception as exc:
            log.warning("Overview %s summary failed: %s", module_id, exc)
            return module_id, {"error": "summary_unavailable"}

    # Fetch summaries, not the City Coordinator. Semaphore bounds provider
    # pressure, and each failure only degrades its own card.
    cached = peek_city_report_cached()
    report = cached[0] if cached else None
    cached_statuses = getattr(report, "domain_status", {}) if report else {}

    # First reuse the coordinator's standardized result or an existing
    # module cache. For cold modules, restore the pushed on-demand summary
    # fetch path. This means already loaded modules cost no new requests while
    # Overview still works correctly on a cold start.
    module_data: Dict[str, Dict[str, Any]] = {}
    statuses_from_coordinator: Dict[str, DomainStatus] = {}
    missing: List[str] = []
    for module_id in CANONICAL_MODULES:
        peek_fn = _MODULE_PEEKS.get(module_id)
        try:
            peek_data = peek_fn(app_state) if peek_fn else None
        except Exception as exc:
            log.warning("Overview %s cache peek failed: %s", module_id, exc)
            peek_data = None
        if isinstance(peek_data, dict):
            module_data[module_id] = peek_data
            continue

        # Traffic's Overview card is specifically a current observed LTA
        # speed-band summary. A cached coordinator status may contain an ML
        # prediction-based or older Traffic assessment, so it cannot replace
        # this source path. The request still reuses the source/API summary
        # caches above the adapter boundary.
        if module_id == "traffic":
            missing.append(module_id)
            continue

        cached_status = cached_statuses.get(module_id)
        if cached_status is not None:
            statuses_from_coordinator[module_id] = (
                DomainStatus.model_validate(cached_status)
                if isinstance(cached_status, dict) else cached_status
            )
        elif report is not None:
            # A valid coordinator snapshot is a complete city run. Do not
            # start another set of domain workflows to fill any absent field.
            module_data[module_id] = {"error": "not_in_cached_city_report"}
        else:
            missing.append(module_id)

    # Domain calls are async wrappers around their own service/adapters.
    if missing:
        loaded = await asyncio.gather(*(fetch_one(module_id) for module_id in missing))
        module_data.update(dict(loaded))

    modules = []
    domain_status: Dict[str, DomainStatus] = {}
    for module_id in CANONICAL_MODULES:
        status = statuses_from_coordinator.get(module_id)
        if status is None:
            data = module_data.get(module_id, {"error": "summary_unavailable"})
            status = normalize_domain_report(module_id, data)
        else:
            data = {}
        domain_status[module_id] = status

        metrics = _card_metrics_for_status(module_id, status)
        headline = (status.key_metrics or {}).get("headline") or {}
        if not (isinstance(headline, dict) and {"label", "value", "unit"} <= headline.keys()):
            # Coordinator-specific normalizers publish their structured values
            # under flat key_metrics names. Select the first usable metric from
            # the same domain spec as the detail rows, so valid readings such as
            # Traffic average speed and Crime statistics are not lost merely
            # because that normalizer did not duplicate a headline object.
            headline_metric = next((m for m in metrics if m.value is not None),
                                   metrics[0] if metrics else None)
            if headline_metric is not None:
                headline = {"label": headline_metric.label,
                            "value": headline_metric.value,
                            "unit": headline_metric.unit}
        kpi = (ModuleKPI(**headline) if isinstance(headline, dict)
               and {"label", "value", "unit"} <= headline.keys() else None)

        raw_status = str(status.overall_status or "").lower()
        module_status = ({"disrupted": "high"}.get(raw_status, raw_status)
                         if raw_status in {"normal", "elevated", "critical", "disrupted"}
                         else "unavailable")
        age_seconds = (status.key_metrics or {}).get("age_seconds")

        modules.append(ModuleSummary(
            id=module_id,
            name=DOMAIN_NAMES.get(module_id, module_id.title()),
            status=module_status if status.available else "unavailable",
            kpi=kpi,
            metrics=metrics,
            updated_at=status.generated_at,
            detail_route=DOMAIN_ROUTES.get(module_id, "/"),
            data_state=_card_data_state(status, metrics),
            age_seconds=age_seconds if isinstance(age_seconds, (int, float)) and not isinstance(age_seconds, bool) else None,
        ))

    generated_at = datetime.now(SG_OFFSET).isoformat()
    assessment_ready = bool(report and build_narrative_input(report))
    ai_brief = (deterministic_summary(report) if assessment_ready else
                "City assessment not loaded. Request a city report to run cross-domain analysis.")
    cached_alerts = []
    if report:
        for incident in report.priority_incidents:
            cached_alerts.append(AlertItem(
                domain=incident.domain,
                severity=incident.severity,
                title=incident.type,
                description=incident.description,
                timestamp=report.generated_at,
                affected_zones=incident.affected_zones,
            ))

    # Preserve the established response shape and useful alerts without
    # repeating provider fetches after the module summaries have completed.
    # Domain-level risk alerts are grounded in those same structured reports.
    for module in modules:
        if module.status in ("elevated", "high", "critical"):
            data = module_data.get(module.id, {})
            cached_alerts.append(AlertItem(
                domain=module.id,
                severity=module.status,
                title=f"{module.name} Status: {module.status.capitalize()}",
                description=_generate_deterministic_module_brief(module.id, data),
                timestamp=domain_status[module.id].generated_at or generated_at,
                affected_zones=domain_status[module.id].affected_zones,
            ))

    return CityOverviewResponse(
        generated_at=generated_at,
        modules=modules,
        domain_status=domain_status,
        alerts=cached_alerts[:20],
        ai_brief=(ai_brief if assessment_ready else deterministic_summary_from_domains(domain_status)),
        city_assessment_ready=assessment_ready,
    )


@router.get("/city-narrative", response_model=CityNarrativeResponse)
async def get_city_narrative() -> CityNarrativeResponse:
    """Reconcile the City Situation against a finished coordinator report.

    This endpoint reads the cached coordinator report. It may generate optional
    narration, but it never starts a domain workflow; the full report endpoint
    is the explicit coordinator trigger.
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
        "waste": _fetch_waste_overview,
        "energy": _fetch_energy_overview,
        "land": _fetch_land_overview,
        "housing": _fetch_housing_overview,
        "construction": _fetch_construction_overview,
    }

    if module_id not in fetch_functions:
        raise HTTPException(status_code=404, detail=f"Module '{module_id}' not found")

    fetch_fn = fetch_functions[module_id]

    try:
        data = await _OVERVIEW_SUMMARY_CACHE.get(
            request.app.state, module_id, lambda: fetch_fn(request.app.state)
        )
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
        alerts = _crime_incidents_from_summary(data)

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


#: Seconds the chat route will wait for one domain's summary fetch while
#: grounding a single-domain question. Small enough that a degraded upstream
#: cannot push the total (fetch + LLM) past the frontend's 30s abort.
_CHAT_DOMAIN_FETCH_BUDGET_S = 8.0

# Overview once again loads the module summaries on demand, as the pushed
# implementation did. Keep that work bounded: the old route launched ten
# modules at once and separately fetched several of their sources a second
# time for alerts. The current route uses the same domain fetchers as module
# detail, with an explicit concurrency and per-domain time budget.
_OVERVIEW_DOMAIN_CONCURRENCY = 3
_OVERVIEW_DOMAIN_TIMEOUT_S = 10.0

#: All module ids the module-detail endpoint can fetch on demand - the
#: canonical 14-module roster, no duplicates, no legacy aliases.
_CHAT_MODULE_IDS = CANONICAL_MODULES


def _module_fetcher_map() -> Dict[str, Any]:
    """Resolve the per-module summary fetchers at call time.

    Built per call (never captured at import) so tests that patch
    ``api._fetch_<module>_overview`` intercept the chat path exactly like the
    module-detail endpoint.
    """
    return {name: globals()[f"_fetch_{name}_overview"] for name in _CHAT_MODULE_IDS}


async def _single_domain_report_for_question(
    question: str,
    module_id: Optional[str],
    app_state: Any,
) -> Optional[Any]:
    """Build a one-domain coordinator-shaped report for a chat question.

    Only ever called when no cached coordinator report exists. Never runs the
    City Coordinator: a question that names exactly one domain (or arrives
    from that module's page) is answered from that domain's own bounded
    summary - the same fetcher the module-detail endpoint uses. An ambiguous
    or unmatched question returns None and the caller answers honestly that no
    verified intelligence is available.
    """
    fetchers = _module_fetcher_map()
    domain: Optional[str] = None
    if module_id in fetchers:
        domain = module_id
    else:
        detected = detect_domains(question)
        domain = detected[0] if len(detected) == 1 else None
    if domain is None:
        return None

    try:
        data = await asyncio.wait_for(
            _OVERVIEW_SUMMARY_CACHE.get(
                app_state, domain, lambda: fetchers[domain](app_state)
            ), timeout=_CHAT_DOMAIN_FETCH_BUDGET_S
        )
    except asyncio.TimeoutError:
        log.warning("Copilot: %s summary fetch exceeded the %.1fs budget.",
                    domain, _CHAT_DOMAIN_FETCH_BUDGET_S)
        data = {"error": "summary fetch timed out"}
    except Exception as e:
        log.warning("Copilot: %s summary fetch failed: %s", domain, e)
        data = {"error": str(e)}

    from backend.app.intelligence.contracts import CitySituationReport

    status = normalize_domain_report(domain, data)
    return CitySituationReport(
        generated_at=datetime.now(SG_OFFSET).isoformat(),
        overall_city_status="UNKNOWN",
        overall_risk_level="UNKNOWN",
        confidence="low",
        domain_status={domain: status},
        limitations=[
            "Single-domain answer: the full City Coordinator assessment has not "
            "run, so cross-domain effects are outside this answer's scope.",
        ],
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, chat_request: ChatRequest) -> ChatResponse:
    """Grounded Copilot.

    Answers only from validated intelligence. The user's text and the
    retrieved evidence are both treated as untrusted data and are never
    interpolated into system instructions. Every answer is validated before
    it is returned, and a grounded deterministic fallback is used whenever the
    model cannot produce something verifiable.

    Evidence sources, in priority order, and nothing else:
      1. the *cached* coordinator report (peeked, never started here - a full
         run costs ~74s and would blow the chat latency budget);
      2. when the cache is cold, the single named domain's own bounded
         summary (the same fetcher the module-detail endpoint uses), wrapped
         in a one-domain report so the normal grounding/validation chain
         applies unchanged;
      3. no evidence -> an explicit "cannot answer" reply. Nothing is invented.
    """
    user_message = (chat_request.message or "").strip()[:MAX_QUESTION_CHARS]
    if not user_message:
        return ChatResponse(response="Please enter a question.")

    history = [
        {"role": h.role, "text": (h.text or "")[:MAX_HISTORY_CHARS]}
        for h in (chat_request.history or [])[-MAX_HISTORY_TURNS:]
    ]

    # Cache-only read of the shared coordinator report: this route must never
    # run the coordinator itself.
    try:
        cached = peek_city_report_cached()
    except Exception as e:
        log.warning("Copilot: coordinator cache read failed: %s", e)
        cached = None
    report = cached[0] if cached else None

    if report is None:
        # request may be absent in direct unit calls; production always has one.
        app_state = getattr(getattr(request, "app", None), "state", None)
        report = await _single_domain_report_for_question(
            user_message, chat_request.module_id, app_state
        )

    ctx = build_copilot_context(
        report, user_message, chat_request.module_id, history
    )
    fallback = grounded_fallback(ctx)

    ai_service = get_ai_service()
    answer, _validation = await _copilot_answer(ai_service, ctx)
    return ChatResponse(response=answer or fallback)


log.info("UrbanOS Overview API router initialized (direct service mode, no HTTP loopback).")
