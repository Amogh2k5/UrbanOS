
"""Pure, deterministic normalization of official Energy records."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from .data import DATASETS, _num
from .models import EnergyReport, EnergySource

SG = timezone(timedelta(hours=8))

def _field(row, *names):
    lower = {str(k).lower(): v for k, v in row.items()}
    for name in names:
        if name.lower() in lower: return lower[name.lower()]
    return None

def _source(key, item, error=None):
    m = DATASETS[key]
    if item is None:
        return EnergySource(name=m["name"], dataset_id=m["id"], url=m["url"],
            frequency=m["frequency"], coverage=m["coverage"], unit=m["unit"],
            status="unavailable", error=error)
    records = item["records"]
    period = None
    if records:
        if key == "peak_demand":
            period = f'{_field(records[-1], "year")} {_field(records[-1], "mth", "month")}'
        elif key in ("solar_capacity", "solar_region"):
            period = str(_field(records[-1], "year") or "historical")
        else: period = str(_field(records[-1], "year") or "historical")
    return EnergySource(name=m["name"], dataset_id=m["id"], url=m["url"],
        frequency=m["frequency"], coverage=m["coverage"], unit=m["unit"],
        status="ok" if records else "unavailable", latest_period=period, records=len(records),
        error=None if records else "Official API returned no records")

def build_report(snapshot: dict) -> EnergyReport:
    datasets = snapshot.get("datasets", {})
    sources = [_source(k, datasets.get(k), next((e for e in snapshot.get("errors", []) if DATASETS[k]["name"] in e), None)) for k in DATASETS]
    demand = []
    for row in (datasets.get("peak_demand") or {}).get("records", []):
        year = _field(row, "year"); month = _field(row, "mth", "month")
        value = _num(_field(row, "peak_system_demand_mw", "Peak System Demand"))
        if year is not None and month is not None:
            demand.append({"period": f"{year}-{int(float(month)):02d}", "value_mw": value})
    demand.sort(key=lambda x: x["period"])
    cons = []
    for row in (datasets.get("consumption") or {}).get("records", []):
        year = _field(row, "year")
        sector = _field(row, "sector")
        product = _field(row, "energy_products")
        value = _num(_field(row, "consumption_ktoe", "consumption"))
        if year is not None:
            cons.append({"year": str(year), "sector": sector, "energy_product": product, "consumption_ktoe": value})
    cons.sort(key=lambda x: (x["year"], str(x["sector"]), str(x["energy_product"])))
    solar_region = []
    for row in (datasets.get("solar_region") or {}).get("records", []):
        year = _field(row, "year"); region = _field(row, "ura_planning_region")
        if year is None or region is None: continue
        solar_region.append({
            "year": str(year), "region": str(region),
            "residential_status": _field(row, "residential_status"),
            "installations": _num(_field(row, "num_solar_pv_inst")),
            "capacity_kwac": _num(_field(row, "inst_cap_kwac")),
            "share_percent": _num(_field(row, "total_inst_cap_percent")),
        })
    solar_cap = []
    for row in (datasets.get("solar_capacity") or {}).get("records", []):
        year = _field(row, "year")
        if year is None: continue
        solar_cap.append({
            "year": str(year), "residential_status": _field(row, "residential_status"),
            "user_type": _field(row, "user_type"),
            "capacity_mwp": _num(_field(row, "inst_cap_mwp")),
            "capacity_mwac": _num(_field(row, "inst_cap_mwac")),
        })
    valid_demands = [x["value_mw"] for x in demand if x["value_mw"] is not None]
    valid_solar = [x for x in solar_cap if x["capacity_mwp"] is not None]
    latest_solar_year = max((x["year"] for x in valid_solar), default=None)
    latest_solar = [x["capacity_mwp"] for x in valid_solar if x["year"] == latest_solar_year]
    metrics = {
        "latest_peak_demand_mw": valid_demands[-1] if valid_demands else None,
        "latest_peak_demand_period": next((x["period"] for x in reversed(demand) if x["value_mw"] is not None), None),
        "max_peak_demand_mw": max(valid_demands) if valid_demands else None,
        "average_peak_demand_mw": round(sum(valid_demands)/len(valid_demands), 2) if valid_demands else None,
        "latest_solar_capacity_mwp": round(sum(latest_solar), 3) if latest_solar else None,
        "latest_solar_capacity_year": latest_solar_year,
        "demand_records": len(valid_demands),
        "consumption_records": len(cons),
    }
    available = sum(s.status == "ok" for s in sources)
    status = "OK" if available == len(sources) else ("PARTIAL" if available else "UNAVAILABLE")
    summary = (f"{available} of {len(sources)} official energy datasets are available. "
               "Demand, consumption and solar indicators are historical statistics, not live grid telemetry.")
    limitations = [
        "The verified public peak-system-demand dataset ends in July 2021 and is monthly; it cannot support a truthful current-demand KPI or half-hourly forecast.",
        "The verified solar datasets end in March 2021; figures must be labelled historical and must not be presented as current installed capacity.",
        "The consumption dataset covers 2009–2019 and reports total final energy consumption in ktoe, not electricity-only consumption in MWh.",
        "No half-hourly system-demand series was verified as accessible in the public dataset catalogue during implementation. ML forecasting is therefore disabled rather than fabricated.",
        "A current USEP series, current generation mix, generation capacity/availability, and transmission availability were not added because a directly accessible, verified dataset was not established in this implementation."
    ]
    errors = [s.error for s in sources if s.error]
    warnings = []
    if available < len(sources):
        warnings.append(f"{len(sources) - available} of {len(sources)} energy datasets unavailable or returned no records")
    confidence = "high" if available == len(sources) else ("medium" if available >= len(sources) // 2 else "low")
    data_timestamps = {
        s.name: {"last_fetched_at": datetime.now(SG).isoformat(), "latest_data_period": s.latest_period, "status": s.status, "data_kind": "historical" if s.status == "ok" else "unavailable"}
        for s in sources
    }
    return EnergyReport(generated_at=datetime.now(SG), status=status, summary=summary,
        key_metrics=metrics, peak_demand=demand, consumption=cons,
        solar_by_region=solar_region, solar_capacity=solar_cap, sources=sources,
        limitations=limitations, warnings=warnings, errors=errors,
        confidence=confidence, data_timestamps=data_timestamps)
