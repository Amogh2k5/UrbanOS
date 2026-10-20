"""Deterministic transformations for official housing datasets."""
from __future__ import annotations
import re
from collections import defaultdict
from typing import Any
from .data import DATASETS, SourceResult
from .models import HousingReport, HousingSource, HousingInsight

def _str(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        val = row.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""

def _number(value: Any) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace("$", "")
    if not s or s.lower() in {"na", "n/a", "null", "none", "-", "--"}:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None

def _period_key(period: str) -> tuple[int, int]:
    m = re.match(r"(\d{4})-Q([1-4])", period, re.I)
    if m:
        return int(m.group(1)), int(m.group(2))
    return (0, 0)

def build_housing_report(snapshot: dict[str, Any]) -> HousingReport:
    sources: dict[str, SourceResult] = snapshot["sources"]
    median = sources["median_resale"]
    apps = sources["resale_applications"]
    prop = sources["hdb_property"]
    limitations = [
        "This is a periodic/historical housing intelligence view, not a live property market feed.",
        "HDB median resale price is a town/flat-type statistic, not an individual flat valuation.",
        "HDB property inventory provides block/street reference fields but no verified latitude/longitude in this dataset; no map markers are fabricated.",
        "Detailed current URA private-market datasets and SingStat household tables were not confirmed as accessible machine-readable feeds in this implementation; their metrics remain unavailable rather than inferred.",
    ]
    warnings: list[str] = []
    resale_rows = []
    if median.status == "available":
        for r in median.records:
            period = _str(r, "quarter", "Quarter")
            town = _str(r, "town", "Town")
            flat = _str(r, "flat_type", "Flat Type")
            price = _number(_str(r, "price", "Price"))
            if period and town and flat and price is not None:
                resale_rows.append({"period": period, "town": town, "flat_type": flat, "median_price": price})
    periods = sorted({r["period"] for r in resale_rows}, key=_period_key)
    latest_period = periods[-1] if periods else None
    latest = [r for r in resale_rows if r["period"] == latest_period] if latest_period else []
    towns: dict[str, dict[str, Any]] = {}
    flat_types: dict[str, list[float]] = defaultdict(list)
    for r in latest:
        towns.setdefault(r["town"], {"town": r["town"], "prices": {}})["prices"][r["flat_type"]] = r["median_price"]
        flat_types[r["flat_type"]].append(r["median_price"])
    town_prices = sorted(
        [{"town": t, **v["prices"]} for t, v in towns.items()],
        key=lambda x: x["town"],
    )
    resale_by_flat = [{"flat_type": f, "median_price_across_towns": round(sum(v)/len(v), 2), "towns_with_data": len(v)}
                      for f, v in sorted(flat_types.items()) if v]
    trend = []
    if resale_rows:
        grouped: dict[str, list[float]] = defaultdict(list)
        for r in resale_rows:
            grouped[r["period"]].append(r["median_price"])
        trend = [{"period": p, "mean_of_town_flat_medians": round(sum(grouped[p])/len(grouped[p]), 2), "observations": len(grouped[p])}
                 for p in periods]
        warnings.append("The trend's aggregate is an unweighted mean of available town/flat-type medians, not an official HDB Resale Price Index.")
    app_records = apps.records if apps.status == "available" else []
    latest_app_period = None
    app_total = None
    if app_records:
        normalized = []
        for r in app_records:
            period = _str(r, "quarter", "Quarter")
            typ = _str(r, "flat_type", "Flat Type")
            value = _number(_str(r, "no_of_resale_applications", "resale_applications", "applications", "count", "value", "Resale Applications"))
            if period and value is not None:
                normalized.append((period, typ, value))
        app_periods = sorted({x[0] for x in normalized}, key=_period_key)
        if app_periods:
            latest_app_period = app_periods[-1]
            app_total = sum(x[2] for x in normalized if x[0] == latest_app_period)
    stock_rows = prop.records if prop.status == "available" else []
    total_units = 0
    valid_units = 0
    completion_years: dict[str, int] = defaultdict(int)
    towns_stock: dict[str, int] = defaultdict(int)
    blocks = []
    for r in stock_rows:
        units = _number(_str(r, "total_dwelling_units", "Total Dwelling Units"))
        town = _str(r, "bldg_contract_town", "Bldg Contract Town", "town")
        year = _str(r, "year_completed", "Year Completed")
        block = _str(r, "blk_no", "Blk No")
        street = _str(r, "street", "Street")
        if units is not None and units >= 0:
            total_units += int(units)
            valid_units += 1
            if town:
                towns_stock[town] += int(units)
        if year.isdigit():
            completion_years[year] += 1
        if len(blocks) < 100 and block and street:
            blocks.append({"block": block, "street": street, "town": town or None, "year_completed": int(year) if year.isdigit() else None,
                           "total_dwelling_units": int(units) if units is not None else None})
    kpis = {
        "latest_median_resale_period": latest_period,
        "town_flat_type_median_price_rows": len(latest),
        "latest_resale_applications_period": latest_app_period,
        "resale_applications": round(app_total) if app_total is not None else None,
        "hdb_property_records": len(stock_rows) if prop.status == "available" else None,
        "hdb_total_dwelling_units_in_records": total_units if valid_units else None,
    }
    sources_out = [HousingSource(
        key=k, name=s.name, agency=s.agency, url=s.url, status=s.status,
        retrieved_at=s.retrieved_at, error=s.error, record_count=len(s.records), fields=s.fields,
    ) for k, s in sources.items()]
    unavailable = [s.name for s in sources_out if s.status != "available"]
    if unavailable:
        warnings.append("Some official sources are unavailable: " + ", ".join(unavailable))
    return HousingReport(
        generated_at=snapshot["generated_at"],
        status="AVAILABLE" if len([s for s in sources_out if s.status == "available"]) == len(sources_out) else ("PARTIAL" if any(s.status == "available" for s in sources_out) else "UNAVAILABLE"),
        kpis=kpis,
        resale_trend=trend[-40:],
        town_prices=town_prices[:60],
        resale_by_flat_type=resale_by_flat,
        housing_stock={
            "available": prop.status == "available",
            "source_period": "through Dec 2025 (source catalogue)",
            "hdb_property_records": len(stock_rows) if prop.status == "available" else None,
            "total_dwelling_units_in_records": total_units if valid_units else None,
            "town_unit_counts": [{"town": k, "units": v} for k, v in sorted(towns_stock.items())],
            "completion_year_building_counts": [{"year": int(k), "buildings": v} for k, v in sorted(completion_years.items()) if k.isdigit()],
            "sample_blocks": blocks,
            "note": "Sum reflects the current returned HDB property records; not a separately published national stock KPI.",
        },
        rental_market={"available": False, "hdb_median_rent": None, "private_rent_index": None,
                       "note": "No current median-rent dataset was configured as an accessible machine-readable source in this build."},
        private_residential={"available": False, "price_index": None, "rental_index": None, "vacancy_rate": None,
                             "note": "URA publishes private residential market releases, but a reliable unauthenticated structured API/feed was not confirmed here.",
                             "official_release_url": "https://www.ura.gov.sg/news/"},
        supply_pipeline={"available": False, "items": [], "note": "No verified structured pipeline feed is wired into this module."},
        household_context={"available": False, "resident_households": None, "average_household_size": None,
                           "owner_occupied_share": None, "dwelling_type_share": None,
                           "note": "SingStat household indicators are not represented as live data; a verified machine-readable table is needed."},
        map_data={"available": False, "type": "FeatureCollection", "features": [],
                  "note": "HDB property dataset has block/street fields but no coordinates; map markers are intentionally omitted."},
        sources=sources_out, errors=list(snapshot.get("errors", [])), warnings=warnings,
        limitations=limitations,
        insights=[
            HousingInsight(question="How are HDB resale prices changing?", answer=f"Latest available town/flat-type median period is {latest_period}." if latest_period else "HDB resale median data is currently unavailable.", data_kind="latest_available" if latest_period else "unavailable"),
            HousingInsight(question="Which towns have the highest median resale prices?", answer="Compare towns using the latest-period town/flat-type table; prices vary by flat type, so a single town ranking would be misleading." if latest else "Town comparison is unavailable until the official HDB dataset can be retrieved.", data_kind="latest_available" if latest else "unavailable"),
            HousingInsight(question="How is private housing supply changing?", answer="Unavailable in this module until a verified structured URA supply feed is connected.", data_kind="unavailable"),
            HousingInsight(question="What is happening with residential vacancy?", answer="Unavailable in this module until verified structured URA vacancy data is connected.", data_kind="unavailable"),
            HousingInsight(question="How is housing stock distributed?", answer=f"Returned HDB property inventory includes {len(stock_rows)} records." if stock_rows else "HDB property inventory is currently unavailable.", data_kind="latest_available" if stock_rows else "unavailable"),
        ],
        confidence="high" if len([s for s in sources_out if s.status == "available"]) == len(sources_out) else ("medium" if any(s.status == "available" for s in sources_out) else "low"),
        data_timestamps={
            s.key: {"last_fetched_at": s.retrieved_at, "latest_data_period": None, "status": s.status, "data_kind": "latest_available" if s.status == "available" else "unavailable"}
            for s in sources_out
        },
        is_ml_prediction=False,
    )
