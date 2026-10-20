
"""Official data.gov.sg dataset adapters for Energy.

All requests are live at runtime. No current values are hardcoded into the report.
"""
from __future__ import annotations
import os, time, logging
from typing import Any
import requests

log = logging.getLogger(__name__)
BASE = "https://data.gov.sg/api/action/datastore_search"
DATASETS = {
    "solar_capacity": {
        "id": "d_51adcf3cc50e30e25ad68c951743db69",
        "name": "Installed Capacity of Grid-Connected Solar PV Systems by User Type",
        "url": "https://data.gov.sg/datasets/d_51adcf3cc50e30e25ad68c951743db69/view",
        "frequency": "Annual / historical; latest listed period Mar 2021",
        "coverage": "Jan 2008–Mar 2021",
        "unit": "MWp and MWac",
    },
    "solar_region": {
        "id": "d_cd4f91f7a1ebb2b7ceb1a70c0dbb706d",
        "name": "Solar PV Installations by URA Planning Region",
        "url": "https://data.gov.sg/datasets/d_cd4f91f7a1ebb2b7ceb1a70c0dbb706d/view",
        "frequency": "Annual / historical; latest listed period Mar 2021",
        "coverage": "Jan 2008–Mar 2021",
        "unit": "installation count, kWac, percent",
    },
    "peak_demand": {
        "id": "d_926d3e304c0b41e56d4cbd3304acf105",
        "name": "Peak System Demand, 2005 to Jul 2021",
        "url": "https://data.gov.sg/datasets/d_926d3e304c0b41e56d4cbd3304acf105/view",
        "frequency": "Monthly",
        "coverage": "Jan 2005–Jul 2021",
        "unit": "MW",
    },
    "consumption": {
        "id": "d_500440fba49cfc69f395e6dd1df967de",
        "name": "Total Final Energy Consumption, 2009 to 2019",
        "url": "https://data.gov.sg/datasets/d_500440fba49cfc69f395e6dd1df967de/view",
        "frequency": "Annual",
        "coverage": "2009–2019",
        "unit": "ktoe",
    },
}

def _num(v):
    if v is None or str(v).strip().lower() in {"", "na", "n.a.", "-", "null", "none"}:
        return None
    try: return float(str(v).replace(",", ""))
    except (ValueError, TypeError): return None

def fetch_dataset(key: str, timeout: float = 12.0) -> dict[str, Any]:
    meta = DATASETS[key]
    params = {"resource_id": meta["id"], "limit": 5000}
    headers = {}
    api_key = os.getenv("DATA_GOV_SG_API_KEY")
    if api_key: headers["x-api-key"] = api_key
    response = requests.get(BASE, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success") or not isinstance(payload.get("result"), dict):
        raise ValueError("data.gov.sg returned an unsuccessful or malformed response")
    result = payload["result"]
    records = result.get("records")
    if not isinstance(records, list):
        raise ValueError("Dataset response has no records array")
    return {"records": records, "meta": meta, "fetched_at": time.time()}

def fetch_snapshot() -> dict[str, Any]:
    snapshot = {"datasets": {}, "errors": []}
    for key in DATASETS:
        try:
            snapshot["datasets"][key] = fetch_dataset(key)
        except Exception as exc:  # preserve partial availability
            log.warning("Energy source %s unavailable: %s", key, exc)
            snapshot["datasets"][key] = None
            snapshot["errors"].append(f"{DATASETS[key]['name']}: {exc}")
    return snapshot
