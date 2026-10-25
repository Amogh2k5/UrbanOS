# UrbanOS Waste Management Module

Infrastructure → **Waste Management**. Official Singapore waste generation, recycling, disposal, waste types, food waste,
licensed collectors and recycling / disposal infrastructure.
Backend: `backend/app/infrastructure/waste/` · Frontend: `/infrastructure/waste` · Tests: `tests/waste/`.

> **Everything in this module is annual statistics or static reference listings. Nothing is live.**
> There is no official open feed of bin fill levels, garbage-truck tracking, collection activity or landfill capacity,
> and the module shows none of them.

## What the research found

Verified on 11-12 Oct 2026 through the dataset pages on data.gov.sg and, for the statistics table, the live
`datastore_search` JSON response. The development sandbox could not call data.gov.sg directly, so
**run `python -m scripts.inspect_waste_sources` once on a networked machine** to confirm the endpoints from your side.

| Need | Verdict |
|---|---|
| Waste generated / recycled / disposed, recycling rate, **14 waste types incl. food** | One dataset (SingStat, from MSE/NEA), **annual, 2000-2025** |
| Domestic vs non-domestic waste | **Not machine-readable.** NEA reports the split in text on its web page only |
| Domestic waste per capita | **Not available** (needs a domestic series + population series; neither verified) |
| Food waste | Only the national "Food" row (generated / recycled / disposed / rate). No household/retail split |
| Recycling bins, e-waste points, lighting-waste points | NEA GeoJSON layers - **static, dated 2017-2022** |
| Waste disposal sites | NEA GeoJSON, **7 points dated 2018-02-01** (publisher: "may be outdated") |
| General waste collectors | NEA licence register (Jan 2026), 368 rows |
| Landfill capacity, truck tracking, bin fill levels, live collection | **No official open data exist.** Not shown |
| Monthly / quarterly waste series | **None exist** → no forecast (see below) |

## Sources actually integrated

| key | Dataset (data.gov.sg id) | Format / access | Coverage | Update | Kind |
|---|---|---|---|---|---|
| `waste_statistics` | Waste Management And Overall Recycling Rates, Annual - SingStat (`d_daf568968ab40dc81e7b08887a83c8fa`) | `datastore_search` JSON, 60 rows × 27 cols, wide (years as columns) | 2000-2025, national | Annual (page: updated 21 Jul 2026) | latest_available / historical |
| `general_collectors` | Listing of General Waste Collectors - NEA (`d_b4de98f706379b787ab86d1e69412910`) | `datastore_search`, 368 rows | Jan 2026 listing | Periodic (updated 19 Jan 2026) | reference |
| `recycling_bins` | Recycling Bins - NEA (`d_4dde14826642f49eefff48b7832b90db`) | GeoJSON via `poll-download` (~18.5 MB) | static point layer; feature stamps 2017 | page updated 06 Jun 2024 | reference |
| `ewaste_points` | E-waste Recycling (GEOJSON) - NEA (`d_db40d004afeb5a7f0f555fdcc34934cc`) | GeoJSON (~660 KB) | publisher: data last updated 2022-06-02 | page updated 08 Nov 2025 | reference |
| `lighting_waste` | Lighting Waste Collection Points (GEOJSON) - NEA (`d_6226f69998ed0cb62151af37706508cd`) | GeoJSON (~3 KB) | feature stamps 2019-09-30 | page updated 06 Jun 2024 | reference |
| `disposal_sites` | Waste Disposal Site - NEA (`d_4b6f69760d43000af97708ca7367c334`) | GeoJSON (~6 KB, 7 points) | publisher: last updated 2018-02-01 | page updated 08 Nov 2025 | reference |

All are under the Singapore Open Data Licence. No API key is required (`DATA_GOV_SG_API_KEY` is sent as `x-api-key` if set, for higher rate limits).

### Not used on purpose
- **Waste Disposed Of And Recycled, Annual** (SingStat, `d_72f8e05d45477a7af0c089ad970519da`): a coarser subset of the table above (million tonnes, ends earlier).
- **E-waste Recycling_NEW** (`d_e8c94e00d7e1dca4ae3248d0a8e39959`): the dataset page now says the dataset does not exist; superseded by `d_db40…`.
- **Waste Treatment**: hazardous/toxic industrial waste treatment licensees - a different scope.
- NEA web-page text (e.g. domestic / non-domestic recycling rates): official but not an API; not scraped.

## Field mapping and units

### Statistics table (`waste_statistics`)
- One row per series; one column per year (`"2025"`, `"2024"`, … as strings). Row label field: `DataSeries`.
- **Four blocks of 15 rows**, in `_id` order: `Total Generated` + 14 types, `Total Recycled` + 14, `Total Disposed` + 14, `Recycling Rate` + 14.
  The 14 waste-type labels repeat in every block (indented 4 spaces), so a type row is only meaningful via the block header before it.
  The parser keys on the block-header *names*, not on indentation.
- **Mixed units:** the dataset page labels every column "Tonnes", but the `Recycling Rate` block is a **percentage**. The parser assigns units per block: tonnes for generated / recycled / disposed, % for rate.
- Source rounding (per SingStat footnote): **tonnes to the nearest 1,000, rates to the nearest percentage point.**
- `"na"` appears for *Others* recycling rate in 2022-2025; it is kept as missing (`null`), never 0.
- Quirk: the label is `Plastic` (shown as "Plastics"); `Ash And Sludge` (shown "Ash & sludge").
- SingStat footnote: from 2019, wood and horticultural wastes recycled include materials sent to facilities (e.g. biomass power plants, an energy-from-waste plant) for use as fuel.

| Source field | Model | Unit |
|---|---|---|
| `Total Generated` / `Total Recycled` / `Total Disposed` rows | `generation.generated` / `recycled` / `disposed` | tonnes |
| `Recycling Rate` row | `generation.recycling_rate_published` | % (whole points) |
| 14 type rows × 4 blocks | `categories.rows[]`, `categories.series[]` | tonnes / % |
| `Food` rows | `food.*` | tonnes / % |

### General waste collectors
`class_of_waste` (e.g. `Class A, Class B`), `Licensee_Name`. Class meanings (from the dataset page): **A** inorganic & bulky waste and recyclables excl. food waste;
**B** organic/putrescible waste; **B.1** used cooking oil; **C** sewage, sludge & grease-interceptor waste.
Licensees are de-duplicated on normalised name; a licensee with several classes counts once per class.
**Email addresses and phone numbers in the source are deliberately never ingested or served.**

### Location layers
Two layouts are handled: direct properties (e-waste, disposal sites: `NAME`, `DESCRIPTION`, `ADDRESS*`, `FMEL_UPD_D`) and the KML-derived layout
(recycling bins, lighting waste) whose real attributes sit in an HTML `Description` table (`NAME` there; the top-level `Name` is a `kml_N` placeholder).
`FMEL_UPD_D` (`YYYYMMDDhhmmss`) is the per-record update stamp. Points outside a Singapore bounding box, non-points and exact duplicates are dropped and counted.
Recycling-bin popups carry no address in the map payload (≈10k points); the other layers include address, description and record date.

## Architecture

```
data.gov.sg  ──►  sources.py        client (timeout, retry/backoff on 429/5xx, poll-download throttle, memory + disk cache, background layer loading),
                                      parsers, concurrent fetch of the 6 sources, per-source isolation
             ──►  processing.py     deterministic analytics, data-quality checks, alerts
             ──►  agent.py          WasteManagementAgent (LangGraph: ingest → analyze → build_report) + rule-based insights
             ──►  models.py         WasteReport (Pydantic)
             ──►  api.py            /api/waste/*          ──►  frontend /infrastructure/waste
             ──►  coordinator/city_agent.py  domain_status["waste"]
```

### Rate limits and background loading

data.gov.sg's official download guide states that anonymous callers get **about 5 `poll-download` requests per minute** (HTTP 429 beyond that);
an API key raises the limit. A first live run hit exactly this (HTTP 429 on two of the four location layers), so the client now:

1. **spaces `poll-download` requests** (12.5 s apart without a key, 1 s with `DATA_GOV_SG_API_KEY`; shared by the whole process);
2. **backs off 12 s, then 24 s** after a 429 (or honours `Retry-After`) instead of retrying after 1-2 s, and says in the error that a key avoids this;
3. **never makes the report wait for the layers.** The API and the City Coordinator call `fetch_waste_snapshot(wait_for_layers=False)`: statistics and the licence
   register come back immediately; each location layer is read from the memory/disk cache, or reported as `status: "loading"` while **one background worker**
   downloads the missing layers one after another. `loading` is not an error and raises no alert. The frontend re-checks every 15 s while anything is loading and
   reloads the map as locations arrive. If a background download fails, the layer becomes `unavailable` with the reason and is retried after 5 minutes (never in a loop);
4. **keeps the parsed layers on disk** (default `<system temp>/urbanos_waste_cache/`, one JSON file per dataset, atomic writes), so a restart does not re-download 18.5 MB.
   A copy older than 24 h is still shown (`stale_cache`) while it refreshes in the background.

First start without a key therefore shows statistics at once and the four layers over roughly the first minute. Setting `DATA_GOV_SG_API_KEY` makes it a few seconds.

| Setting | Default | Purpose |
|---|---|---|
| `DATA_GOV_SG_API_KEY` | unset | sent as `x-api-key`; raises rate limits and shortens the poll spacing |
| `URBANOS_WASTE_POLL_INTERVAL_S` | 12.5 (1.0 with a key) | minimum seconds between `poll-download` requests |
| `URBANOS_WASTE_CACHE_TTL_S` | 21600 (6 h) | statistics / licence register cache |
| `URBANOS_WASTE_FACILITY_CACHE_TTL_S` | 86400 (24 h) | location layers |
| `URBANOS_WASTE_CACHE_DIR` | system temp dir | disk cache location |
| `URBANOS_WASTE_DISK_CACHE` | 1 | set `0` to disable the disk cache |

The API caches the built report 10 min (60 s if a source failed, 10 s while layers are loading). `?refresh=true` bypasses the report cache only.

### Endpoints
| Endpoint | Purpose |
|---|---|
| `GET /api/waste/report` | **Primary.** Full `WasteReport` (used by the frontend and the Coordinator) |
| `GET /api/waste/overview` | Summary, KPIs, alerts, limitations |
| `GET /api/waste/categories` | Waste-type rows and series |
| `GET /api/waste/food` | Food-waste section |
| `GET /api/waste/services` | Licensed-collector counts by class |
| `GET /api/waste/map?kind=` | GeoJSON of the location layers (`recycling_bins`, `ewaste`, `lighting_waste`, `disposal_sites`); separate because it is large. Layers still downloading are simply absent; their `status` is in `metadata.kinds` |
| `GET /api/waste/sources` | Provenance and per-source status |

A fully unavailable source is **not** an HTTP error: the report returns `status: "UNAVAILABLE"`, empty sections and `errors[]`. HTTP 500 is only for an unexpected agent crash.

## Analytics (all deterministic, from the table only)

- **Latest year** = the latest year in which total generated, recycled **and** disposed are all reported.
- **Year-on-year** uses exactly the previous calendar year; if it is missing, no comparison is shown (never a "nearest" year).
- **Overall recycling rate** = recycled ÷ generated × 100 (1 dp), with NEA's rounded figure carried alongside (`published_value`). Rate changes are in percentage points.
- **Rate excluding construction & demolition** = (recycled − C&D recycled) ÷ (generated − C&D generated). Cross-check: this reproduces NEA's published 2023 figure of 45 % (45.2 %).
- **Waste types**: share of generated / disposed, recycling rate (computed; published where it exists), year-on-year change, ranking by tonnes disposed.
- **Food waste**: generated, recycled, disposed, rate, share of all waste generated / disposed, full series.
- **Data-quality checks** (tolerances derived from the source's rounding): generated = recycled + disposed; the 14 types sum to each block total; published rate ≈ computed rate. Large year-on-year jumps (≥ 40 % and ≥ 100,000 t) are listed, not removed.
- **Alerts** (only `LOW` / `MODERATE`; statistics never raise `HIGH`): disposal at a series high; recycling rate ≥ 5 pp below its published peak; large streams (≥ 500,000 t) recycled < 35 %; failed consistency checks; stale statistics; degraded sources.
- **Unavailable by design:** domestic/non-domestic split, per-capita, landfill capacity, truck tracking, bin fill levels, forecasts - listed in `unavailable_metrics` with reasons.

## Agent and report

`WasteManagementAgent` consumes the structured analytics and writes only a deterministic summary and eight rule-based answers
(latest picture, generation trend, recycling, disposal, least-recycled types, food waste, services & infrastructure, what cannot be assessed).
Every sentence is assembled from report values (a test verifies each stated number traces to the report). No LLM text is generated, so none can invent a statistic.
Cross-domain reasoning is **not** done here.

`overall_risk` is always `UNKNOWN`: official waste data cannot support a risk claim, and the module never reports "LOW" it cannot measure.
`status` is `STATISTICS_AVAILABLE`, `PARTIAL` or `UNAVAILABLE`. Confidence: `high` = statistics OK, all checks pass, ≥ 5/6 sources OK; `medium` = statistics OK otherwise; `low` = no statistics.

### Coordinator
`collect_reports` runs `run_waste_agent()` after Water; `domain_status["waste"]` carries the headline metrics (statistics year, tonnes generated/recycled/disposed, recycling rate and change, food recycling rate, licensed collectors, infrastructure locations, data-kind label).
Waste does **not** affect city status, risk escalation, impacts or coordinator confidence, and there is no cross-domain rule for it. A failure becomes `{"available": false}` plus a warning.

## ML decision: none

The only official waste time series are **annual (26 observations)**. A chronological train / validation / test split with a baseline comparison cannot produce trustworthy error estimates on that,
and waste totals move with economic activity and one-off events (2020). The module requires ≥ 48 observations (e.g. 4 years of monthly data); none exists as official open data.
`forecast.available` is `false` with the reason in the report; `is_ml_prediction` is always `false`. This matches `AGENTS.md`'s "no ML in MVP" constraint.

## What has and has not been verified

**Verified on the live services (first real run, 12 Oct 2026):**
- *Statistics table*: 60 rows, 4 blocks, years 2000-2025, 4 `na` cells, latest complete year 2025; KPIs match the published figures.
  All consistency checks passed except one rounding-boundary case (2013: published 62 % vs 61.5 % recomputed from tonnes rounded to 1,000), which the rate check now tolerates (0.1 pp slack).
- *General Waste Collectors*: 368 licensees, field ids `class_of_waste` / `Licensee_Name` confirmed, 11 class combinations, no unrecognised class values.
- *E-waste layer*: 718 points (not the 2 in the dataset preview), per-record dates 2021-12-31 to 2022-06-02, three programme names (the ALBA name appears with a missing space in some records).
- *Lighting-waste layer*: 2 points, dated 2019-09-30.

**Verified from the official dataset pages / previews:** existence, formats, sizes and update stamps of all six sources; the real feature layout of the bins, lighting, e-waste and disposal layers
(parsers are unit-tested on text copied verbatim from those previews; doing so found and fixed two parser bugs - see `test_real_*`).

**Not yet verified live:** the *recycling bins* (18.5 MB) and *waste disposal sites* downloads - both returned HTTP 429 in the first run, before the throttle/backoff/background loading above was added.
Re-run `python -m scripts.inspect_waste_sources` (about a minute without a key) to confirm them, including the full set of bin `NAME` values.

## Running

```bash
python -m scripts.inspect_waste_sources          # confirm all six live sources parse (~1 min without an API key)
python -m pytest tests/waste -q                  # 106 backend tests (offline, mocked transports)
uvicorn backend.app.main:app --reload            # then: GET http://localhost:8000/api/waste/report
```
Frontend: `cd frontend && npm run dev`, open `/infrastructure/waste` (Infrastructure → Waste Management).
