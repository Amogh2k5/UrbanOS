# UrbanOS Fire / Safety Module

## Data sources

1. **Singapore Civil Defence Force (SCDF) public incident reports**
   - Used for recent published fire-incident intelligence.
   - Source: https://www.scdf.gov.sg/home/about-scdf/media-room/latest-happenings
   - Important limitation: this is a public communications feed, not an operational dispatch feed. Absence of a published incident is never interpreted as proof that no real-world incident exists.

2. **data.gov.sg / SINGSTAT Fire Occurrences, Annual**
   - Dataset ID: `d_808473a208220960f07a0b064ef16bde`
   - Used only for historical fire-count context.
   - It cannot establish current incident location/status/severity.

3. **Singapore map**
   - Frontend uses the existing MapLibre + OpenStreetMap pattern already used by UrbanOS.
   - Incident markers are rendered only when verified coordinates are present in the source data. No coordinates are fabricated.

## Processing

SCDF article text is normalized and deterministic rules classify:
- status: ACTIVE / RESOLVED / UNKNOWN
- incident type
- severity only when strong source evidence exists
- conservative five-region grouping from explicit location text

No ML model is used.

## Backend

- `backend/app/safety/fire/models.py`
- `backend/app/safety/fire/rules.py`
- `backend/app/safety/fire/api.py`
- `backend/app/safety/fire/agent.py`
- `backend/app/main.py`
- `coordinator/city_agent.py`

Endpoints:
- `GET /api/fire/report`
- `GET /kpi/live/fire`

## Frontend

- `frontend/src/app/safety/fire/page.tsx`
- `frontend/src/app/safety/fire/FireMap.tsx`
- `frontend/src/services/api/index.ts`

The Fire page contains:
- Active / Critical / Today / Resolved KPIs
- Singapore map
- recent/active incident list
- incident details
- regional overview
- historical fire counts
- source/limitation state

## Tests

- `tests/fire/test_fire_rules.py`
- `tests/fire/test_fire_agent.py`

## Known limitations

- SCDF does not expose a public operational fire-dispatch feed through the sources used here.
- Current incident KPIs are therefore scoped to retrieved SCDF-published reports.
- Incident coordinates are not present in those reports by default; the map intentionally does not invent coordinates.
- OneMap geocoding can be added later behind credentials if incident-location geocoding is required.
