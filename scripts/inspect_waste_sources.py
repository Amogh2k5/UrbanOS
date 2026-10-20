"""Inspect the REAL structure of every official source used by the Waste Management module.

Run this once on a machine with internet access (the development sandbox could not reach data.gov.sg):

    python -m scripts.inspect_waste_sources

For each source it prints HTTP/parse status, record counts, field names, what the parser extracted
and the latest data period, and for the statistics table it re-runs the consistency checks
(generated = recycled + disposed, waste types sum to totals, published vs computed rate).
Exit code 0 only if every source is reachable and parses to usable rows.

Rate limit: data.gov.sg allows only ~5 file downloads per minute without an API key (HTTP 429 beyond that). The client
paces itself, so this script takes about a minute. Set DATA_GOV_SG_API_KEY (free, from data.gov.sg) to go faster.
"""
from __future__ import annotations

import json
import sys

from backend.app.infrastructure.waste import processing as P
from backend.app.infrastructure.waste import sources as src


def show(title: str) -> None:
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def main() -> int:
    # disk_cache=None: always hit the real services, never a cached copy.
    client = src.WasteDataClient(disk_cache=None)
    ok = True
    print(f"API key: {'set' if client.api_key else 'not set'}. The four location layers are downloaded one at a time, "
          f"{client.poll_min_interval_s:g} s apart, to respect data.gov.sg's rate limit "
          f"({'raised by your key' if client.api_key else 'about 5 downloads/minute without a key; set DATA_GOV_SG_API_KEY to speed this up'}). "
          f"Expect about {int(client.poll_min_interval_s * 4)} s in total.")

    show(f"Waste Management And Overall Recycling Rates, Annual  [{src.WASTE_STATS_ID}]")
    try:
        recs = client.get_records(src.WASTE_STATS_ID).data
        print(f"records: {len(recs)} (expected 60 = 4 blocks x 15 rows)")
        print("field names:", sorted({k for r in recs for k in r})[:6], "...")
        print("sample:", json.dumps(recs[:2], ensure_ascii=False)[:300])
        table = src.parse_waste_statistics(recs)
        year = P.latest_complete_year(table)
        print(f"blocks: {sorted(table.total)}  years: {table.years[0]}..{table.years[-1]}  latest complete year: {year}")
        print(f"missing ('na') cells: {table.missing_cells}  unparseable: {table.unparseable_cells}  duplicate rows: {table.duplicate_rows}")
        for w in table.warnings:
            print("warning:", w)
        for c in P.build_data_quality(table).checks:
            print(f"  [{'PASS' if c.passed else 'FAIL'}] {c.description} ({c.checked} years)", *c.failures[:2])
            ok &= c.passed
        if year:
            for k in P.build_kpis(table, year):
                print(f"  KPI {k.key}: {k.value} {k.unit} ({k.period})")
        ok &= year is not None
    except Exception as exc:  # noqa: BLE001
        ok = False
        print("FAILED:", exc)

    show(f"Listing of General Waste Collectors  [{src.COLLECTORS_ID}]")
    try:
        recs = client.get_records(src.COLLECTORS_ID).data
        print(f"records: {len(recs)}  field names: {sorted({k for r in recs for k in r})}")
        listing = src.parse_general_waste_collectors(recs)
        print(f"licensees: {len(listing.licensees)}  duplicates merged: {listing.duplicate_rows_removed}")
        print("class combinations:", dict(listing.combinations.most_common()))
        print("unrecognised class values:", dict(listing.unrecognised))
        ok &= len(listing.licensees) > 0
    except Exception as exc:  # noqa: BLE001
        ok = False
        print("FAILED:", exc)

    for kind, spec in src.FACILITY_SPECS.items():
        show(f"{src.FACILITY_LABELS[kind]}  [{spec['dataset_id']}]")
        try:
            layer = client.get_facility_layer(spec["dataset_id"], kind).data
            print(f"points: {len(layer.facilities)}  invalid: {layer.invalid}  duplicates removed: {layer.duplicates_removed}")
            print(f"record dates: {layer.date_min} .. {layer.date_max}")
            print("by name:", dict(layer.by_name.most_common(5)))
            print("sample:", layer.facilities[:1])
            ok &= len(layer.facilities) > 0
        except Exception as exc:  # noqa: BLE001
            ok = False
            print("FAILED:", exc)

    print("\nRESULT:", "all sources OK" if ok else "one or more sources failed - see above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
