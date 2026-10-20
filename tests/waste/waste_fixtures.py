"""Test fixtures shaped like - and valued from - the official sources.

``waste_stat_records()`` reproduces the real ``datastore_search`` response for
"Waste Management And Overall Recycling Rates, Annual" (d_daf568968ab40dc81e7b08887a83c8fa),
retrieved on 11 Oct 2026, for the years 2019-2025 (all 60 rows, exact values) plus the 2000 and
2001 food-waste generated values, which show the series break the module reports.  What is
true of the real response and kept here: 4 blocks x (1 total + 14 waste types) rows, the 4-space
indent on waste-type labels, values as strings, ``_id`` ordering, 'na' for 'Others' rate 2022-2025,
and the label 'Plastic' (not 'Plastics').
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]

# (label, [2019 .. 2025]) per block, in the order of the real table
_GEN = [
    ("Total Generated", [7278000, 5880000, 6944000, 7385000, 6859000, 6658000, 7015000]),
    ("Construction & Demolition", [1440000, 825000, 1013000, 1424000, 832000, 708000, 1150000]),
    ("Ferrous Metal", [1278000, 934000, 1312000, 1338000, 1296000, 1275000, 1265000]),
    ("Non-Ferrous Metal", [126000, 75000, 88000, 92000, 106000, 103000, 115000]),
    ("Used Slag", [174000, 106000, 182000, 169000, 176000, 112000, 79000]),
    ("Scrap Tyres", [33000, 23000, 27000, 26000, 27000, 34000, 34000]),
    ("Horticultural", [400000, 313000, 332000, 221000, 256000, 265000, 232000]),
    ("Wood", [438000, 304000, 310000, 419000, 447000, 410000, 428000]),
    ("Paper/Cardboard", [1011000, 1144000, 1136000, 1064000, 1251000, 1272000, 1192000]),
    ("Glass", [75000, 66000, 74000, 73000, 75000, 79000, 81000]),
    ("Food", [744000, 665000, 817000, 813000, 755000, 784000, 790000]),
    ("Ash And Sludge", [252000, 228000, 249000, 241000, 231000, 229000, 265000]),
    ("Textile/Leather", [168000, 137000, 189000, 254000, 211000, 206000, 231000]),
    ("Plastic", [930000, 868000, 982000, 1001000, 957000, 918000, 890000]),
    ("Others", [210000, 193000, 233000, 249000, 238000, 263000, 264000]),
]
_REC = [
    ("Total Recycled", [4293000, 3040000, 3826000, 4188000, 3553000, 3326000, 3657000]),
    ("Construction & Demolition", [1434000, 822000, 1011000, 1419000, 828000, 706000, 1144000]),
    ("Ferrous Metal", [1270000, 930000, 1306000, 1331000, 1289000, 1268000, 1258000]),
    ("Non-Ferrous Metal", [124000, 73000, 87000, 91000, 105000, 101000, 113000]),
    ("Used Slag", [171000, 104000, 181000, 166000, 173000, 110000, 75000]),
    ("Scrap Tyres", [31000, 22000, 26000, 25000, 26000, 32000, 33000]),
    ("Horticultural", [293000, 249000, 277000, 188000, 218000, 225000, 176000]),
    ("Wood", [289000, 195000, 234000, 298000, 299000, 250000, 258000]),
    ("Paper/Cardboard", [449000, 432000, 437000, 394000, 387000, 402000, 369000]),
    ("Glass", [11000, 7000, 9000, 11000, 6000, 6000, 8000]),
    ("Food", [136000, 126000, 154000, 146000, 132000, 138000, 140000]),
    ("Ash And Sludge", [25000, 16000, 22000, 27000, 32000, 36000, 39000]),
    ("Textile/Leather", [6000, 6000, 7000, 5000, 5000, 7000, 6000]),
    ("Plastic", [37000, 36000, 58000, 57000, 48000, 43000, 34000]),
    ("Others", [15000, 21000, 18000, 30000, 6000, 3000, 3000]),
]
_DIS = [
    ("Total Disposed", [2985000, 2841000, 3118000, 3197000, 3306000, 3332000, 3358000]),
    ("Construction & Demolition", [6000, 3000, 2000, 5000, 5000, 3000, 6000]),
    ("Ferrous Metal", [8000, 4000, 6000, 7000, 7000, 7000, 7000]),
    ("Non-Ferrous Metal", [2000, 2000, 1000, 2000, 1000, 2000, 1000]),
    ("Used Slag", [3000, 2000, 1000, 2000, 3000, 2000, 4000]),
    ("Scrap Tyres", [2000, 1000, 1000, 1000, 1000, 1000, 1000]),
    ("Horticultural", [107000, 64000, 55000, 32000, 38000, 40000, 55000]),
    ("Wood", [149000, 109000, 76000, 121000, 149000, 160000, 170000]),
    ("Paper/Cardboard", [561000, 712000, 699000, 671000, 863000, 871000, 823000]),
    ("Glass", [64000, 58000, 65000, 63000, 69000, 73000, 72000]),
    ("Food", [607000, 539000, 663000, 667000, 623000, 646000, 649000]),
    ("Ash And Sludge", [226000, 211000, 227000, 213000, 199000, 193000, 226000]),
    ("Textile/Leather", [161000, 131000, 182000, 249000, 206000, 199000, 225000]),
    ("Plastic", [893000, 832000, 924000, 944000, 909000, 875000, 856000]),
    ("Others", [195000, 173000, 214000, 219000, 232000, 260000, 261000]),
]
_RATE = [
    ("Recycling Rate", [59, 52, 55, 57, 52, 50, 52]),
    ("Construction & Demolition", [99, 99, 99, 99, 99, 99, 99]),
    ("Ferrous Metal", [99, 99, 99, 99, 99, 99, 99]),
    ("Non-Ferrous Metal", [99, 98, 98, 98, 99, 99, 99]),
    ("Used Slag", [99, 99, 99, 99, 98, 98, 95]),
    ("Scrap Tyres", [94, 95, 95, 95, 95, 96, 96]),
    ("Horticultural", [73, 80, 83, 85, 85, 85, 76]),
    ("Wood", [66, 64, 76, 71, 67, 61, 60]),
    ("Paper/Cardboard", [44, 38, 39, 37, 31, 32, 31]),
    ("Glass", [15, 11, 13, 14, 8, 7, 10]),
    ("Food", [18, 19, 19, 18, 18, 18, 18]),
    ("Ash And Sludge", [10, 7, 9, 11, 14, 16, 15]),
    ("Textile/Leather", [4, 4, 4, 2, 2, 3, 3]),
    ("Plastic", [4, 4, 6, 6, 5, 5, 4]),
    ("Others", [7, 11, 8, "na", "na", "na", "na"]),
]
_FOOD_GEN_EARLY = {2000: 1093000, 2001: 536000}   # real values; the break the module flags


def waste_stat_records(*, with_early_food: bool = False) -> List[Dict[str, Any]]:
    recs: List[Dict[str, Any]] = []
    i = 0
    for block in (_GEN, _REC, _DIS, _RATE):
        for pos, (label, vals) in enumerate(block):
            i += 1
            rec: Dict[str, Any] = {"_id": i, "DataSeries": label if pos == 0 else "    " + label}
            # the real API returns years newest-first in the field list, values as strings
            for y, v in sorted(zip(YEARS, vals), reverse=True):
                rec[str(y)] = str(v)
            if with_early_food and block is _GEN and label == "Food":
                for y, v in _FOOD_GEN_EARLY.items():
                    rec[str(y)] = str(v)
            recs.append(rec)
    return recs


def mutate(records: List[Dict[str, Any]], label: str, block_index: int, year: int, value: Any) -> List[Dict[str, Any]]:
    """Return a copy with one cell changed. ``block_index`` 0..3 = generated/recycled/disposed/rate."""
    out = copy.deepcopy(records)
    start = block_index * 15
    for rec in out[start:start + 15]:
        if rec["DataSeries"].strip() == label:
            rec[str(year)] = str(value)
            return out
    raise KeyError(label)


def collector_records() -> List[Dict[str, Any]]:
    """Shaped like d_b4de98f706379b787ab86d1e69412910 (field ids from the dataset's column legend)."""
    def r(i, cls, name):
        return {"_id": i, "class_of_waste": cls, "Licensee_Name": name, "Address": f"BLK {i} TEST ROAD SINGAPORE 10000{i}",
                "Email_Address": f"secret{i}@example.com", "Contact_No": f"6000000{i}"}
    return [
        r(1, "Class A, Class B", "800 SUPER WASTE MANAGEMENT PTE LTD"),
        r(2, "Class A", "A & T WASTE HAULAGE SERVICES PTE LTD"),
        r(3, "Class A", "ADVANCED RECYCLING PTE. LTD."),
        r(4, "Class C", "SLUDGE CO PTE LTD"),
        r(5, "Class B.1", "OIL RECYCLERS PTE LTD"),
        r(6, "Class A", "advanced  recycling pte. ltd."),            # duplicate (case / spacing)
        r(7, "Class A, Class Z", "ODD CLASS PTE LTD"),                  # unknown class token
        {"_id": 8, "class_of_waste": "Class A", "Licensee_Name": "", "Address": "x"},   # no name -> skipped
    ]


def _kml_feature(lon, lat, name, addr_blk="", street="", date="20170602165922", kml="kml_1"):
    desc = (
        "<center><table><tr><th colspan='2' align='center'><em>Attributes</em></th></tr>"
        f"<tr bgcolor=\"#E3E3F3\"> <th>ADDRESSBLOCKHOUSENUMBER</th> <td>{addr_blk}</td> </tr>"
        f"<tr bgcolor=\"\"> <th>ADDRESSSTREETNAME</th> <td>{street}</td> </tr>"
        f"<tr bgcolor=\"#E3E3F3\"> <th>DESCRIPTION</th> <td>Recycle &amp; reuse</td> </tr>"
        f"<tr bgcolor=\"\"> <th>NAME</th> <td>{name}</td> </tr>"
        f"<tr bgcolor=\"#E3E3F3\"> <th>FMEL_UPD_D</th> <td>{date}</td> </tr></table></center>"
    )
    return {"type": "Feature", "properties": {"Name": kml, "Description": desc},
            "geometry": {"type": "Point", "coordinates": [lon, lat, 0.0]}}


def bins_geojson() -> Dict[str, Any]:
    return {"type": "FeatureCollection", "features": [
        _kml_feature(103.875, 1.3885, "Recycling Bins in HDB Estates", "407", "FERNVALE ROAD", kml="kml_1"),
        _kml_feature(103.894, 1.3654, "Recycling Bins in HDB Estates", "312", "HOUGANG AVENUE 5", kml="kml_2"),
        _kml_feature(103.894, 1.3654, "Recycling Bins in HDB Estates", "312", "HOUGANG AVENUE 5", kml="kml_3"),  # exact duplicate
        _kml_feature(103.816, 1.2886, "Recycling Bins at Schools", "76", "REDHILL ROAD", date="20190101000000", kml="kml_4"),
        _kml_feature(0.0, 0.0, "Bad coords", kml="kml_5"),                                   # outside Singapore
        {"type": "Feature", "properties": {}, "geometry": None},                              # no geometry
        {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": []}},
    ]}


def ewaste_geojson() -> Dict[str, Any]:
    def f(lon, lat, name, building, street, desc, date):
        return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {"OBJECTID": 1, "NAME": name, "ADDRESSBLOCKHOUSENUMBER": None, "ADDRESSBUILDINGNAME": building,
                               "ADDRESSSTREETNAME": street, "DESCRIPTION": desc, "ACCESSRESTRICTION": "Public", "FMEL_UPD_D": date}}
    return {"type": "FeatureCollection", "name": "EWASTE", "features": [
        f(103.8015, 1.2743, "NEA Producer Responsibility Scheme - ALBA E-waste Recycling Programme", "ALEXANDRA RETAIL CENTRE (ARC)",
          "460 ALEXANDRA ROAD", "Bin collection; E-waste accepted: ICT equipment, Batteries and Lamps only", "20220602130953"),
        f(103.8524, 1.2823, "KGS E-waste Recycling Programme for Non-regulated E-waste", "ONE MARINA",
          "1 MARINA BOULEVARD", "Bin collection; E-waste accepted: Non-regulated products only", "20220518163655"),
    ]}


def lighting_geojson() -> Dict[str, Any]:
    return {"type": "FeatureCollection", "features": [
        _kml_feature(103.923, 1.3126, "Lightbulb/Lamp Recycling Points", "55", "Siglap Road", date="20190930163217", kml="kml_1"),
        _kml_feature(103.8058, 1.2879, "Lightbulb/Lamp Recycling Points", "317", "Alexandra Road", date="20190930163217", kml="kml_2"),
    ]}


def disposal_geojson() -> Dict[str, Any]:
    def f(lon, lat, name, desc):
        return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {"NAME": name, "DESCRIPTION": desc, "ADDRESSSTREETNAME": "98 Tuas South Avenue 3", "FMEL_UPD_D": "20180201145018"}}
    return {"type": "FeatureCollection", "features": [
        f(103.7695, 1.2066, "Semakau Landfill", "Government operated offshore landfill"),
        f(103.6209, 1.2957, "Tuas South Incineration Plant", "Government operated municipal waste incineration plant"),
        f(103.7949, 1.4623, "Senoko Waste-to-Energy Plant", "Private municipal waste incineration plant"),
    ]}


def datastore_payload(records, total: Optional[int] = None) -> Dict[str, Any]:
    return {"success": True, "result": {"records": records, "total": len(records) if total is None else total}}
