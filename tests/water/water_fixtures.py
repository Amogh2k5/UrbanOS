"""Test fixtures shaped like the official sources.

VALUES are copied from what the data.gov.sg dataset pages displayed on 30 Sep 2026
(Water Sales Annual, Volume of Potable Water sold, Volume of NEWater sold, Drinking
water quality datasets). FIELD NAMES are inferred from the pages' column legends and
the documented datastore_search response shape; the live JSON could not be fetched from
the build sandbox (host not allow-listed), so run scripts/inspect_water_sources.py
locally to confirm them against the real API.
"""
from __future__ import annotations

YEARS = list(range(2025, 2014, -1))
_SALES = {
    "Sales Of Potable Water": [515.5, 517.6, 509.5, 506.7, 501.4, 501.2, 500.2, 495.5, 499.4, 517, 514.7],
    "Domestic Use": [304.4, 303.9, 300.2, 305.9, 316.5, 320.7, 297.6, 294.2, 294.8, 301.4, 297.1],
    "Non-Domestic Use": [211.1, 213.7, 209.3, 200.8, 184.9, 180.5, 202.6, 201.3, 204.5, 215.6, 217.6],
    "Sales Of Newater": [153.8, 148.3, 145.1, 148.2, 148.9, 141.1, 145.5, 140.5, 140.2, 126.9, 124.8],
    "Sales Of Industrial Water": ["na", "na", 13.7, 12, 11.4, 13, 17.9, 20.6, 19.9, 21, 25],
}


def water_sales_records():
    recs = []
    for i, (name, vals) in enumerate(_SALES.items(), start=1):
        rec = {"_id": i, "DataSeries": name}
        rec.update({str(y): str(v) for y, v in zip(YEARS, vals)})
        recs.append(rec)
    return recs


def potable_records():
    dom = {2008: 271.4, 2009: 277.8, 2010: 281, 2011: 281.3, 2012: 284.4}
    non = {2008: 191.2, 2009: 190.1, 2010: 195.1, 2011: 197.2, 2012: 206.5}
    recs = []
    for y in dom:
        recs.append({"year": str(y), "category": "Domestic", "sales_of_potable_water": dom[y]})
        recs.append({"year": str(y), "category": "Non-domestic", "sales_of_potable_water": non[y]})
    return recs


def newater_records():
    vals = {2007: 49.15, 2008: 65.99, 2009: 71.95, 2010: 96.4, 2011: 102.4, 2012: 111.4,
            2013: 114.1, 2014: 117.1, 2015: 124.8, 2016: 126.9}
    return [{"year": str(y), "sale_of_newater": v} for y, v in vals.items()]


def quality_records():
    rows = [
        (2023, "Escherichia coli (E. coli)", "cfu/100mL", "<1", "<1"),
        (2023, "Colour", "Hazen", "<5", "<5"),
        (2023, "Conductivity ", "æS/cm", "222", "95 - 587"),
        (2023, "pH Value ", "Units", "8.2", "7.8 - 8.8"),
        (2023, "Total Dissolved Solids", "mg/L", "110", "72 - 354"),
        (2023, "Turbidity", "NTU", "0.14", "0.05 - 0.45"),
        (2023, "Gross Alpha", "Bq/L", "<0.05", "<0.05 - 0.104"),
        # A later year, values chosen to be inside limits, to test "latest year wins".
        (2025, "Escherichia coli (E. coli)", "cfu/100mL", "<1", "<1"),
        (2025, "Conductivity ", "æS/cm", "230", "100 - 600"),
        (2025, "pH Value ", "Units", "8.1", "7.7 - 8.9"),
        (2025, "Total Dissolved Solids", "mg/L", "115", "70 - 360"),
        (2025, "Turbidity", "NTU", "0.15", "<0.05 - 0.48"),
        (2025, "Gross Alpha", "Bq/L", "<0.05", "<0.05 - 0.10"),
    ]
    return [{"year": str(y), "parameter": p, "units": u, "average": a, "range": r} for y, p, u, a, r in rows]


def sensor_geojson():
    def feat(i, lon, lat, name):
        return {"type": "Feature", "id": f"s{i}", "geometry": {"type": "Point", "coordinates": [lon, lat, 0.0]},
                "properties": {"Name": name}}
    return {
        "type": "FeatureCollection",
        "features": [
            feat(1, 103.8198, 1.3521, "Sensor A"),
            feat(2, 103.8500, 1.2900, "Sensor B"),
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}, "properties": {"Name": "Bad"}},
            {"type": "Feature", "geometry": None, "properties": {}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [103.9, 1.33]},
             "properties": {"Description": "<table><tr><th>NAME</th><td>From HTML</td></tr></table>"}},
        ],
    }


def datastore_payload(records, total=None):
    return {"success": True, "result": {"records": records, "total": len(records) if total is None else total}}
