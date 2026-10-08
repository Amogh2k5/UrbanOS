"""Deterministic Water processing: analytics, drain classification, alerts.

Everything here is a pure function of the acquired data. There is no ML model:
the only official usage data is annual (<= 18 points), which cannot support a
chronological train/validation/test split or a credible model - see
``build_forecast_section``.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Dict, List, Optional, Protocol, Sequence

from backend.app.infrastructure.water.models import (
    AnnualPoint, AnnualSeries, DrainCondition, DrainReading, DrainSection, DrainSensor,
    DrainSensorStatus, ForecastSection, Indicator, NEWaterSection, QualityParameter,
    QualitySection, SupplySection, Trend, UsageSection, WaterAlert,
)
from backend.app.infrastructure.water.sources import (
    WaterSnapshot, _parse_range, normalize_unit, parse_number,
)

# ------------------------------------------------------------------ helpers
YOY_ALERT_PCT = 5.0  # statistical flag only; not an official PUB threshold
MIN_OBSERVATIONS_FOR_ML = 48  # e.g. 4 years of monthly data; annual data never reaches this
TREND_STABLE_PP = 2.0  # percentage points


def _round(x: Optional[float], nd: int = 1) -> Optional[float]:
    return None if x is None else round(x, nd)


def pct_change(new: Optional[float], old: Optional[float]) -> Optional[float]:
    if new is None or old is None or old == 0:
        return None
    return (new - old) / old * 100.0


def cagr_pct(first: Optional[float], last: Optional[float], years: int) -> Optional[float]:
    if first is None or last is None or first <= 0 or last <= 0 or years <= 0:
        return None
    return ((last / first) ** (1.0 / years) - 1.0) * 100.0


def latest_two(row: Dict[int, Optional[float]]) -> tuple:
    """(latest_year, latest_value, prev_year, prev_value) using only non-null points."""
    valid = sorted((y, v) for y, v in row.items() if v is not None)
    if not valid:
        return None, None, None, None
    ly, lv = valid[-1]
    py, pv = valid[-2] if len(valid) > 1 else (None, None)
    return ly, lv, py, pv


def make_series(key: str, label: str, row: Dict[int, Optional[float]], source_key: str, unit: str = "million m3", kind: str = "historical") -> AnnualSeries:
    return AnnualSeries(
        key=key, label=label, unit=unit, data_kind=kind, source_key=source_key,  # type: ignore[arg-type]
        points=[AnnualPoint(year=y, value=row[y]) for y in sorted(row)],
    )


def make_indicator(key: str, label: str, row: Dict[int, Optional[float]], source_key: str, unit: str = "million m3") -> Optional[Indicator]:
    ly, lv, py, pv = latest_two(row)
    if ly is None:
        return None
    return Indicator(
        key=key, label=label, value=lv, unit=unit, period=str(ly),
        previous_value=pv, previous_period=None if py is None else str(py),
        change_abs=_round(None if pv is None else lv - pv, 2),
        change_pct=_round(pct_change(lv, pv), 2),
        data_kind="latest_available", source_key=source_key,
    )


def _merge(primary: Dict[int, Optional[float]], fallback: Dict[int, float]) -> Dict[int, Optional[float]]:
    """Primary (recent) dataset wins; the longer dataset fills earlier years."""
    merged: Dict[int, Optional[float]] = dict(fallback)
    for y, v in primary.items():
        if v is not None or y not in merged:
            merged[y] = v
    return merged


# ------------------------------------------------------------------- usage
def build_usage_section(snap: WaterSnapshot) -> UsageSection:
    sales = snap.sales
    sec = UsageSection(resolution="annual")
    sec.limitations.append(
        "Official water-sales data is annual; there is no daily or monthly official usage series "
        "in the sources used. Values are volumes SOLD by PUB, used as the usage measure."
    )
    dom = _merge(sales.get("domestic", {}), snap.potable.get("domestic", {}))
    non = _merge(sales.get("non_domestic", {}), snap.potable.get("non_domestic", {}))
    total = dict(sales.get("potable_total", {}))
    # Derive total only where the source total is missing and both parts exist.
    for y in set(dom) & set(non):
        if total.get(y) is None and dom[y] is not None and non[y] is not None:
            total[y] = round(dom[y] + non[y], 1)

    if not (dom or non or total):
        sec.data_kind = "unavailable"
        sec.limitations.append("No usable water-sales rows were acquired.")
        return sec

    sec.potable_total = make_indicator("potable_total", "Potable water sales (total)", total, "water_sales_annual")
    sec.domestic = make_indicator("domestic", "Domestic potable water", dom, "water_sales_annual")
    sec.non_domestic = make_indicator("non_domestic", "Non-domestic potable water", non, "water_sales_annual")
    sec.series = [
        make_series("potable_total", "Potable water sales (total)", total, "water_sales_annual"),
        make_series("domestic", "Domestic potable water", dom, "potable_annual"),
        make_series("non_domestic", "Non-domestic potable water", non, "potable_annual"),
    ]
    if sec.potable_total:
        sec.latest_year = int(sec.potable_total.period) if sec.potable_total.period else None
    if sec.domestic and sec.non_domestic and sec.domestic.period == sec.non_domestic.period:
        parts = (sec.domestic.value or 0) + (sec.non_domestic.value or 0)
        if parts > 0:
            sec.domestic_share_pct = _round(sec.domestic.value / parts * 100, 1)
            sec.non_domestic_share_pct = _round(sec.non_domestic.value / parts * 100, 1)
    if 2015 in total and sec.latest_year and total.get(2015) and total.get(sec.latest_year):
        sec.cagr_pct_since_2015 = _round(cagr_pct(total[2015], total[sec.latest_year], sec.latest_year - 2015), 2)

    # Cross-check: domestic + non-domestic should reproduce the total (rounding tolerance 1.0).
    for y in sorted(set(dom) & set(non) & set(total)):
        if None in (dom[y], non[y], total[y]):
            continue
        if abs(dom[y] + non[y] - total[y]) > 1.0:
            sec.consistency_warnings.append(
                f"{y}: domestic ({dom[y]}) + non-domestic ({non[y]}) differs from total ({total[y]})"
            )
    return sec


def build_forecast_section(usage: UsageSection) -> ForecastSection:
    n = 0
    if usage.series:
        n = sum(1 for p in usage.series[0].points if p.value is not None)
    return ForecastSection(
        available=False,
        data_kind="unavailable",
        observations=n,
        frequency="annual",
        minimum_observations_required=MIN_OBSERVATIONS_FOR_ML,
        reason=(
            f"Only {n} annual observations are available from the official sources. A chronological "
            f"train/validation/test split with a baseline comparison needs far more history (this module "
            f"requires at least {MIN_OBSERVATIONS_FOR_ML} observations, e.g. four years of monthly data). "
            "No official daily or monthly water-usage dataset was found, so usage is shown as analytics "
            "(latest value, year-on-year change, trend) rather than as an unreliable forecast."
        ),
    )


# ----------------------------------------------------------------- newater
def build_newater_section(snap: WaterSnapshot) -> NEWaterSection:
    recent = snap.sales.get("newater", {})
    merged = _merge(recent, snap.newater_long)
    sec = NEWaterSection(data_kind="historical")
    sec.limitations.append(
        "NEWater figures are annual sales volumes, not live measurements, and are not a forecast."
    )
    if not merged:
        sec.data_kind = "unavailable"
        return sec
    sec.latest = make_indicator("newater", "NEWater sales", merged, "water_sales_annual")
    sec.series = [make_series("newater", "NEWater sales", merged, "water_sales_annual")]
    if sec.latest and sec.latest.period and merged.get(2015) and merged.get(int(sec.latest.period)):
        sec.cagr_pct_since_2015 = _round(
            cagr_pct(merged[2015], merged[int(sec.latest.period)], int(sec.latest.period) - 2015), 2
        )
    sec.share_of_water_sales_pct = share_of_water_sales(snap)
    if sec.share_of_water_sales_pct is not None:
        pot, new = snap.sales.get("potable_total", {}), snap.sales.get("newater", {})
        ys = sorted(y for y in set(pot) & set(new) if pot.get(y) is not None and new.get(y) is not None)
        if ys and snap.sales.get("industrial", {}).get(ys[-1]) is None:
            sec.limitations.append(
                f"NEWater share for {ys[-1]} is of potable + NEWater sales only: industrial water sales "
                "are reported as 'na' for that year."
            )
    sec.long_run_source_note = (
        "Years before 2015 come from PUB's 'Volume of NEWater sold, Annual' dataset (2007-2025); "
        "2015 onward come from 'Water Sales, Annual'. Where both overlap, Water Sales wins."
    )
    return sec


def share_of_water_sales(snap: WaterSnapshot) -> Optional[float]:
    """NEWater as % of (potable + NEWater + industrial) sales for the latest year all three exist.

    Industrial water is reported 'na' for recent years; when it is missing we use potable+NEWater
    only and the caller labels that in the UI. Returns None if potable or NEWater is missing.
    """
    pot = snap.sales.get("potable_total", {})
    new = snap.sales.get("newater", {})
    ind = snap.sales.get("industrial", {})
    years = sorted(y for y in set(pot) & set(new) if pot.get(y) is not None and new.get(y) is not None)
    if not years:
        return None
    y = years[-1]
    denom = pot[y] + new[y] + (ind.get(y) or 0.0)
    return _round(new[y] / denom * 100, 1) if denom > 0 else None


# ------------------------------------------------------------------ supply
def build_supply_section(snap: WaterSnapshot, usage: UsageSection, newater: NEWaterSection) -> SupplySection:
    sec = SupplySection()
    sec.limitations.append(
        "These are annual water SALES indicators. They describe supply-side volumes delivered, "
        "not reservoir storage or real-time availability."
    )
    indicators: List[Indicator] = []
    if usage.potable_total:
        indicators.append(usage.potable_total)
    if newater.latest:
        indicators.append(newater.latest)
    ind = make_indicator("industrial", "Industrial water sales", snap.sales.get("industrial", {}), "water_sales_annual")
    if ind:
        indicators.append(ind)
        latest_industrial_year = ind.period
        all_years = [int(i.period) for i in indicators if i.period]
        if latest_industrial_year and all_years and int(latest_industrial_year) < max(all_years):
            sec.limitations.append(
                f"Industrial water sales are reported as 'na' after {latest_industrial_year}; "
                "the last reported value is shown with its year."
            )
    sec.indicators = indicators
    sec.series = [s for s in (usage.series[:1] + newater.series) if s.points]
    sec.newater_share_of_water_sales_pct = newater.share_of_water_sales_pct
    if indicators:
        sec.status = "SALES_DATA_ONLY"
        sec.data_kind = "latest_available"
        sec.period = max((i.period for i in indicators if i.period), default=None)
    else:
        sec.status = "UNAVAILABLE"
        sec.data_kind = "unavailable"
    return sec


# ----------------------------------------------------------------- quality
# Limits from PUB's published drinking-water-quality table (EPH regulations).
_LIMITS = {
    "ph": ("6.5 - 9.5", 6.5, 9.5),
    "turbidity": ("<= 5 NTU", None, 5.0),
    "colour": ("<= 15 Hazen", None, 15.0),
}


def _evaluate(key: str, avg_text: Optional[str], rng_text: Optional[str]) -> tuple:
    if key == "ecoli":
        # Limit is "not detected" (<1 cfu/100 mL). A reported '<1' average and range is within limit.
        texts = [t for t in (avg_text, rng_text) if t]
        if texts and all(t.replace(" ", "").startswith("<1") for t in texts):
            return "<1 cfu/100mL", "WITHIN_LIMIT"
        return "<1 cfu/100mL", "UNKNOWN" if not texts else "EXCEEDS_LIMIT"
    if key in _LIMITS:
        label, lo_lim, hi_lim = _LIMITS[key]
        lo, hi = _parse_range(rng_text)
        avg = parse_number((avg_text or "").lstrip("<>≤≥ "))
        if hi is None and avg is None:
            return label, "UNKNOWN"
        observed_hi = hi if hi is not None else avg
        observed_lo = lo if lo is not None else avg
        if (hi_lim is not None and observed_hi is not None and observed_hi > hi_lim) or (
            lo_lim is not None and observed_lo is not None and observed_lo < lo_lim
        ):
            return label, "EXCEEDS_LIMIT"
        return label, "WITHIN_LIMIT"
    return None, "NO_LIMIT_PUBLISHED"


def build_quality_section(snap: WaterSnapshot) -> QualitySection:
    sec = QualitySection()
    q = snap.quality or {}
    rows = q.get("rows") or []
    if not q.get("year") or not rows:
        sec.data_kind = "unavailable"
        sec.limitations.append("Drinking-water quality dataset unavailable.")
        return sec
    sec.reporting_period = f"Calendar year {q['year']}"
    sec.other_parameter_count = int(q.get("other_count", 0))
    order = ["ecoli", "ph", "turbidity", "conductivity", "tds", "colour"]
    for row in sorted(rows, key=lambda r: order.index(r["key"]) if r["key"] in order else 99):
        lo, hi = _parse_range(row.get("range"))
        limit, compliance = _evaluate(row["key"], row.get("average"), row.get("range"))
        sec.parameters.append(
            QualityParameter(
                key=row["key"], parameter=row["name"], unit=normalize_unit(row.get("unit")),
                average=row.get("average"), average_value=parse_number((row.get("average") or "").lstrip("<>≤≥ ")),
                range=row.get("range"), range_min=lo, range_max=hi,
                regulatory_limit=limit, compliance=compliance,  # type: ignore[arg-type]
            )
        )
    sec.limitations.append(
        "Annual average and range of PUB's drinking-water quality monitoring. These are periodic "
        "summaries, not real-time sensor readings."
    )
    return sec


# ------------------------------------------------------------------- drain
# PUB's public water-level-sensor map legend: 0-75% full = low, 76-90% = moderate, 91-100% = high
# flood risk. CRITICAL (>100%, i.e. above the reference depth) is this module's extension.
DRAIN_THRESHOLDS = {
    "NORMAL": "0-75% full (PUB: low flood risk)",
    "ELEVATED": "76-90% full (PUB: moderate flood risk)",
    "HIGH": "91-100% full (PUB: high flood risk)",
    "CRITICAL": ">100% of reference depth (module extension; not a PUB-published band)",
}
DRAIN_THRESHOLD_SOURCE = "PUB 'Water Level Sensors & CCTVs' map legend (app.pub.gov.sg/waterlevel)"


def compute_percentage(water_level_m: Optional[float], reference_depth_m: Optional[float]) -> Optional[float]:
    """Percent full. Returns None for invalid inputs (negative level, non-positive depth, NaN)."""
    if water_level_m is None or reference_depth_m is None:
        return None
    if not (math.isfinite(water_level_m) and math.isfinite(reference_depth_m)):
        return None
    if water_level_m < 0 or reference_depth_m <= 0:
        return None
    return water_level_m / reference_depth_m * 100.0


def classify_drain_condition(percentage: Optional[float]) -> DrainCondition:
    if percentage is None or not math.isfinite(percentage) or percentage < 0:
        return "UNAVAILABLE"
    if percentage <= 75:
        return "NORMAL"
    if percentage <= 90:
        return "ELEVATED"
    if percentage <= 100:
        return "HIGH"
    return "CRITICAL"


def compute_trend(pcts: Sequence[float]) -> Trend:
    """Trend from chronologically ordered percentages (oldest -> newest)."""
    if len(pcts) < 2:
        return "unknown"
    delta = pcts[-1] - pcts[0]
    if delta > TREND_STABLE_PP:
        return "rising"
    if delta < -TREND_STABLE_PP:
        return "falling"
    return "stable"


class DrainReadingProvider(Protocol):
    """Implement this if/when PUB publishes official live readings."""

    def fetch(self) -> List[DrainReading]: ...


def build_drain_section(
    sensors: List[DrainSensor],
    invalid_sensor_records: int = 0,
    readings: Optional[List[DrainReading]] = None,
    sensors_source_ok: bool = True,
) -> DrainSection:
    sec = DrainSection(thresholds=DRAIN_THRESHOLDS, threshold_source=DRAIN_THRESHOLD_SOURCE)
    sec.sensor_count = len(sensors)
    sec.sensor_locations_available = bool(sensors)
    sec.invalid_sensor_records = invalid_sensor_records
    by_sensor: Dict[str, List[DrainReading]] = {}
    for r in readings or []:
        by_sensor.setdefault(r.sensor_id, []).append(r)

    statuses: List[DrainSensorStatus] = []
    counts: Dict[str, int] = {}
    latest_at: Optional[datetime] = None
    for s in sensors:
        hist = sorted(by_sensor.get(s.id, []), key=lambda r: r.observed_at)
        st = DrainSensorStatus(sensor=s)
        valid = [(r, compute_percentage(r.water_level_m, r.reference_depth_m)) for r in hist]
        valid = [(r, p) for r, p in valid if p is not None]
        if valid:
            last, pct = valid[-1]
            st.water_level_m, st.reference_depth_m = last.water_level_m, last.reference_depth_m
            st.percentage, st.observed_at = round(pct, 1), last.observed_at
            st.condition = classify_drain_condition(pct)
            st.trend = compute_trend([p for _, p in valid])
            sec.sensors_with_readings += 1
            if latest_at is None or last.observed_at > latest_at:
                latest_at = last.observed_at
        counts[st.condition] = counts.get(st.condition, 0) + 1
        statuses.append(st)

    sec.sensors = statuses
    sec.condition_counts = counts
    sec.latest_reading_at = latest_at
    sec.readings_available = sec.sensors_with_readings > 0
    sec.data_kind = "live" if sec.readings_available else ("latest_available" if sensors else "unavailable")
    if not sec.readings_available:
        sec.limitations.append(
            "PUB publishes drain/canal sensor LOCATIONS as open data, but no official open feed of "
            "water-level READINGS was found. Sensor locations are shown as infrastructure only; "
            "no drain is classified Normal/Elevated/High/Critical and no level is displayed."
        )
    if sensors and not sensors_source_ok:
        sec.limitations.append("Sensor locations are from a cached copy.")
    if not sensors:
        sec.limitations.append("Sensor location layer unavailable.")
    return sec


def overall_from_drain(drain: DrainSection) -> tuple:
    """(overall_status, overall_risk) - UNKNOWN unless real readings exist."""
    if not drain.readings_available:
        return "UNKNOWN", "UNKNOWN"
    c = drain.condition_counts
    if c.get("CRITICAL"):
        return "CRITICAL", "CRITICAL"
    if c.get("HIGH"):
        return "ELEVATED", "HIGH"
    if c.get("ELEVATED"):
        return "ELEVATED", "MODERATE"
    return "NORMAL", "LOW"


# ------------------------------------------------------------------ alerts
def build_alerts(usage: UsageSection, newater: NEWaterSection, quality: QualitySection, drain: DrainSection) -> List[WaterAlert]:
    alerts: List[WaterAlert] = []
    for st in drain.sensors:
        if st.condition in ("ELEVATED", "HIGH", "CRITICAL"):
            sev = {"ELEVATED": "MODERATE", "HIGH": "HIGH", "CRITICAL": "HIGH"}[st.condition]
            alerts.append(WaterAlert(
                id=f"drain-{st.sensor.id}", severity=sev, category="drain_condition",  # type: ignore[arg-type]
                message=f"Drain sensor {st.sensor.name or st.sensor.id} at {st.percentage}% of reference depth ({st.condition})",
                evidence=[f"observed_at={st.observed_at}", f"trend={st.trend}"], data_kind="live",
            ))
    for p in quality.parameters:
        if p.compliance == "EXCEEDS_LIMIT":
            alerts.append(WaterAlert(
                id=f"quality-{p.key}", severity="HIGH", category="water_quality",
                message=f"{p.parameter} ({quality.reporting_period}) outside PUB regulatory limit {p.regulatory_limit}",
                evidence=[f"average={p.average}", f"range={p.range}"], data_kind="latest_available",
            ))
    for ind, cat in ((usage.potable_total, "usage"), (usage.domestic, "usage"), (usage.non_domestic, "usage"), (newater.latest, "newater")):
        if ind and ind.change_pct is not None and abs(ind.change_pct) >= YOY_ALERT_PCT:
            alerts.append(WaterAlert(
                id=f"yoy-{ind.key}", severity="LOW", category=cat,
                message=f"{ind.label} changed {ind.change_pct:+.1f}% between {ind.previous_period} and {ind.period}",
                evidence=[f"{ind.previous_value} -> {ind.value} {ind.unit}", f"flag threshold ±{YOY_ALERT_PCT:.0f}% (statistical, not an official limit)"],
                data_kind="historical",
            ))
    for w in usage.consistency_warnings:
        alerts.append(WaterAlert(id=f"consistency-{w[:4]}", severity="LOW", category="data_quality", message=w, data_kind="historical"))
    return alerts
