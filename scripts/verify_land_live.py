"""Land module verification.

Reports progress per source and distinguishes cached data from fresh downloads.
By default it exercises only the SMALL datasets so routine checks stay quick;
the two ~190 MB / ~145 MB layers are opt-in.

    python scripts/verify_land_live.py                 # small sources only
    python scripts/verify_land_live.py --only gls_sites,planning_areas
    python scripts/verify_land_live.py --full          # all six, downloads big ones
    python scripts/verify_land_live.py --prewarm land_use,cadastral   # download only, no parse
    python scripts/verify_land_live.py --report        # print report from cached data

No real network access is required once the raw cache is warm.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

sys.path.insert(0, r"C:\projects\UrbanOS")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from backend.app.planning.land.sources import (
    SOURCE_BY_KEY, LandDataClient, _PARSERS, _dataset_id_for, fetch_land_snapshot,
)

# Datasets small enough for a routine check.
SMALL = ["planning_areas", "regions", "gls_sites", "jtc_estates"]
BIG = ["land_use", "cadastral"]
ALL = list(SOURCE_BY_KEY)


def cache_state(client: LandDataClient) -> dict:
    out = {}
    for key in ALL:
        ds = _dataset_id_for(key)
        path = client._read_disk(ds)
        out[key] = "cached" if path else "absent"
    return out


def prewarm(client: LandDataClient, keys: list) -> None:
    print("\n=== PREWARM (download only, no parsing) ===")
    for key in keys:
        ds = _dataset_id_for(key)
        t = time.perf_counter()
        already = client._read_disk(ds)
        if already:
            print(f"  {key:<14} cached  {already.stat().st_size / 1e6:8.1f} MB")
            continue
        url = client._resolve_download_url(ds)
        path = client._download_to_disk(url, ds)
        print(f"  {key:<14} fetched {path.stat().st_size / 1e6:8.1f} MB in {time.perf_counter() - t:.1f}s")
    print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=",".join(SMALL), help="comma-separated source keys")
    ap.add_argument("--full", action="store_true", help="use all six sources")
    ap.add_argument("--prewarm", default="", help="comma-separated keys to download only")
    ap.add_argument("--report", action="store_true", help="build + print the full report")
    args = ap.parse_args()

    client = LandDataClient()

    if args.prewarm:
        prewarm(client, [k.strip() for k in args.prewarm.split(",") if k.strip()])
        return

    keys = ALL if args.full else [k.strip() for k in args.only.split(",") if k.strip()]
    unknown = [k for k in keys if k not in SOURCE_BY_KEY]
    if unknown:
        raise SystemExit(f"unknown source keys: {unknown}; valid={ALL}")

    print("=== LAND SOURCE CACHE STATE ===")
    for key in ALL:
        size = ""
        p = client._read_disk(_dataset_id_for(key))
        if p:
            size = f" ({p.stat().st_size / 1e6:.1f} MB)"
        print(f"  {key:<14} {cache_state(client)[key]:<8}{size}")
    print()

    print(f"=== BUILDING SNAPSHOT for {keys} ===")
    t = time.perf_counter()
    snap = fetch_land_snapshot(client)
    print(f"  snapshot built in {time.perf_counter() - t:.1f}s")
    print()

    print("=== PER-SOURCE RESULT ===")
    for key in keys:
        target = _PARSERS[key][1]
        records = getattr(snap, target, [])
        info = next((s for s in snap.sources if s.key == key), None)
        status = info.status if info else "?"
        err = (info.error if info and info.error else "")
        print(f"  {key:<14} {status:<12} records={len(records):<8} {err[:70]}")
    print()

    print("=== SNAPSHOT SUMMARY ===")
    print(f"  land_use       : {len(snap.land_use)} zones (invalid {snap.land_use_invalid}/{snap.land_use_total_seen})")
    print(f"  planning_areas : {len(snap.planning_areas)}")
    print(f"  regions        : {len(snap.regions)}")
    print(f"  cadastral      : {len(snap.cadastral)} (invalid {snap.cadastral_invalid}, dupes {snap.duplicate_lot_keys})")
    print(f"  gls_sites      : {len(snap.gls_sites)}")
    print(f"  jtc_estates    : {len(snap.jtc_estates)}")
    print(f"  errors         : {len(snap.errors)}")
    print()

    if args.report:
        from backend.app.planning.land.agent import run_land_agent

        print("=== AGENT REPORT ===")
        t = time.perf_counter()
        report = run_land_agent()
        print(f"  built in {time.perf_counter() - t:.1f}s")
        print(f"  source_status={report.source_status} confidence={report.confidence}")
        lu, pl, cad, g, ind = report.land_use, report.planning, report.cadastral, report.gls, report.industrial
        print(f"  land use : zones={lu.total_zones} area_km2={lu.total_area_km2} categories={lu.distinct_categories}")
        print(f"             groups(km2)={ {k: (round(v / 1e6, 1) if v else None) for k, v in lu.by_group.items()} }")
        print(f"  planning : areas={pl.planning_area_count} regions={pl.region_count}")
        print(f"  cadastral: parcels={cad.parcel_count} invalid={cad.invalid_features}")
        print(f"  gls      : sites={g.site_count} years={g.award_year_min}-{g.award_year_max}")
        print(f"  industrial: estates={ind.estate_count} area_km2={ind.total_estate_area_km2}")
        print(f"  alerts={len(report.alerts)} insights={len(report.insights)}")
        for a in report.alerts:
            print(f"    [{a.severity}] {a.category}: {a.message[:90]}")


if __name__ == "__main__":
    main()