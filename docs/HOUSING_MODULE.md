# UrbanOS Planning → Housing

## Purpose
Singapore Housing Intelligence: source-backed housing stock and HDB resale analysis. This is a periodic-statistics dashboard, not a property marketplace. No ML model, affordability score, supply-demand score, or synthetic feed is used.

## Architecture
`Official HDB/data.gov.sg datasets → housing data layer → deterministic processing → HousingAgent → HousingReport → /api/planning/housing/report → Planning/Housing dashboard`

The existing `TopNav` already exposes `/planning/housing`. The API is registered from `backend/app/main.py`. The uploaded repository snapshot does not contain the backend `coordinator/city_agent.py` package referenced by its `/api/city/report` handler, so this change does not invent or replace a coordinator architecture. Housing exposes a structured report endpoint that can be consumed by a coordinator when that package is present.

## Data sources implemented
The data client queries the data.gov.sg datastore API:
`https://data.gov.sg/api/action/datastore_search?resource_id=<dataset_id>&limit=32000`

- HDB, Median Resale Prices for Registered Applications by Town and Flat Type — `d_b51323a474ba789fb4cc3db58a3116d4`; quarterly town/flat-type median price rows.
- HDB, Resale Applications by Flat Type — `d_02aa4bb51bc674f3a2d0b9bb6911d934`; used only when returned schema contains an interpretable application-count field.
- HDB, HDB Property Information — `d_17f5382f26140b1fdae0ba2ef6239d2f`; block/street, year completed, total dwelling units and other stock attributes.

Official catalogue pages:
- https://data.gov.sg/datasets/d_b51323a474ba789fb4cc3db58a3116d4/view
- https://data.gov.sg/datasets/d_02aa4bb51bc674f3a2d0b9bb6911d934/view
- https://data.gov.sg/datasets/d_17f5382f26140b1fdae0ba2ef6239d2f/view
- HDB market releases: https://www.hdb.gov.sg/about-us/news-and-publications/press-releases
- URA private-residential releases: https://www.ura.gov.sg/news/
- SingStat: https://www.singstat.gov.sg/

The HDB resale dataset catalogue shows coverage from Q2 2007 to Q2 2026 (last catalogue update 13 Aug 2026). HDB Property Information catalogue shows coverage through Dec 2025. Periods shown by the app are derived from records returned at request time, not hardcoded.

## Data deliberately not fabricated
- HDB Resale Price Index is not substituted with the unweighted mean of town/flat-type medians. The chart labels its own derived summary accurately.
- Median rent is unavailable unless a verified configured source is reachable.
- URA private residential price/rental indices, vacancy and pipeline are marked unavailable because this implementation did not verify a stable unauthenticated structured endpoint for those series. Official URA releases are linked for reference.
- SingStat household/dwelling indicators are marked unavailable until a machine-readable table/API is verified and wired.
- HDB Property Information in this dataset does not supply verified lat/lon, so no map markers or fake map are generated.
- A missing or failed upstream dataset remains unavailable/partial; it is never converted into zero.

## API
- `GET /api/planning/housing/report`
- `GET /api/planning/housing/report?refresh=true`
- `GET /api/planning/housing/sources`

The report is cached for 30 minutes after partial/available results and 5 minutes after fully unavailable results. `DATA_GOV_SG_API_KEY` is optional and read from the environment; no key is stored in code.

## Verification
- Unit tests cover period selection, numeric/missing-value handling, partial data, stock normalization and no fabricated map features.
- Python syntax compilation is checked as part of packaging.
- Full runtime API/network verification and browser production build depend on installing project dependencies and reaching the upstream endpoints in the deployment environment.
