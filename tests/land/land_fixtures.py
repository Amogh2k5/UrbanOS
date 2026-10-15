"""Land test fixtures shaped like the real data.gov.sg sources.

Field names, dataset ids and value ranges are taken from the live datasets that
were opened and schema-verified while building the module:

  land use      G_MP25_LANDUSE_PL      d_a8c3546b26712e35021f3a681d0353ae
  planning area G_MP25_PLNG_AREA_NO_SEA_PL  d_2cc750190544007400b2cfd5d7f53209
  region        G_MP25_REGION_NO_SEA_PL     d_4ce0038f7ac689652350bb91b7fb92ed
  cadastral     CADASTRAL_LAND_LOT         d_e7395d743076a2bcc487b0d12b9bf33b
  gls site      URA_SALE_SITE_PL           d_0e2b42f98535686282031a42c9c7b05a
  jtc estate    JTC_ESTATE_NAME            d_0e6c5a63613b812b7240612c5d837a82

All geometry is WGS84 lon/lat, exactly as published.
"""
from __future__ import annotations

import json

UPDATED = "20251229172155"


def _ring(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def land_use_feature(lu_desc="RESIDENTIAL", gpr="2.8", area=1000.0, x=103.84, y=1.30):
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [_ring(x, y, x + 0.001, y + 0.001)]},
        "properties": {
            "OBJECTID": 1,
            "LU_DESC": lu_desc,
            "LU_TEXT": None,
            "GPR": gpr,
            "WHI_Q_MX": None,
            "GPR_B_MN": None,
            "INC_CRC": "9FFCB6622FA68945",
            "FMEL_UPD_D": UPDATED,
            "SHAPE.AREA": area,
            "SHAPE.LEN": 300.0,
        },
    }


def land_use_doc(n=3):
    feats = [
        land_use_feature("RESIDENTIAL", "2.8", 1000.0, 103.84, 1.30),
        land_use_feature("COMMERCIAL", "LND", 500.0, 103.85, 1.31),
        land_use_feature("PARK", "EVA", 250.0, 103.86, 1.32),
    ][:n]
    return json.dumps({"type": "FeatureCollection", "name": "G_MP25_LANDUSE_PL", "features": feats}).encode()


def planning_area_doc():
    feats = [
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [_ring(103.80, 1.28, 103.90, 1.38)]},
            "properties": {
                "OBJECTID": 1,
                "PLN_AREA_N": "BUKIT TIMAH",
                "PLN_AREA_C": "BT",
                "CA_IND": "N",
                "REGION_N": "CENTRAL REGION",
                "REGION_C": "CR",
                "INC_CRC": "A3BFBAC3EBE4A93B",
                "FMEL_UPD_D": "20251229123848",
                "SHAPE.AREA": 17518288.1814697,
                "SHAPE.LEN": 22652.99,
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [_ring(103.60, 1.28, 103.75, 1.38)]},
            "properties": {
                "OBJECTID": 2,
                "PLN_AREA_N": "CLEMENTI",
                "PLN_AREA_C": "CL",
                "CA_IND": "N",
                "REGION_N": "WEST REGION",
                "REGION_C": "WR",
                "INC_CRC": "BB3FBAC3EBE4A93B",
                "FMEL_UPD_D": "20251229123848",
                "SHAPE.AREA": 13518288.0,
                "SHAPE.LEN": 22652.99,
            },
        },
    ]
    return json.dumps({"type": "FeatureCollection", "name": "G_MP25_PLNG_AREA_NO_SEA_PL", "features": feats}).encode()


def region_doc():
    feats = [{
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [_ring(103.6, 1.2, 104.1, 1.48)]},
        "properties": {
            "OBJECTID": 1,
            "REGION_N": "CENTRAL REGION",
            "REGION_C": "CR",
            "INC_CRC": "63C6FAD3D10B7D2E",
            "FMEL_UPD_D": "20251229123457",
            "SHAPE.AREA": 136413235.63491,
            "SHAPE.LEN": 129647.35,
        },
    }]
    return json.dumps({"type": "FeatureCollection", "name": "G_MP25_REGION_NO_SEA_PL", "features": feats}).encode()


def cadastral_doc(n=3, dupes=0):
    feats = []
    for i in range(n):
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [_ring(103.77 + i * 0.001, 1.30, 103.771 + i * 0.001, 1.301)]},
            "properties": {
                "OBJECTID_1": 80458188 + i,
                "LOT_KEY": f"MK10-0070{i}X",
                "INC_CRC": "9415BA616CB2A80D",
                "FMEL_UPD_D": "20250422001659",
                "SHAPE_1.AREA": 17682.5973,
                "SHAPE_1.LEN": 3065.34,
            },
        })
    for i in range(dupes):
        feats.append(json.loads(json.dumps(feats[0])))
    return json.dumps({"type": "FeatureCollection", "name": "CADASTRAL_LAND_LOT", "features": feats}).encode()


def gls_doc():
    feats = [
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [_ring(103.79, 1.33, 103.792, 1.332)]},
            "properties": {
                "OBJECTID": 24193,
                "HOUSING_UN": 0, "HOTEL_RM": 0, "COM_SQM": 0,
                "DATE_LNCH": "19950329", "DATE_CLOSG": "19950621", "DATE_AWARD": "19950822",
                "LOCATION": "Kaki Bukit Avenue 1",
                "DEVT_ALLOW": "Light Industry", "LEASE_YR": "60", "DEVT_CODE": "Industrial",
                "SA_SQM": 60988.6, "GPR": 2.5, "GFA": 0, "NO_OF_BIDS": 3,
                "SUCCESS_TR": "Ho Lee Investments (Pte) Ltd", "SUCCESS_TP": 136390000,
                "PLN_AREA_N": "Bedok", "EXPECTED_P": None,
                "FMEL_UPD_D": "20231026175842", "SHAPE.AREA": 61012.21, "SHAPE.LEN": 1000.75,
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [_ring(103.80, 1.31, 103.802, 1.312)]},
            "properties": {
                "OBJECTID": 24195,
                "HOUSING_UN": 315, "HOTEL_RM": 0, "COM_SQM": 0,
                "DATE_LNCH": "20250101", "DATE_CLOSG": "20250601", "DATE_AWARD": "20250701",
                "LOCATION": "Peck Hay Road",
                "DEVT_ALLOW": "Condominium", "LEASE_YR": "99", "DEVT_CODE": "Residential (Non-Landed)",
                "SA_SQM": 27034, "GPR": 4.9, "GFA": 75695, "NO_OF_BIDS": 5,
                "SUCCESS_TR": "Example Developer", "SUCCESS_TP": 155631000,
                "PLN_AREA_N": "Novena", "EXPECTED_P": None,
                "FMEL_UPD_D": "20250702120000", "SHAPE.AREA": 27034.0, "SHAPE.LEN": 900.0,
            },
        },
    ]
    return json.dumps({"type": "FeatureCollection", "name": "URA_SALE_SITE_PL", "features": feats}).encode()


def jtc_doc():
    feats = [{
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [_ring(103.70, 1.33, 103.72, 1.34)]},
        "properties": {
            "OBJECTID_1": 41130,
            "ESTATE_NAME": "Jurong Industrial Estate Others",
            "INC_CRC": "CF530EC57E529BB9",
            "FMEL_UPD_D": "20241126123953",
            "SHAPE_1.AREA": 3027335.96326847,
            "SHAPE_1.LEN": 14512.62,
        },
    }]
    return json.dumps({"type": "FeatureCollection", "name": "JTC_ESTATE_NAME", "features": feats}).encode()


def poll_download_response(body: bytes, dataset_id: str = "d_test") -> bytes:
    """Poll-download payload. The presigned URL embeds the dataset id (as the
    real service does) so a mock handler can route the subsequent download."""
    return json.dumps({
        "code": 0,
        "data": {"url": f"https://files.example/{dataset_id}.geojson?X-Amz-Security-Token=SECRET"},
    }).encode()


def docs_by_key() -> dict:
    return {
        "land_use": land_use_doc(),
        "planning_areas": planning_area_doc(),
        "regions": region_doc(),
        "cadastral": cadastral_doc(),
        "gls_sites": gls_doc(),
        "jtc_estates": jtc_doc(),
    }