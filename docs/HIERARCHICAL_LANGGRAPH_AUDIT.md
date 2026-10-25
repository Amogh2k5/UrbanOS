# UrbanOS hierarchical LangGraph migration audit

## Final invocation hierarchy

The top-level `CityCoordinatorState` LangGraph owns collection, normalization,
city-level rules, recommendations, and `CitySituationReport` construction. Its
collection node dispatches registered domain graph adapters through a bounded
worker pool (5 workers, shared 30-second collection deadline). Each adapter
creates fresh call state and returns a `DomainGraphResult` with a normalized
`DomainStatus`, report state, warnings, errors, and duration. One domain error
or timeout is recorded against that domain and does not prevent completed
domains from being consumed.

The registry contains the fourteen required independent modules and also keeps
the existing `environment` graph as a compatibility producer. That combined
producer remains the source for the historical `environment` report and its
existing city-rule contribution. The new Weather and PM2.5 statuses are
additive. City-level risk and confidence rules continue to use the same ten
pre-migration report inputs (including the existing Environment aggregate),
so additional module statuses do not silently alter established risk logic.

## Registered domain graphs and nodes

| Domain | Workflow nodes | Data/behavior |
|---|---|---|
| Traffic | `LOAD_PREDICTIONS` → `AGGREGATE_ZONES` → `LOAD_LIVE_INCIDENTS` → `LOAD_LIVE_SPEEDS` → `ANALYZE_TRAFFIC` → `BUILD_REPORT` | Existing graph and report semantics retained |
| Transit | `fetch_transit_status` → `validate_transit` | Uses persisted LTA reference data and collected rail alerts; missing summary becomes unavailable |
| Roads | `fetch_roads` → `validate_roads` | Uses the existing bounded/stale-aware Roads aggregator; missing active-work count becomes unavailable |
| Weather | `fetch_weather` → `validate_weather` | Uses the NEA client with fixture fallback disabled; only a confirmed live forecast is assessed |
| PM2.5 | `fetch_pm25` → `validate_pm25` | Uses the shared NEA observation snapshot; absence of regional numeric readings becomes unavailable |
| Flood | `LOAD_PAST_EVENTS` → `FETCH_SG_RAINFALL` → `FETCH_SU_FORECAST` → `FETCH_PUB_ALERTS` → `FETCH_NEA_WEATHER` → `ASSESS_RISK` → `BUILD_REPORT` | Preserved as its own compiled graph |
| Energy | `ingest_energy_data` → `build_report` | Reuses existing Energy sources and processing |
| Water | `ingest_water_data` → `analyze_water` → `build_report` | Preserved as its own graph |
| Waste | `ingest_waste_data` → `analyze_waste` → `build_report` | Preserved as its own graph |
| Land | `ingest_land_data` → `analyze_land` → `build_report` | Preserved as its own graph |
| Housing | `ingest_housing_data` → `build_report` | Reuses source and processing functions |
| Construction | `ingest_construction_data` → `build_report` | Reuses source and processing functions |
| Crime | `ingest_crime_data` → `analyze_crime` | Crime function and processing are now invoked inside the domain graph |
| Fire | `ingest_fire_data` → `analyze_fire` → `build_report` | StateGraph builder is compiled at the shared adapter boundary |

The registry's `environment` compatibility workflow retains its existing
`prepare_inputs` → `predict_pm25` → `predict_weather` → `build_report` graph.
Weather and PM2.5 are separately registered because the existing module
producers now expose those real source outputs; they do not reinterpret the
combined forecast as live observations.

## Shared interface and failure behavior

`BaseDomainGraph.invoke(initial_state, config, timeout_seconds)` accepts a
fresh mapping per call and normalizes dict/Pydantic/domain-model reports to the
shared `DomainStatus`. Legacy uncompiled `StateGraph` objects are compiled at
registration. Missing reports, malformed serialized reports, explicit
unavailability, and thrown exceptions all produce unavailable statuses with
explicit error text. The coordinator applies a shared deadline while source
clients retain their transport-specific limits. Python cannot forcibly stop a
synchronous worker that has already entered a provider call; such a worker may
finish after the coordinator has returned its timeout result.

The environment compatibility status and established city rules are retained.
Additional Weather, PM2.5, Transit, and Roads statuses are included in the
report without changing the city-rule input set or thresholds. Transit and
Roads use actual stored/aggregated data; if required summary measurements are
missing, their graphs return unavailable rather than estimated values.

## Frontend cache and preload

`frontend/src/services/api/index.ts` now shares successful lightweight domain
responses for short domain-specific TTLs and coalesces same-resource in-flight
requests by canonical URL. A manual refresh bypasses cached values and replaces
the canonical cache entry; out-of-order older requests cannot overwrite a
refresh result. Failed requests are not cached. PM2.5 KPI requests preserve
their 30-second abort boundary while using the common cache.

Once `/api/overview/city` has rendered, Overview starts a background preload of
Weather KPI, PM2.5 KPI, and Transit status with a maximum of two concurrent
requests. Each preload failure is isolated. Large maps, historical datasets,
and detail reports are not included. Existing page-level refresh actions remain
intact, and response freshness fields continue to come from the API.

## Tests and remaining limitations

Focused adapter/coordinator baseline initially exposed duplicate import
identities for `coordinator.city_agent` and `backend.app.coordinator.city_agent`.
The test conftest now aliases them to one module so test provider patches
intercept registered callbacks. It also stubs only the added domains at the
provider boundary with explicit unavailable responses.

Focused verification passed: `python -m pytest tests/intelligence/test_domain_graph.py tests/intelligence/test_coordinator.py tests/test_city_coordinator.py -q`
reported 69 passed. The City Report handler contract test invokes the registered
route endpoint directly and stubs the cache accessor, keeping it offline and
focused on the response contract. `python -m pytest tests -q --ignore=tests/test_api_pm25_prediction.py -k 'not test_city_report_response_structure'`
was attempted; it reached the existing
`tests/intelligence/test_alert_sources.py::TestTrafficAlerts::test_valid_incidents_are_returned_with_real_fields`
and stopped in Windows Proactor event-loop `socketpair()` initialization while
a pre-existing traffic statistics refresh thread was scanning its SQLite
table. The PM2.5 prediction integration file was excluded because its endpoint
performs expensive synchronous prediction work. These are not reported as
passing suites.

Frontend verification passed: all 242 Vitest tests, `npm run typecheck`, and
`npx next build --webpack`. The default `npm run build` path hit an internal
Turbopack subprocess panic while parsing `maplibre-gl.css`; the Webpack build
completed successfully.

The remaining runtime limitation is that a timed-out synchronous provider
thread cannot be terminated by `concurrent.futures`; graph-level transport
timeouts remain important. The `environment` compatibility graph remains
registered alongside the fourteen required module graphs to preserve the
current report contract.
