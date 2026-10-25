# UrbanOS system reliability audit

Audit date: 2026-10-25. This records code-path and mocked-test findings; no government API was stress-tested. The existing working tree was already heavily modified before this audit, so this document separates verified current behavior from changes made for this audit.

## Root causes and verified behavior

1. **Flood 403 source path was obsolete.** `FloodAlertsApiClient` used `https://api.data.gov.sg/v1/environment/flood-alerts` and Bearer authentication, then expected a legacy payload shape. The current official PUB dataset documents `https://api-open.data.gov.sg/v2/real-time/api/weather/flood-alerts`, optional `x-api-key`, and `data.records[].item.readings[]`. The adapter now uses that path, preserves source timestamps/coordinates, accepts a valid empty `records` list, and rejects malformed payloads rather than calling them “no alerts.” The optional configured key is sent as `x-api-key`. Source: [official PUB Flood Alerts API](https://developers.data.gov.sg/datasets?formats=API&resultId=d_f1404e08587ce555b9ea3f565e2eb9a3).
2. **Startup side effects are guarded.** `backend/app/main.py::_build_app` constructs clients, stores, and scheduler objects but does not start collectors, warm-up functions, coordinator runs, or schedulers. Prediction/live service constructors do not start workers; worker startup is explicit. Mocked startup tests assert no HTTP calls or worker starts.
3. **Overview is cache-only.** `GET /api/overview/city` peeks the city report and module-local caches, then emits all 14 canonical cards with unavailable states where no cache exists. It does not call domain fetchers or the coordinator. `GET /api/overview/city-narrative` only peeks the coordinator cache. `GET /api/city/report` is the explicit full coordinator trigger.
4. **Module detail is on demand.** `GET /api/overview/module/{module_id}` dispatches to the requested module fetcher. Traffic, Fire, Flood, and Crime also load their own relevant alert/statistics source. The regression test proves a Water request calls only the Water workflow; source-level dependencies remain specific to the chosen module.
5. **Chat cold-cache routing is bounded.** A single-domain question uses that domain summary with an 8-second fetch budget; a warm coordinator report is read from cache. Chat does not start the full coordinator on a cold cache. LLM work has a separate 15-second budget.
6. **Coordinator hierarchy remains intact.** The coordinator invokes registered domain graphs via `BaseDomainGraph` with fresh input state and bounded pool size (5) and a 30-second coordinator deadline. Domain failures are recorded as unavailable and do not erase other results. A legacy `environment` aggregate graph remains in the report for compatibility; the public Overview card roster is still exactly 14.

## Domain verification matrix

The API/UI columns distinguish automated contract checks from browser verification. No real browser session was available during this audit. Live source status is not inferred from adapter registration.

| Domain | Source / state evidence | Domain API path | API verified | UI verified | Remaining limitation |
|---|---|---|---|---|---|
| Traffic | LTA traffic adapter and local prediction/observation store; live state depends on credentials and collection | `/api/mobility/traffic/report` | Focused coordinator and on-demand tests | Card rendering automated; browser unverified | No live LTA request in this audit |
| Roads | LTA road works/openings feeds and cached aggregator snapshot | `/api/mobility/roads/analytics/summary` | Overview and domain graph tests | Card rendering automated; browser unverified | Live provider freshness unverified |
| Transit | LTA reference data and alerts in local store; scheduler is not auto-started | `/api/mobility/transit/status` | Startup/on-demand tests | Card rendering automated; browser unverified | No live LTA request in this audit |
| PM2.5 | NEA live adapter plus stored observations | `/kpi/live/pm25`, `/api/overview/module/pm25` | Mocked source and on-demand tests | Card rendering automated; browser unverified | Live NEA response not checked |
| Weather | NEA forecast adapter | `/kpi/live/weather`, `/api/overview/module/weather` | Mocked source and on-demand tests | Card rendering automated; browser unverified | Live NEA response not checked |
| Flood | PUB Flood Alerts via data.gov.sg; new official v2 path; no live request made | `/kpi/live/flood`, `/api/overview/module/flood` | Mocked v2, empty, malformed, 403 tests | Card rendering automated; browser unverified | Current live availability unverified |
| Fire | SCDF incident source and local report cache | `/api/fire/report`, `/api/overview/module/fire` | Alert-source tests | Card rendering automated; browser unverified | Live source availability unverified |
| Crime | data.gov.sg annual aggregates; not an incident-level live feed | `/api/crime/report`, `/api/overview/module/crime` | Alert-source and normalization tests | Card rendering automated; browser unverified | Dataset freshness varies by publication |
| Water | PUB/data.gov.sg source adapters and cached report | `/api/water/report`, `/api/overview/module/water` | Focused Water and on-demand tests | Card rendering automated; browser unverified | Provider availability not live-checked |
| Waste | data.gov.sg dataset adapters and cached report | `/api/waste/report`, `/api/overview/module/waste` | Reliability and domain tests | Card rendering automated; browser unverified | Provider availability not live-checked |
| Energy | EMA/data.gov.sg source adapters and cached report | `/api/infrastructure/energy/report`, `/api/overview/module/energy` | Reliability and domain tests | Card rendering automated; browser unverified | Provider availability not live-checked |
| Land | URA/data.gov.sg source adapters and cached report | `/api/planning/land/report`, `/api/overview/module/land` | Domain graph tests | Card rendering automated; browser unverified | Provider availability not live-checked |
| Housing | HDB/data.gov.sg datasets and cached report | `/api/planning/housing/report`, `/api/overview/module/housing` | Housing source reliability tests | Card rendering automated; browser unverified | Dataset publication lag remains |
| Construction | BCA Green Mark GeoJSON plus validated pipeline datasets | `/api/planning/construction/report`, `/api/overview/module/construction` | Empty-response/cache tests | Card rendering automated; browser unverified | Empty/discontinued map data remains honestly unavailable |

All 14 cards are asserted in `tests/test_on_demand_loading.py`; selected detail endpoints and source adapters have mocked tests. This audit did not prove live data availability or visually inspect every detail page.

## Cache and failure handling

Shared upstream support is in `backend/app/upstream.py`: per-key single-flight loads, TTL and error TTL, bounded 429 retry with exponential jitter, and `Retry-After` parsing. Adapters own their own keys and freshness rules. The Flood adapter caches successful live reads for 30 seconds and errors for 60 seconds; 403 is not retried. Domain-specific source caches remain separate where their contracts differ. Offline fixtures are labeled as fixtures; live routes in the inspected Flood path explicitly disable fixture fallback.

## Verification results

- Baseline focused backend command: `python -m pytest tests/test_startup_warmup_isolation.py tests/test_on_demand_loading.py tests/intelligence/test_coordinator.py tests/test_city_coordinator.py tests/test_upstream_reliability.py -q --disable-warnings --maxfail=1` — **79 passed**.
- Post-change focused command: `python -m pytest tests/test_upstream_reliability.py tests/test_flood_agent_v3.py tests/test_startup_warmup_isolation.py tests/test_on_demand_loading.py -q --disable-warnings --maxfail=1` — **43 passed**.
- Frontend: `npm test -- --reporter=dot` — **235 passed in 7 files**; `npm run typecheck` — passed.
- Full backend collection from repository root fails before tests run for five ML test modules because imports such as `src.data_validation` are not resolvable from the root. A broader `pytest tests` attempt did not finish within the bounded run and was stopped; it is not counted as passing.
- Default `npm run build` failed in Turbopack child-process startup on `maplibre-gl.css`. `npm run build -- --webpack` compiled and typechecked but failed while tracing output due sandbox `EPERM` creating a directory beneath `.next/standalone`. Production build therefore remains unverified in this environment.
- Backend server startup process was launched on port 8765, but HTTP smoke requests were blocked by sandbox socket permissions. The process was stopped; `/health` and live HTTP behavior remain unverified here.
- No live upstream rate-limit or Flood API requests were used.

## Exact local run commands

From `C:\projects\UrbanOS` in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

In another PowerShell window:

```powershell
Set-Location frontend
npm run dev
```

The frontend defaults to `http://localhost:3000`; the backend defaults to port `8000`.
