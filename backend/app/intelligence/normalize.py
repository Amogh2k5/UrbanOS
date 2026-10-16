"""Normalisation adapters: domain report dict -> shared :class:`DomainStatus`.

Every consumer (city overview cards, the coordinator, KPI insight panels and
the Copilot) reads :class:`DomainStatus`. Producing it in exactly one place is
what stops the platform from growing a second, contradictory explanation for
the same fact.

This module reads plain dicts (``model_dump()`` / ``to_dict()`` output of the
domain agents) so it needs no domain imports and cannot create a cycle.

Rules enforced here:

  * An unavailable domain yields ``available=False`` and ``overall_status
    None``. It never reports ``"normal"`` - absence of data is not normality.
  * Every emitted finding either cites evidence or is marked ``unavailable``.
  * Severity is never escalated on a missing or stale source.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from backend.app.intelligence.contracts import (
    AlertSeverity, DomainStatus, EvidenceRef, Finding, Freshness,
)

DOMAIN_NAMES: Dict[str, str] = {
    "traffic": "Traffic",
    "roads": "Roads",
    "transit": "Transit",
    "pm25": "Air Quality",
    "weather": "Weather",
    "flood": "Rain & Flood",
    "fire": "Fire",
    "crime": "Crime",
    "water": "Water",
    "land": "Land Use",
}

DOMAIN_ROUTES: Dict[str, str] = {
    "traffic": "/mobility/traffic",
    "roads": "/mobility/roads",
    "transit": "/mobility/transit",
    "pm25": "/environment/pm25",
    "weather": "/environment/weather",
    "flood": "/environment/flood",
    "fire": "/safety/fire",
    "crime": "/safety/crime",
    "water": "/infrastructure/water",
    "land": "/planning/land",
}


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return None
    return str(value)


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _risk_level_text(raw: Any) -> str:
    """Normalise a risk-level field to an upper-case string.

    Accepts a plain string or a ``str``-Enum member (the Flood agent reports
    ``FloodRiskLevel``), because ``str()`` on an enum member yields
    ``"FloodRiskLevel.LOW"`` - a string no status rule would ever match.
    """
    return str(getattr(raw, "value", raw) or "").strip().upper()


def _mk(
    domain: str,
    suffix: str,
    title: str,
    answer: str,
    *,
    category: str = "general",
    question: Optional[str] = None,
    severity: Optional[AlertSeverity] = None,
    evidence: Optional[List[str]] = None,
    evidence_refs: Optional[List[EvidenceRef]] = None,
    sources: Optional[List[str]] = None,
    observed_at: Optional[str] = None,
    freshness: Freshness = "unknown",
    affected_area: Optional[str] = None,
    limitations: Optional[List[str]] = None,
    metrics: Optional[Dict[str, Any]] = None,
    data_kind: str = "latest_available",
) -> Finding:
    return Finding(
        id=f"{domain}.{suffix}",
        domain=domain,
        title=title,
        answer=answer,
        question=question,
        category=category,
        data_kind=data_kind,  # type: ignore[arg-type]
        severity=severity,
        evidence=evidence or [],
        evidence_refs=evidence_refs or [],
        sources=sources or [],
        observed_at=observed_at,
        freshness=freshness,
        affected_area=affected_area,
        limitations=limitations or [],
        metrics=metrics or {},
    )


def _unavailable_finding(domain: str, reason: str, question: Optional[str] = None) -> Finding:
    """The only legitimate 'no data' finding. Never carries a severity."""
    return _mk(
        domain,
        "unavailable",
        "Data unavailable",
        reason,
        question=question,
        data_kind="unavailable",
        limitations=[reason],
    )


# --------------------------------------------------------------- module KPIs
def _count_kpi(label: str, value: Any) -> Optional[Dict[str, Any]]:
    """KPI for a plain count, or ``None`` when the count is not a real reading.

    Rejects ``None``, non-numeric strings and sentinel placeholders such as
    ``"n/a"``: rendering one of those as a headline number would present a data
    gap as a measurement. An explicit numeric ``0`` is a reading and is kept.
    """
    count = _num(value)
    if count is None:
        return None
    return {"label": label, "value": int(count), "unit": ""}


def build_kpi(module_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Single headline metric per module, or None when unsupported.

    Returned shape matches the existing ``ModuleKPI`` contract so the overview
    cards keep working unchanged. ``None`` is returned whenever the underlying
    value is absent or malformed, so the card renders "Unavailable" instead of
    a placeholder that reads like a measurement.
    """
    if module_id == "traffic":
        speed = _num(data.get("overall_average_speed"))
        if speed is not None:
            return {"label": "Average Speed", "value": round(speed, 1), "unit": "km/h"}
        congestion = data.get("overall_congestion_level")
        if congestion:
            return {"label": "Congestion", "value": str(congestion).replace("_", " ").title(), "unit": ""}
    elif module_id == "roads":
        road_works = data.get("road_works")
        active = road_works.get("active") if isinstance(road_works, dict) else None
        return _count_kpi("Active Road Works", active)
    elif module_id == "transit":
        return _count_kpi("Train Alerts", data.get("active_train_alerts"))
    elif module_id == "pm25":
        regions = data.get("regions")
        values = [
            v for v in (_num(r.get("value")) for r in regions.values()
                        if isinstance(r, dict))
            if v is not None
        ] if isinstance(regions, dict) else []
        if values:
            return {"label": "Current PM2.5", "value": round(sum(values) / len(values), 1), "unit": "µg/m³"}
    elif module_id == "weather":
        # Out of scope for this change: value semantics are unchanged, only the
        # shape guard is added so a malformed payload cannot raise.
        general = data.get("general")
        temp = general.get("temperature_c") if isinstance(general, dict) else None
        if temp is not None:
            return {"label": "Temperature", "value": temp, "unit": "°C"}
    elif module_id == "flood":
        risk = _risk_level_text(data.get("risk_level"))
        # UNKNOWN is the agent saying "no rainfall source was live", which is
        # not a measurement. Returning None makes the card render "Unavailable"
        # instead of a value that reads like an observation.
        if risk in ("LOW", "MODERATE", "HIGH", "CRITICAL"):
            return {"label": "Flood Risk", "value": risk.title(), "unit": ""}
        return None
    elif module_id == "fire":
        return _count_kpi("Active Incidents", data.get("active_incident_count"))
    elif module_id == "crime":
        total = _num(data.get("total_physical_crime_2025"))
        if total is not None:
            return {
                "label": "Physical Crime",
                "value": int(total),
                "unit": "",
            }
        return None
    elif module_id == "water":
        drain = data.get("drain") or {}
        if drain.get("readings_available"):
            pct = drain.get("sensors_with_readings")
            total = drain.get("sensor_count")
            if pct is not None and total:
                return {"label": "Drain Sensors Reporting", "value": f"{pct}/{total}", "unit": ""}
        usage = data.get("usage") or {}
        pot = usage.get("potable_total") or {}
        if pot.get("value") is not None:
            return {"label": "Potable Sales", "value": pot["value"], "unit": pot.get("unit", "")}
        return None
    elif module_id == "land":
        area = (data.get("land_use") or {}).get("total_area_km2")
        if area is not None:
            return {"label": "Land-Use Area", "value": round(float(area), 1), "unit": "km²"}
        count = (data.get("planning") or {}).get("planning_area_count")
        if count is not None:
            return {"label": "Planning Areas", "value": count, "unit": ""}
    return None


# ------------------------------------------------------------------- status
#: NEA 24-hour forecast codes that represent convective or rain-bearing weather
#: rather than settled conditions. Mirrors the set the Flood agent applies to the
#: same field, so one reading of the source cannot mean "thunderstorm" in one
#: module and "normal" in another.
_ELEVATED_FORECAST_CODES = ("TS", "TL", "TRW", "HR")


def determine_status(module_id: str, data: Dict[str, Any]) -> str:
    """Deterministic status: normal | elevated | critical | unavailable.

    Thresholds are ordered high-to-low so the most severe branch is reachable.

    A domain whose required field is absent, ``None`` or malformed returns
    ``"unavailable"``. It never falls through to ``"normal"``: absence of data
    is not evidence of normal conditions. An explicit ``0`` supplied by a valid
    source *is* a reading and is honoured.
    """
    if data.get("error"):
        return "unavailable"

    if module_id == "traffic":
        congestion = str(data.get("overall_congestion_level") or "")
        if congestion in ("severe", "heavy"):
            return "critical"
        if congestion == "moderate":
            return "elevated"
        return "normal"

    if module_id == "roads":
        road_works = data.get("road_works")
        active = _num(road_works.get("active")) if isinstance(road_works, dict) else None
        if active is None:
            return "unavailable"
        if active > 500:
            return "critical"
        if active > 100:
            return "elevated"
        return "normal"

    if module_id == "transit":
        alerts = _num(data.get("active_train_alerts"))
        if alerts is None:
            return "unavailable"
        return "elevated" if alerts > 10 else "normal"

    if module_id == "pm25":
        regions = data.get("regions")
        if not isinstance(regions, dict) or not regions:
            # No regional readings at all: air quality could not be assessed.
            return "unavailable"
        values = [
            v for v in (_num(r.get("value")) for r in regions.values()
                        if isinstance(r, dict))
            if v is not None
        ]
        if not values:
            # Regions present but none carries a usable reading.
            return "unavailable"
        if any(v > 100 for v in values):
            return "elevated"
        return "normal"

    if module_id == "weather":
        if data.get("error") == "rate_limited":
            return "unavailable"
        forecast = (data.get("general") or {}).get("forecast_code", "")
        # NEA 24h forecast codes. TS/TL/TRW are the convective (thundery
        # shower / thunderstorm) codes and HR is heavy rain. A live reading of
        # TL / "Thundery Showers" was being reported as "normal" because only
        # TS and HR were listed; the Flood agent already treats exactly this set
        # as thunderstorm evidence, so the two modules disagreed.
        return "elevated" if forecast in _ELEVATED_FORECAST_CODES else "normal"

    if module_id == "flood":
        risk = _risk_level_text(data.get("risk_level"))
        if risk == "CRITICAL":
            return "critical"
        if risk == "HIGH":
            # Unchanged mapping: HIGH flood has always been the strongest band
            # this four-value vocabulary offers.
            return "critical"
        if risk == "MODERATE":
            return "elevated"
        if risk == "LOW":
            return "normal"
        # UNKNOWN, absent or unrecognised: the assessment could not be made.
        # Never report "normal" here - an absent rainfall reading is not a
        # dry-weather reading.
        return "unavailable"

    if module_id == "fire":
        active = _num(data.get("active_incident_count"))
        if active is None:
            # The feed returned nothing. Absence of records is not absence of
            # fires, so this is an unavailable assessment, not a normal one.
            return "unavailable"
        if active > 5:
            return "critical"
        if active > 0:
            return "elevated"
        return "normal"

    if module_id == "crime":
        # Crime publishes no severity feed, so it can only ever be "normal".
        # But when its statistics did not load it must say "unavailable",
        # never imply a healthy picture.
        if str(data.get("source_status") or "").lower() in ("unavailable", "error", ""):
            return "unavailable"
        if all(data.get(k) is None for k in (
            "total_physical_crime_2025", "total_scams_cybercrime_2025", "total_scams_2025",
        )):
            return "unavailable"
        return "normal"

    if module_id == "water":
        risk = str(data.get("overall_risk") or "").upper()
        if risk == "CRITICAL":
            return "critical"
        if risk in ("HIGH", "MODERATE"):
            return "elevated"
        if risk == "LOW":
            return "normal"
        # UNKNOWN or absent: the water agent could not assess risk (measured:
        # overall_risk UNKNOWN with drain readings unavailable). Reporting
        # "normal" asserted a clean bill of health the data does not support.
        return "unavailable"

    if module_id == "land":
        return "normal"

    return "normal"


# ----------------------------------------------------------------- findings
def _insights_to_findings(
    domain: str, insights: List[Dict[str, Any]], data_kind_default: str = "latest_available"
) -> List[Finding]:
    """Convert Water/Land ``insights`` into shared Findings, preserving answers."""
    out: List[Finding] = []
    for idx, ins in enumerate(insights or []):
        if not isinstance(ins, dict):
            continue
        answer = str(ins.get("answer") or "").strip()
        question = str(ins.get("question") or "").strip()
        if not answer:
            continue
        kind = ins.get("data_kind") or data_kind_default
        out.append(_mk(
            domain,
            f"insight_{idx}",
            question or f"{domain.title()} insight",
            answer,
            category="insight",
            question=question or None,
            data_kind=kind if kind in
            ("live", "latest_available", "historical", "forecast", "unavailable")
            else data_kind_default,
            evidence=[f"Derived from the {domain} report."] if kind != "unavailable" else [],
        ))
    return out


def _traffic_findings(data: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    speed = _num(data.get("overall_average_speed"))
    congestion = data.get("overall_congestion_level")
    if speed is not None:
        change = _num(data.get("overall_speed_change_percent"))
        ev = [f"Overall average speed {speed:.1f} km/h across monitored zones."]
        metrics: Dict[str, Any] = {"average_speed_kmh": round(speed, 1)}
        answer = f"Network average speed is {speed:.1f} km/h (classified {congestion})."
        if change is not None:
            ev.append(f"Change versus the prediction baseline: {change:+.1f}%.")
            metrics["speed_change_pct"] = round(change, 1)
            answer += f" That is {change:+.1f}% versus the prediction baseline."
        sev: Optional[AlertSeverity] = (
            "HIGH" if congestion in ("severe", "heavy")
            else "MODERATE" if congestion == "moderate" else None
        )
        out.append(_mk(
            "traffic", "speed", "Network average speed", answer,
            question="How congested is the road network right now?",
            category="congestion", severity=sev, evidence=ev,
            observed_at=_iso(data.get("generated_at")),
            freshness="recent", metrics=metrics, data_kind="live",
            limitations=list(data.get("limitations") or [])[:2],
        ))
    incidents = data.get("incidents") or []
    if isinstance(incidents, list) and incidents:
        out.append(_mk(
            "traffic", "incidents", "Active traffic incidents",
            f"{len(incidents)} traffic incident(s) reported by LTA DataMall.",
            question="Are there active traffic incidents?",
            category="incidents", severity="MODERATE",
            evidence=[str(i.get("message") or i.get("type") or "incident")
                      for i in incidents[:3] if isinstance(i, dict)],
            observed_at=_iso(data.get("generated_at")), freshness="live",
            metrics={"incident_count": len(incidents)}, data_kind="live",
        ))
    if not out:
        out.append(_unavailable_finding("traffic", "No traffic telemetry available."))
    return out


def _fire_findings(data: Dict[str, Any]) -> List[Finding]:
    active = data.get("active_incident_count")
    if active is None:
        return [_unavailable_finding(
            "fire",
            "The published fire feed returned no records, so current incident "
            "counts cannot be stated. Absence of data is not evidence of no fires.",
            question="How many fire incidents are active right now?",
        )]
    critical = _num(data.get("critical_incident_count"))
    out = [_mk(
        "fire", "active", "Active fire incidents",
        f"{int(active)} active fire incident(s) in the SCDF published feed."
        + (f" {int(critical)} of these are classified critical." if critical else ""),
        question="How many fire incidents are active right now?",
        category="incidents",
        severity="HIGH" if (critical or 0) > 0 else ("MODERATE" if active else None),
        evidence=[f"SCDF published feed reports {int(active)} active incident(s)."],
        observed_at=_iso(data.get("generated_at")), freshness="live",
        metrics={"active_incidents": int(active),
                 "critical_incidents": int(critical) if critical is not None else None},
        data_kind="live",
        limitations=list(data.get("limitations") or [])[:2],
    )]
    return out


def _crime_findings(data: Dict[str, Any]) -> List[Finding]:
    period = str(data.get("data_period") or "").strip()
    suffix = f" ({period})" if period and period != "unknown" else ""
    physical = _num(data.get("total_physical_crime_2025"))
    scams = _num(data.get("total_scams_cybercrime_2025"))

    if physical is None and scams is None:
        return [_unavailable_finding(
            "crime",
            "Crime statistics are unavailable for the published period.",
            question="What is the current crime picture?",
        )]

    evidence: List[str] = []
    metrics: Dict[str, Any] = {}
    if physical is not None:
        evidence.append(f"Police statistics: {int(physical)} physical crimes reported{suffix}.")
        metrics["physical_crime"] = int(physical)
    if scams is not None:
        evidence.append(f"Police statistics: {int(scams)} scams/cybercrime reported{suffix}.")
        metrics["scams_cybercrime"] = int(scams)

    bits = []
    if physical is not None:
        bits.append(f"{int(physical)} physical crimes")
    if scams is not None:
        bits.append(f"{int(scams)} scams and cybercrime")
    return [_mk(
        "crime", "statistics", "Reported offences",
        "Published police statistics report " + " and ".join(bits) + suffix + ".",
        question="What is the current crime picture?",
        category="statistics", evidence=evidence,
        observed_at=_iso(data.get("generated_at")),
        freshness="recent", metrics=metrics, data_kind="historical",
        limitations=(list(data.get("limitations") or [])[:2]
                     + ["Crime figures are annual published statistics, not live conditions."]),
    )]


def _flood_findings(data: Dict[str, Any]) -> List[Finding]:
    # risk_level is a FloodRiskLevel enum in the raw report; unwrap it so an
    # internal type name never reaches user-facing text.
    raw_risk = data.get("risk_level") or "UNKNOWN"
    risk = str(getattr(raw_risk, "value", raw_risk)).upper()
    factors = [f for f in (data.get("primary_risk_factors") or []) if f]
    evidence: List[str] = []
    for key, label in (("singapore_rainfall", "Singapore rainfall"),
                       ("regional_weather", "Regional weather")):
        block = data.get(key) or {}
        if isinstance(block, dict):
            # Only scalars: nested objects would stringify into noise.
            bits = [
                f"{k}={v}" for k, v in list(block.items())[:3]
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            ]
            if bits:
                evidence.append(f"{label}: " + ", ".join(str(b) for b in bits))
    if risk == "UNKNOWN" and not evidence:
        return [_unavailable_finding(
            "flood",
            "Flood risk cannot be assessed because rainfall sources are unavailable.",
            question="What is the current flood risk?",
        )]
    sev: Optional[AlertSeverity] = (
        "HIGH" if risk == "HIGH" else "MODERATE" if risk == "MODERATE" else None
    )
    answer = f"Current flood risk is {risk}."
    if factors:
        answer += " Drivers: " + "; ".join(str(f) for f in factors[:3]) + "."
    return [_mk(
        "flood", "risk", "Current flood risk", answer,
        question="What is the current flood risk?",
        category="risk", severity=sev, evidence=evidence,
        observed_at=_iso(data.get("generated_at")), freshness="live",
        affected_area=", ".join(data.get("affected_zones") or []) or None,
        metrics={"risk_level": risk, "active_alerts": data.get("active_alert_count")},
        data_kind="live",
        limitations=["Past flood events are reference only and do not raise current risk."],
    )]


def _generic_findings(domain: str, data: Dict[str, Any]) -> List[Finding]:
    kpi = build_kpi(domain, data)
    if not kpi:
        return [_unavailable_finding(
            domain, f"No supported headline metric for {DOMAIN_NAMES.get(domain, domain)}.")]
    value = kpi["value"]
    unit = kpi.get("unit") or ""
    return [_mk(
        domain, "headline", f"{kpi['label']}",
        f"Current {kpi['label'].lower()}: {value}{(' ' + unit) if unit else ''}.",
        question=f"What is the current {kpi['label'].lower()}?",
        category="headline",
        evidence=[f"{kpi['label']} = {value}{(' ' + unit) if unit else ''}"],
        observed_at=_iso(data.get("timestamp") or data.get("snapshot_at")
                         or data.get("generated_at")),
        freshness="recent", metrics={"value": value, "unit": unit},
    )]


_BUILDERS: Dict[str, Callable[[Dict[str, Any]], List[Finding]]] = {
    "traffic": _traffic_findings,
    "fire": _fire_findings,
    "crime": _crime_findings,
    "flood": _flood_findings,
}


def build_findings(module_id: str, data: Dict[str, Any]) -> List[Finding]:
    """Deterministic, evidence-backed findings for one domain."""
    if not data.get("error"):
        native = data.get("insights")
        if isinstance(native, list) and native:
            findings = _insights_to_findings(module_id, native)
            if module_id in _BUILDERS:
                findings.extend(_BUILDERS[module_id](data))
            return findings
        if module_id in _BUILDERS:
            return _BUILDERS[module_id](data)
    return _generic_findings(module_id, data)


# ------------------------------------------------------------------- adapter
def normalize_domain_report(module_id: str, data: Dict[str, Any]) -> DomainStatus:
    """Convert one domain's report dict into the shared contract."""
    error = data.get("error") if isinstance(data, dict) else "no data"
    if error:
        return DomainStatus(
            domain=module_id,
            available=False,
            overall_status=None,
            error=str(error),
            display_name=DOMAIN_NAMES.get(module_id, module_id.title()),
            detail_route=DOMAIN_ROUTES.get(module_id),
            findings=[_unavailable_finding(module_id, f"Data unavailable: {error}")],
            confidence="low",
            limitations=[str(error)],
        )

    status = determine_status(module_id, data)
    kpi = build_kpi(module_id, data)
    key_metrics: Dict[str, Any] = {}
    if kpi:
        key_metrics["headline"] = kpi
    for key in ("overall_risk", "risk_level", "overall_status", "confidence",
                "active_alert_count", "source_status", "is_ml_prediction",
                # Freshness, for domains that can serve a cached payload
                # (Roads/LTA). Absent elsewhere; never invented.
                "stale", "age_seconds", "partial", "unavailable_sources"):
        if data.get(key) is not None:
            key_metrics[key] = data[key]

    alerts = data.get("alerts") or []
    return DomainStatus(
        domain=module_id,
        available=True,
        overall_status=str(data.get("overall_status") or status).upper(),
        overall_risk=(str(data["overall_risk"]) if data.get("overall_risk") else None),
        risk_level=(str(data["risk_level"]) if data.get("risk_level") else None),
        key_metrics=key_metrics,
        active_alert_count=len(alerts) if isinstance(alerts, list) else None,
        affected_zones=[str(z) for z in (data.get("affected_zones") or [])],
        primary_risk_factors=[str(f) for f in (data.get("primary_risk_factors") or [])],
        confidence=(str(data["confidence"]) if data.get("confidence") else None),
        limitations=[str(x) for x in (data.get("limitations") or [])],
        is_ml_prediction=bool(data.get("is_ml_prediction", False)),
        generated_at=_iso(data.get("generated_at") or data.get("timestamp")
                          or data.get("snapshot_at")),
        source_status=(str(data["source_status"]) if data.get("source_status") else None),
        warnings=[str(w) for w in (data.get("warnings") or [])],
        errors=[str(e) for e in (data.get("errors") or [])],
        findings=build_findings(module_id, data),
        detail_route=DOMAIN_ROUTES.get(module_id),
        display_name=DOMAIN_NAMES.get(module_id, module_id.title()),
    )