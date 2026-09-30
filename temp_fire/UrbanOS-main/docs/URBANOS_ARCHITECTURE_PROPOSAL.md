# UrbanOS — Technical Architecture Proposal

A comprehensive, code-free architecture proposal for the UrbanOS multi-agent smart-city platform. Every major decision includes rationale.

---

## 1. Overall System Architecture

### Recommended layered architecture

```
┌──────────────────────────────────────────────────────────────┐
│  PRESENTATION LAYER (Next.js + React + Map)                  │
│  Ops Dashboard · Situation Report Viewer · What-if Studio    │
└──────────────────────────────────────────────────────────────┘
                              │ REST / WS / SSE
┌──────────────────────────────────────────────────────────────┐
│  APPLICATION LAYER (FastAPI)                                 │
│  API Gateway · Auth · Session · Report Orchestration         │
│  Orchestration Engine (What-if, Safe Routing)                 │
└──────────────────────────────────────────────────────────────┘
                              │
┌──────────────────────────────────────────────────────────────┐
│  AGENT LAYER                                                 │
│  Traffic │ Weather │ Flood │ Pollution │ Electricity │       │
│  City Coordinator Agent (LLM + tool calling)                 │
└──────────────────────────────────────────────────────────────┘
                              │ tool calls
┌──────────────────────────────────────────────────────────────┐
│  DOMAIN SERVICE LAYER (Python use-cases)                      │
│  Forecasters · Impact Analyzers · Conflict Resolvers          │
│  Route Builders · Persistence Gateways                       │
└──────────────────────────────────────────────────────────────┘
                              │
┌──────────────────────────────────────────────────────────────┐
│  DATA & ML LAYER                                             │
│  Ingestion Workers · Historical Store (Postgres)              │
│  Feature Store · ML Model Registry · Predict Job Queue       │
│  Live API Cache (Redis) · TimescaleDB                        │
└──────────────────────────────────────────────────────────────┘
                              │
┌──────────────────────────────────────────────────────────────┐
│  EXTERNAL SOURCES                                            │
│  LTA DataMall · NEA · PUB · EMA                              │
└──────────────────────────────────────────────────────────────┘
```

### Key architectural patterns

| Pattern | Why |
|---|---|
| **Layered + hexagonal** | Keeps agents/ui independent of storage and external APIs; swap-able models. |
| **Independent domain agents** | Mirrors domain ownership; parallel dev; aligns with bounded contexts. |
| **Coordinator-as-orchestrator** | One brain merges multi-domain signals — conflict resolution in one place. |
| **Tool-calling agents** | LLM stays declarative; deterministic logic lives in Python tools (safer, testable, cheap). |
| **Event-sourced observations** | Every raw observation persisted; replays and ML retraining possible. |
| **Async ingestion workers** | Pull from slow SG APIs without blocking request path. |

### Why NOT a single monolithic LLM prompt

A single mega-prompt cannot be unit tested per-domain, costs tokens per turn to re-explain models, cannot resolve conflicts in a principled way, and hides determinism inside a black box. Domain agents give localized reasoning; the Coordinator does conflict resolution with explicit rules and records its rationale.

### Deployment (initial, Windows-only team)

- Docker Compose for local dev (FastAPI, Postgres, Redis, workers, Next frontend).
- Stateless API allows future Kubernetes move.
- Postgres + TimescaleDB to avoid introducing Kafka for MVP.
- **No Kafka/event bus in MVP** — Postgres LISTEN/NOTIFY + Redis pub/sub sufficient. Add Kafka in Phase 3.

---

## 2. Domain-Agent Architecture

Each domain agent (Traffic / Weather / Flood / Pollution / Electricity) is structured identically so the team can parallelize.

### Internal structure of a domain agent

```
DomainAgent (FastAPI-resident service)
├── LLMReasoningModule        (small system prompt + few-shot if needed)
├── ToolCatalog               (declared functions agent may call)
├── StateReader               (pull from Postgres feature views + Redis cache)
├── ExternalAPIAdapter        (rate-limit, retry, normalizer)
├── DomainForecaster          (ML model or simple baseline)
├── ImpactAnalyzer            (cross-domain hooks, registered per agent)
├── RecommendationBuilder     (produces {action, severity, rationale, confidence})
└── AgentEnvelope             (JSON message contract)
```

### Responsibilities per agent (data-only, no LLM in ingestion path)

| Agent | Pull sources | Tools expose | LLM use | ML use |
|---|---|---|---|---|
| Traffic | LTA Traffic Speed, Traffic Flow | `get_live_traffic`, `predict_congestion(t,h)`, `get_corridor_state` | Summarize state | **Yes** (congestion regression/forecast) |
| Weather | NEA rainfall/temp/humidity/wind/2h/24h/4-day | `get_weather`, `get_rainfall_grid`, `precip_next_2h` | Summarize | **Light** (bias-correct NEA forecast vs history) — optional, MVP uses NEA forecast directly |
| Flood | PUB water level + flood-prone areas + NEA rainfall | `get_water_levels`, `flood_risk_area`, `rainfall_in_basin` | Summarize + explain | **Yes** (water-level + flash-flood classifier) |
| Pollution | NEA PM2.5, PSI | `get_psi`, `pm25_hotspot`, `predict_psi_24h` | Summarize | **Maybe** (temporal model of PSI 24h; only if NEA doesn't publish forecast — **VERIFY**) |
| Electricity | EMA demand/consumption/peak | `get_demand`, `predict_demand_24h`, `peak_risk_window` | Summarize | **Yes** (demand forecasting, particularly peak windows) |

### Why this split

- **LLM stays only where it adds value**: explanation, conflict drafting, natural-language reports. Numeric tasks go to tools.
- **ML only where prediction is non-trivial AND not already solved by the data provider**.

### Recommendation contract (emitted by every agent)

```jsonc
{
  "domain": "flood",
  "timestamp": "2026-08-17T08:30:00+08:00",
  "scope": {"area": "Bukit Timah canal", "lat":..., "lng":...},
  "current_state": {...},                 // structured facts
  "prediction": {...},                   // structured or null
  "recommendations": [
    {
      "id": "F-001",
      "action": "Activate pumps at Bukit Timah",
      "severity": "HIGH",
      "confidence": 0.78,
      "effective_window": "30-90 min",
      "conflicts_with": ["E-004"],        // e.g., pump uses power
      "rationale": "Rainfall intensity 35mm/h upstream..."
    }
  ],
  "evidence": [{"source": "PUB", "ref": "..."}],
  "schema_version": "1.0"
}
```

### Shared base class

Define an abstract `BaseDomainAgent` exposing `ingest_tick()`, `snapshot()`, `analyze()`, `analyze_whatif(scenario)`, `emit()`. Subclasses override only domain-specific logic. This reduces duplication and makes adding Mumbai/Bangkok later a matter of swapping adapters.

---

## 3. City Coordinator Architecture

The Coordinator is the orchestration brain. It does **not** call SG APIs directly — it only consumes DomainAgent outputs + shared tools.

### Coordinator job phases

1. **Collect** — request each domain agent envelope (parallel).
2. **Normalize** — project all recommendations to a common city model (lat/lng, time, severity scale 0-5).
3. **Build City Graph** — nodes = zones/segments/assets; edges = causal links (e.g., rain→flood→traffic; heat→demand; PSI→traffic advisory).
4. **Cross-domain impact** — propagate shocks across the graph (see §10).
5. **Conflict resolution** — reconciles contradictory recommendations.
6. **Priority ranking** — safety > life > infra > comfort.
7. **Draft report** — LLM synthesizes structured City Situation & Action Report.
8. **Publish** — emit report + write to `reports` table + push to dashboard.

### Conflict resolution strategy (explicit, not purely LLM)

| Conflict type | Resolution |
|---|---|
| Spatial overlap, different urgency | Higher severity wins; lower becomes conditional. |
| Resource contention (power for pumps vs. demand) | Compute net resource demand; if deficit, invoke electricity agent `peak_risk_window` to re-decide. |
| Contradictory traffic advice (divert vs. allow) | Prefer safer route; flag residual delay. |
| PSI advisory vs. traffic diversion | Optimize jointly: avoid low-lying flood roads even if PSI-exposed. |

Implement as **rule engine** (`rules/*.py`, pure functions) invoked by the Coordinator. LLM only describes result, does not decide safety.

### Coordinator outputs

- **City Situation Report (CSR)** — Markdown + JSON bundle stored in Postgres.
- **Action Plan** — ordered list of actions w/ owner placeholder (agency), severity, window, conflict notes.
- **Routing Layer** — occupancy grid + edge weights for safe-routing service.

### LLM sizing

- Use a frontier-tier model for the Coordinator (longer context, better synthesis).
- Use smaller/cheaper models per domain agent.
- Keep deterministic logic in tools — LLM never performs arithmetic or ranking.

---

## 4. Data-Ingestion Architecture

### Principles

- **Adapters own every API quirk** (paging, rate limits, auth, units, time zones → Asia/Singapore, nulls).
- **Idempotent writes**: each observation gets `(source, observed_at, station_id, metric)` natural key; upserts avoid duplicates.
- **Pull-based schedulers** in MVP (no webhook reliance — SG APIs are mostly pull REST).
- **Backpressure**: one worker queue (Redis streams in MVP, upgrade to Kafka later).

### Ingestion topology

```
Cron / APScheduler
   │
   ├── TrafficIngestor     ──> LTA Traffic Speed/Flow  ──> normalize ──> Postgres (raw + derived)
   ├── WeatherIngestor     ──> NEA endpoints           ──> ...
   ├── FloodIngestor       ──> PUB water level
   ├── PollutionIngestor   ──> NEA PSI/PM2.5
   └── ElectricityIngestor ──> EMA endpoints
   │
   └── All writes also push "event_key" to Redis pub/sub "observations"
        → live dashboard subscribers
```

### Caching strategy

- Redis caches latest observation per (source, metric, station) with TTL = refresh interval.
- Historical data never served from cache — query Postgres.

### Backfill service

A separate one-shot/backfill CLI imports CSV/historical files into the **same schema as live data** so ML training uses one unified table. **VERIFY** availability of historical exports per agency — several agencies publish daily/historical CSV (HDB, EMA, NEA) but format varies and must be confirmed.

---

## 5. Exact API vs Historical-Data Strategy

### Rule of thumb

| Use case | Use | Why |
|---|---|---|
| Live "now" state | Live API | Authoritative. |
| Trend / prediction / training | Historical (CSV/exports) + continuously persisted live | ML needs long series; live-only window too short. |
| What-if with counterfactuals | Historical patterns + simulation knobs | Live API cannot answer hypotheticals. |

### Per-domain strategy

#### Traffic
- **Live**: LTA DataMall Traffic Speed & Flow APIs (free, key-gated). **VERIFY** update frequency.
- **Historical**: LTA may not supply long-term CSV. **Risk**: we may have to *accumulate our own* by scraping live API on schedule for ≥3 months before training traffic models. Mark as MVP-blocking if prediction required.
- **ML**: Time-series congestion forecasting on accumulated flows. Requires ≥3-6 months data — **MVP uses heuristic + rule-based**, ML in Phase 2.

#### Weather
- **Live**: NEA rainfall/temp/humidity/wind/2-hour/24-hour/4-day forecasts.
- **Historical**: NEA publishes daily historical weather CSV back several years. **VERIFY exact endpoints and columns.**
- **ML**: For MVP, use NEA's own forecasts (no model). Optionally Phase 2 local-statistical bias correction vs historical NEA forecast errors.

#### Flood
- **Live**: PUB water-level (real-time), PUB flood-prone areas (static), NEA rainfall.
- **Historical**: PUB flood incident records (need to **VERIFY** availability/structure), NEA historical rainfall.
- **ML**: Two models — (a) short-term water-level prediction, (b) flash-flood classifier. Worth doing because PUB live data is dense and flood risk is domain-critical.

#### Pollution
- **Live**: NEA PM2.5 regional + PSI national.
- **Historical**: NEA publishes historical PSI/PM2.5 CSV since 2014 (need to **VERIFY download mechanism** — possibly via data.gov.sg).
- **ML**: PSI often has published forecasts; if not, a 24h temporal model is justified. **Verify NEA forecast policy** before committing to ML.

#### Electricity
- **Live**: EMA demand/consumption/peak.
- **Historical**: EMA publishes historical half-hourly demand data — **VERIFY granularity and licence.**
- **ML**: Demand forecasting is a well-solved regression task with strong seasonality; **highest ROI ML in this stack.** Train on ≥1 year historical and continuously refine.

### Where ML is clearly NOT needed in MVP

- Weather forecasting (NEA's forecast is the SOTA we can get for free).
- Pollution *if* NEA publishes forecast.
- Live "current state" of any domain (it's literally reported by the API).

### Where ML IS justified

1. **Electricity demand forecasting** — high value, low risk, clean data.
2. **Flood water-level + flash-flood classifier** — safety-critical, dense PUB sensor data.
3. **Traffic congestion forecast** — only AFTER accumulating 3-6 months (Phase 2).
4. **Pollution 24h** — only if NEA does NOT publish forecast.

---

## 6. Database Architecture and Schema

### Engine choice

- **PostgreSQL 16** with **TimescaleDB** extension for time-series tables. Rationale: one DB for both relational state and time-series; avoids running Influx/ClickHouse alongside. Hypertable partitioning on `observed_at`.
- **PostGIS** extension for geospatial (zones, corridors, flood polygons, sensor points).
- **Redis** for hot cache + pub/sub + job queue (Redis Streams).
- Optional `pgvector` later for embedding-based semantic search of historical reports.

### Why TimescaleDB over vanilla Postgres partitions

- Continuous aggregates for "last 5 min / hourly / daily" rollups materialized automatically.
- Compression on old chunks — years of weather data stays cheap.
- Schema still looks like Postgres for tooling.

### Core tables (illustrative, not final)

```
sources             (id, name, agency, licence, ingestion_cron, last_pulled, health)
locations           (id, type[station|zone|segment|grid], name, lat, lng, geom(geometry))
metrics             (id, name, unit, domain, description)

observations        -- TimescaleDB hypertable
  (id, source_id, location_id(int4, null ok), metric_id, observed_at timestamptz,
   value numeric, raw jsonb, ingested_at timestamptz)
   partitioned by observed_at; index (metric_id, location_id, observed_at desc)

forecasts           -- model outputs (also hypertable)
  (id, model_id, target_metric_id, location_id, horizon_min int,
   forecast_for timestamptz, value numeric, prob jsonb, generated_at timestamptz)

models              (id, name, version, domain, kind[regressor|classifier|ensemble],
                      path, metrics jsonb, trained_at, active boolean)

agents_state        (domain text primary key, last_envelope jsonb, last_run_at)

envelopes           (id uuid, domain, generated_at, payload jsonb)

reports             (id uuid, generated_at, scope jsonb, markdown text, action_jsonb,
                     slots jsonb, conflicts_jsonb, model_refs jsonb)

routing_graph       -- safe routing snapshot
  (id, generated_at, nodes jsonb, edges jsonb, weights jsonb)

whatif_runs          (id uuid, created_at, scenario jsonb, status, result jsonb,
                      started_at, finished_at)

api_keys            -- see §17
audit_log           -- see §17
sessions / users    -- see §17
```

### Geospatial strategy

- All locations stored w/ PostGIS `geometry`.
- Flood zones as polygons from PUB flood-prone data.
- Traffic corridors as `LineString` from LTA station IDs (**VERIFY** corridor definition LTA publishes).
- Use `ST_DWithin`, `ST_Intersects` for queries: "which locations within 2 km of heavy rainfall centroid".

### Retention & rollup

- Raw observations: 90 days hot, 7 years compressed.
- Hourly/daily rollups: permanent.
- Envelopes/reports: permanent.

### Indexing checklist

- `(metric_id, location_id, observed_at DESC)` everywhere time-series.
- GIN on jsonb fields we filter (`raw`, `action_jsonb.slots`).
- GiST on geometry.

---

## 7. ML Prediction Pipeline

### Pipeline stages

```
[Historical export CSV] ─┐
                         ├─► DatasetBuilder ─► FeatureStore ─► Trainer ─► Model Registry ─► Predictor Service
[Live persisted obs]    ─┘
```

### Components

- **DatasetBuilder**: builds clean training frames per metric from `observations` + rollups. Time-zone-aware, gap-filled (forward-fill then flag).
- **FeatureStore (light)**: tables `feature_groups(feature_group_id, name, sql_or_pandas_def, computed_at)` + materialized views of common features (lag, rolling, time-of-day, holiday flag, dew point, etc.). Avoid launching a separate Feast/Tecton install for MVP — Postgres materialized views suffice.
- **Trainer**: Python scikit-learn / XGBoost / LightGBM scripts invoked as batch jobs. **No deep learning recommended for MVP** — tabular SG data, modest volume; gradient-boosted trees win and stay reproducible.
- **Model Registry**: `models` table with versioning + `active` flag + metrics JSON.
- **Predictor Service**: exposes tool `predict_<domain>(horizon_minutes, location_id)` to agents. Reads `active` model, fetches features, returns prediction + confidence interval.
- **Scheduled predictions**: APScheduler job every N minutes writes rows into `forecasts` hypertable, so agents have cheap "last known forecast" without re-running model per call.

### Why no deep learning for MVP

- Reproducibility and debuggability trump marginal accuracy on small tabular datasets.
- Hardware cost / team bandwidth.
- Easy to upgrade later behind the predictor-service interface.

### Drift & monitoring

- Track prediction error vs realised observation; alert if MAE exceeds training-time threshold for N consecutive windows.
- Automatic backfill of new labelled data → monthly retrain job.

---

## 8. Agent Communication Protocol

### Transport

- **In-process** for MVP: agents are FastAPI sub-services in same process; communicate via Python function calls returning `Envelope` objects.
- **Upgradable to async** via Redis pub/sub or NATS without rewriting agents, because interface = envelope.

### Envelope (canonical)

Already shown in §2. Same shape for request from Coordinator to Agent:

```jsonc
{
  "type": "analyze_request",
  "request_id": "uuid",
  "issued_at": "...",
  "horizon_min": 120,
  "scope": {"area": "Central", "lat":..., "lng":...},
  "scenario": null            // or what-if override
}
```

Agent replies with the §2 envelope.

### LLM ↔ Tool interface

- Use OpenAI-style function-calling schema (works across models).
- Tools are **pure Python functions** registered with `name, description, JSON-schema params`.
- Tools **never** call the LLM. Tools can call DB/cache/predictor; results returned as JSON serializable.
- Every tool call logged to `agent_toolcalls(run_id, agent, tool, args, result, latency_ms)`.

### Protocol guarantees

- Idempotent: same `analyze_request` within 30s returns cached envelope.
- Bounded latency: each agent has a deadline (e.g., 4s); on timeout return last envelope + degrade flag.

---

## 9. Tool-Calling Architecture

### Categories of tools (per agent)

| Category | Example tools |
|---|---|
| Read state | `get_live_traffic`, `get_rainfall_grid`, `get_water_levels`, `get_psi`, `get_demand` |
| Predict | `predict_congestion`, `flood_risk`, `predict_demand_24h`, `predict_psi_24h?` |
| Cross-domain hook (read-only) | `weather.get_rainfall_for_polygon`, `electricity.get_peak_window` |
| Spatial | `locations_in_radius`, `intersects_flood_zone` |
| History | `historical_p95(metric, location, last_days)` |

### Constraints

- Tools are explicitly exposed to specific agents (allow-list in agent config). Prevents agent overreach.
- A tool manifest is a **first-class artefact** in repo (`tools/manifest.yaml`), so security review is easy.

### Why function calling, not generic code execution

- Determinism and security; rate-limit per tool; easy to mock in tests.

---

## 10. Safe-Routing Architecture

### Goal

Given current/predicted city state, return safest route(s) avoiding flood, congestion spike, pollution hotspots, blackout risk zones.

### Architecture

- Build a **routing graph** from OpenStreetMap (Singapore extract) cached locally. **VERIFY** allowable OSM use; alternatively LTA road network dataset — licensing to confirm.
- **Graph nodes**: intersections; **edges**: road segments with static attributes (length, road class, speed limit).
- **Dynamic edge costs** layered on top:
  - Flood polygon intersection → cost = ∞ (or large) for affected edges.
  - Predicted congestion multiplier from Traffic agent.
  - Pollution-weighted penalty (configurable per use-case — e.g., pedestrian).
  - Power-outage risk factor (low impact for routing in MVP; flag lights/signals disabled).
- Compute with Dijkstra / A*. Use `networkx` for MVP; consider `OSRM` or `Valhalla` server later for speed.
- **Modal variants**: walk / cycle / drive / transit — selected subgroup of edges per mode.

### Outputs

- Route geometry (GeoJSON), expected duration, safety score, list of avoided hazards.
- **Return multiple Pareto-optimal routes** (fast vs safest) so Coordinator/dashboard can illustrate trade-offs.

### What-if integration

Safe-routing service accepts the city-state snapshot as input, so a What-if scenario recomputes routes against the simulated snapshot.

### Verification needed

- Whether LTA publishes routable road graph or we must derive from OSM.
- Licensing of OSM tiles for the map display (requires attribution; **VERIFY** for commercial dashboard).

---

## 11. What-If Simulation Architecture

### Use cases

- "If rainfall intensity doubles for next 2 h, which zones go flood-risk?"
- "If PSI exceeds 150, what traffic diversions minimize exposure?"
- "If peak demand climbs 10%, what load-shed is safe?"

### Design

- A **Scenario** is a JSON document of overrides + hypotheses:
  ```jsonc
  {
    "horizon_min": 120,
    "inputs": {"rainfall_intensity_factor": 2.0, "psi_floor": 150},
    "domain_actions": [],
    "policy": {"safety_first": true}
  }
  ```
- Coordinator fans scenario out to each agent's `analyze_whatif(scenario)` which runs **its domain predictor + impact analyzer** with overridden features (no external API calls).
- Responses aggregated; conflict resolution re-run; new CSR generated.
- Stored under `whatif_runs` with full reproducibility: model versions, scenario, env.

### Determinism

Same scenario + same model versions = identical result (deterministic tools; LLM only summarizes). Persist a "deterministic_payload" alongside the report so the team can diff scenarios without LLM noise.

### Costs

What-ifs can be pure-Python fast (no API calls). Concurrency limited by predictor cost.

---

## 12. FastAPI Backend Architecture

### Module layout

```
backend/
├── app/
│   ├── main.py                    (FastAPI factory)
│   ├── api/                       (HTTP routers)
│   │   ├── city.py                (state, reports, what-if endpoints)
│   │   ├── traffic.py / weather.py / ...
│   │   ├── routing.py
│   │   ├── admin.py               (sources, models, jobs)
│   ├── agents/                    (domain agents + coordinator)
│   ├── services/
│   │   ├── ingestors/
│   │   ├── predictors/
│   │   ├── routing/
│   │   ├── reports/
│   ├── adapters/                 (per-source API clients)
│   ├── db/                        (sqlalchemy + alembic)
│   ├── core/                      (config, logging, security, deps)
│   ├── tools/                     (LLM-callable Python functions)
│   └── workers/                   (apscheduler jobs, workers)
├── tests/
├── alembic/
└── pyproject.toml
```

### Key FastAPI decisions

| Decision | Why |
|---|---|
| Async I/O endpoints | High concurrency for dashboard + SSE subscriptions. |
| SQLAlchemy 2.0 async + `asyncpg` | Standard; great Postgres support. |
| Alembic migrations | Version-controlled schema. |
| Pydantic v2 for envelopes | Fast + validated agent contracts. |
| APScheduler (in-process) for MVP | No extra Celery/RQ install. Later migrate to Celery/RQ. |
| Background Tasks API for one-off jobs | Simpler than queue for short ops. |
| OpenTelemetry-ready (tracing hooks) | Phase 2 prod observability. |
| Structured JSON logging (`structlog`) | Operations-friendly. |
| Dependency injection via FastAPI `Depends` | Easy test mocking. |
| Health/readiness endpoints | Container orchestration later. |

### Background jobs

- AP scheduler pulls each source per cadence config.
- Prediction jobs run N-minutely per `active` model.
- Report generation job every 5 min (or on-demand).
- What-if jobs queue (in-process + Redis list).

### Streaming to dashboard

- SSE for live city state pushes (browser-friendly).
- WebSocket optional for richer what-if interactions.

---

## 13. Next.js Frontend Architecture

### Stack

- Next.js 14 (App Router) + React 18 + TypeScript.
- Tailwind + shadcn/ui-style component basis.
- Map: **MapLibre GL JS** (open-source, no token) over vector tiles served by self-hosted tileserver or MapTiler Plan. **VERIFY** tile licensing for commercial dashboard.
- Charts: ECharts or Recharts (time-series + heatmap).
- State: TanStack Query for server state, Zustand for UI state.

### Pages

- **Ops Dashboard** — multi-panel: map + per-domain tiles + City Situation Report panel + action checklist + alerts timeline.
- **Domain deep-dive** — switch tabs per domain with charts + recommendations.
- **What-if Studio** — form scenario, run, side-by-side compare.
- **Route Planner** — origin/destination → safe routes shown on map.
- **Reports archive** — search/filter past CSRs.
- **Admin** — sources/models/health.

### Performance

- `revalidate` ISR for read-only archived reports.
- SSE connection manager with auto-reconnect.
- Map view state synced via URL params (shareable links).

### Auth

- NextAuth (Auth.js) integrated with backend JWT.
- Role-based: `ops_lead`, `analyst`, `viewer`, `admin`.

---

## 14. Project / Repository Folder Structure

### Recommended: **monorepo**

**Why monorepo** over polyrepo for MVP-team:
- Shared envelopes + generated clients.
- One PR can change schema + API + frontend.
- Simpler CI for small team.

```
UrbanOS/
├── .github/
│   └── workflows/         (CI: lint, test, build, migrate)
├── backend/
│   ├── app/
│   ├── alembic/
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/app/
│   ├── src/components/
│   ├── src/lib/
│   └── package.json
├── ml/
│   ├── datasets/           (dataset builders)
│   ├── features/           (feature group defs)
│   ├── training/           (per-model trainers)
│   ├── evaluation/
│   ├── registry/
│   └── predict/            (predictor entrypoints)
├── infra/
│   ├── docker/             (compose files)
│   ├── dockerfiles/
│   ├── nginx/              (reverse proxy later)
│   └── k8s/                (future)
├── data/
│   ├── raw/                (ingestored exports; git-LFS or excluded)
│   ├── external_csv/       (historical exports)
│   └── geo/                (GeoJSON / shapefiles)
├── scripts/
│   ├── backfill/
│   └── seed/
├── docs/
│   ├── adr/                (Architecture Decision Records)
│   ├── api_contracts/
│   └── runbooks/
├── tools/registry/         (LLM tool manifest + shared schemas)
├── .editorconfig
├── pyproject.toml          (workspace)
├── package.json            (workspace)
├── docker-compose.yml
└── README.md
```

### Keep these out of git
- `.env` / API keys.
- Raw historical data > 10MB (use object storage later; for MVP local-only).
- Model artefact binaries (use a `models/` dir on disk + registry table; later S3-compatible bucket).

---

## 15. Data Storage Strategy

| Tier | Store | Purpose | TTL |
|---|---|---|---|
| Hot | Redis | latest observation per metric+station; SSE counters | minutes |
| Warm | Postgres TimescaleDB `observations` | last 90 days hot partitions | 90 days then compressed |
| Cold | Postgres TimescaleDB compressed chunks | long archive | 7 years |
| Rollups | Materialized continuous aggregates | hourly/daily stats | permanent |
| Geospatial | PostGIS | zones, corridors, sensors | permanent |
| Reports | Postgres `reports` (jsonb) | CSRs | permanent |
| What-if | Postgres `whatif_runs` | scenarios + results | permanent (or 1yr) |
| Model artifacts | Local FS / future object store | versioned models | keep last 3 per model id |
| Logs | JSON stdout; collected externally | audit | 90 days |

### Backups

- `pg_dump` nightly (logical) + WAL archiving if RPO < 1h.
- Encryption at rest: Postgres TDE not native → use volume encryption (LUKS/BitLocker for Windows dev).
- Restore drills monthly.

---

## 16. Model Strategy

### Model taxonomy

| Kind | Used for | Recommended | Why |
|---|---|---|---|
| Deterministic rule engine | Conflict resolution, severity scaling | Plain Python rules | Testable, auditable. |
| LLM (small/medium) | Per-domain summarization, NL rationale | e.g., GLM-5.2 (per env), or GPT-class — small-tier | Cheap; tools do numeric work. |
| LLM (large) | Coordinator synthesis, CSR drafting | e.g., larger GLM or frontier | Synthesis needs context. |
| Gradient-boosted trees | Electricity demand, flood risk, traffic congestion (Phase 2), PSI 24h (if needed) | XGBoost / LightGBM | Best tabular; simple. |
| Statistical baselines | Weather bias correction (optional) | Linear regression / Kalman | Tiny, explainable. |
| classifiers | Flash flood YES/NO | LightGBM w/ probability calibration | Outputs decision thresholds. |

### No deep learning for MVP, no CV, no YOLO

- Aligns with stated requirement NOT to use image/YOLO.
- Recurrent/Transformer models not justified for current data scale; revisit in Phase 3 for traffic if more granular data accumulates.

### Model governance

- Each model has `version`, `metrics` (RMSE/MAE/AUC), `trained_at`, `dataset_id`, `signature` (feature schema hash).
- Promotion staging: `dev → staging → prod`, switch via `active` flag.
- Inference endpoint validates signature against incoming features (fail safe if mismatch).

---

## 17. Security and API-Key Management

### Threat model (brief)

- Stolen SG-API keys → quota violation, data leak.
- LLM prompt injection from public dashboard input → coordinator issues unsafe recommendations.
- What-if parameters used to exfiltrate training data.
- PII risk: low (city-scale, no PII).

### Secrets storage

- **Local dev**: `.env` per developer, in repo only as `.env.example` (placeholders).
- **Prod-like (when introduced)**: HashiCorp Vault or AWS Secrets Manager; Postgres reads at boot.
- **Never** commit real keys. Pre-commit hook scans for high-entropy strings.

### Backend security

- All external calls via adapters that read source-of-truth key from a single `SecretsProvider`.
- Rate limit per user per endpoint.
- Pydantic validation on every external-facing field.
- Strict allow-list of LLM tools per agent (see §9).
- CSP + sane CORS for frontend.

### LLM safety

- Sanitize user inputs (what-if payload) — pure JSON, never interpolated into prompts unfiltered.
- Coordinator prompts assembled from structured fields; user-free text only allowed in dedicated "notes" string, prefixed in prompt with "UNTRUSTED NOTE:".
- All LLM calls require `system` prompt with safety policy; final action list is **rule-reviewed** before publishing to dashboard.

### Audit

- `audit_log(actor, action, target, ts, meta_jsonb)` for every mutating action (admin, model promotions, key changes).

### AuthN/AuthZ

- JWT via Auth.js (frontend) ↔ FastAPI dependency.
- Roles: `viewer`, `analyst`, `ops_lead`, `admin`.
- Ops actions (model promote, key rotate, source toggle) require `ops_lead`+.

---

## 18. Error Handling and Reliability

### Tiered failure model

| Tier | Failure | Response |
|---|---|---|
| Adapter | Source API 5xx / timeout | Retry with exponential backoff + jitter; circuit breaker per source; degrade to last cached values; surface "stale" flag in dashboard. |
| Domain agent | Tool timeout | Return partially-flagged envelope; Coordinator knows which domains are degraded. |
| Predictor | Model not loaded / signature mismatch | Predictor returns `mode=baseline` from rule fallback + flag. |
| Coordinator | One domain missing | Compose report with explicit "domain unavailable" caveat; never omit silently. |
| Pipeline | Postgres unreachable | API 5xx + retry queue writes to local buffer file; replay on recovery. |
| LLM | Provider outage | Use cached previous report; mark "auto-synthesis unavailable". |

### Explicit principles

- **No silent fallbacks**: any degradation logged + surfaced in dashboard header.
- **Circuit breakers** per external source to avoid cascading latency.
- **Bounded queues**: each scheduler job has max-concurrency + max-retries.
- **Health endpoints** surface DB / Redis / each source's last-success timestamp.

### Observability

- Structured logging (`structlog` JSON).
- Metrics via Prometheus-compatible exporter (`/metrics`).
- Tracing via OpenTelemetry when production-tier (not required for MVP Windows dev).

---

## 19. Testing Strategy

### Layers

| Layer | Tool | What we assert |
|---|---|---|
| Unit | pytest | Tools, normalizers, conflict rules, predictors with mocked DB. |
| Contract tests (envelopes) | schemathesis / jsonschema | Every agent emits valid envelope; every router consumes valid envelope. |
| Adapter tests | pytest + VCR (cassettes) | Real SG API responses parsed correctly; tolerant to schema drift. |
| Integration | pytest + testcontainers (Postgres+Timescale+Redis) | Ingest → analyze → report round-trips. |
| LLM eval | Promptfoo / bespoke | Fixed scenarios → expected recommendation coverage (checklist assertions, not exact text). |
| ML eval | N-Step ahead backtest | Rolling-origin MAE/RMSE vs baseline; log to `models.metrics`. |
| End-to-end | Playwright (frontend) against docker-compose | Dashboard load + report render + what-if roundtrip. |
| Performance | `locust` | 100 concurrent dashboard users; ingestor throughput. |
| Reliability | Chaos script | Kill a source; expect degraded report with stale flag, not 500. |

### LLM-specific safeguards

- Every Coordinator test pins the LLM output to deterministic checklist (e.g., action with id `F-001` present, severity ≥ HIGH, conflicts noted) — not full text equality.
- A regression suite of 20 representative scenarios run nightly; failures block prompts from prod promotion.

---

## 20. MVP Scope

### Goal

A demo-grade, internally usable UrbanOS that ingests live SG data, runs five domain agents, produces a City Situation & Action Report, and renders an Ops Dashboard. **No ML required.**

### In-MVP

- **Ingestors** for all five domains (live only).
- **5 domain agents** with rule-based + live-state tools only (no ML predictors).
- **City Coordinator** with rule-based conflict resolution + LLM synthesis.
- **City Situation & Action Report** persisted + dashboard panel.
- **Map** with weather, traffic overlay, flood zones, pollution PSI bubbles, electricity demand gauge.
- **Safe routing** with flood + congestion + pollution overlays (rule-based).
- **What-if studio** for flood + traffic (Coordinator calls agents w/ overridden inputs; no ML).
- **Postgres / Timescale / Redis / PostGIS** stack.
- **Auth** with single `ops_lead` + `viewer` role.
- **Docker Compose** to run everything locally on Windows.

### Explicitly OUT-of-MVP

- ML predictors (Phase 2).
- Historical backfill pipelines (Phase 2 — manual CSV one-shots only for setup).
- Real-time alerts to SMS/email.
- Multi-user RBAC beyond 2 roles.
- Production deployment (cloud/K8s).
- CV / image / YOLO (never — per requirement).
- Chat-style interface (Phase 2 maybe).

### MVP success acceptance

1. Dashboard auto-refreshes every 60s.
2. A live CSR visible with per-domain cards + action list.
3. Fallback when NEA or LTA source is down → dashboard flags "LTA degraded" and continues.
4. A what-if scenario produces a new CSR in < 5s.
5. Safe-routing returns 3 candidate paths with hazard warnings.

---

## 21. Future Extensions

| Extension | Trigger |
|---|---|
| **Real ML predictors** (electricity, flood, traffic, PSI) | After 3 months data accumulated / historical backfill complete. |
| **Alerting** (email/SMS/webhook) | When ops team grows beyond pilot. |
| **Multi-city** (Mumbai, Bangkok, Jakarta) | Once SG model proven; adapter pattern makes this cheap. |
| **Mobile-responsive Ops UI** | Field operators request. |
| **Natural language Q&A** over CSRs | When LLM eval proves deterministic enough. |
| **Retrieval over past reports (pgvector)** | When report archive exceeds thousands. |
| **Streaming bus** (Kafka/NATS) | When event flow > thousands/sec or fan-out to many consumers. |
| **Cloud deployment / K8s** | When reliability bars exceed local-host dev. |
| **Scenario presets marketplace** (typhoon, haze, MRT outage) | Once research team has curated set. |
| **Agency API write-back** (automated dispatch) | Strict security + legal approval required; far out. |
| **Federated / on-device LLM** | Cost optimization once model landscape stabilizes. |

---

## 22. Technical Risks and Limitations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LTA historical traffic CSV unavailable → traffic ML cannot train | High | Med | Self-accumulate live API for 3-6m; rule-only MVP. |
| SG APIs change schema / auth silently | Med | Med | Adapter strictness + nightly contract tests + source health dashboard. |
| LLM hallucination slips into CSR | Med | High | Dry-run compliance checks; deterministic checklist tests; safety review in rule engine. |
| LLM prompt injection via what-if "notes" | Med | High | Strict JSON-only inputs; sanitize + sandbox prompt fields. |
| TimescaleDB licensing/community changes | Low | Med | Code stays regular Postgres + partitioning; refactor is mechanical. |
| Map tile licensing (OSM/MapTiler) | Med | Med | Host own tiles from OSM with attribution; verify commercial use. |
| Aggregate ML accuracy insufficient (esp. flood) | Med | High | Always pair ML with rule fallback + confidence calibration; never surface single source-of-truth. |
| Confidential agency data leaks via logging | Low | High | No PII; redact JSON `raw` field before logging at INFO. |
| Multi-call latency explodes for Coordinator | Med | Med | Parallel agent calls + per-agent timeout + cached envelopes. |
| Team is Windows-only → some libs/imaging friction | Med | Low | Use Docker for dev; pin Linux containers in compose. |
| Model drift silently degrades predictions | Med | Med | Monthly retrain + alerting on rolling MAE. |

---

## Recommended Final Architecture (summary)

- **Layered**: Presentation (Next.js) / Application (FastAPI) / Agent / Domain Service / Data & ML.
- **Agents**: 5 domain agents + 1 City Coordinator. LLMs drive reasoning + report synthesis; tools handle all numerics/IO.
- **Storage**: PostgreSQL 16 + TimescaleDB (time-series) + PostGIS (geospatial); Redis cache + pub/sub + job queue.
- **Routing**: OSM-derived graph in `networkx` for MVP; safe-routing service consumes agent-derived edge costs.
- **ML**: Delayed to Phase 2 except where clearly justified (electricity demand MVP-eligible if historical export available; flood Phase 2 once PUB history confirmed). No deep learning; no CV/YOLO.
- **What-if**: scenario JSON → Coordinator fans out to each agent's `analyze_whatif` with overridden features; deterministic payload + LLM-only summary.
- **Deployment**: Docker Compose on team Windows workstations for MVP; cloud/K8s later.
- **Monorepo**: `backend / frontend / ml / infra / data / tools / docs`.

## Recommended MVP

**Live-only dashboard + Coordinator + rule-based agents + reports + minimal what-if (flood×traffic) + safe-routing** with explicit "no ML" stance. Three months of observation accumulation; then start Phase-2 ML.

## Development Phases

### Phase 0 — Foundation (≈2 weeks)
- Repo scaffold, CI, Docker compose, Alembic initial schema, secrets/example.
- Postgres + Timescale + PostGIS + Redis running on Windows via Docker.
- Auth scaffolding (Auth.js + FastAPI JWT, roles viewer/ops_lead).
- Smoke-test one ingestor (NEA weather).

### Phase 1 — Ingestion + Agents (≈4 weeks)
- All five ingestors with cassettes + circuit breakers + health dashboard.
- Domain agent base class + 5 agents emitting envelopes (rule-based; live tools; no ML).
- Coordinator with rule engine + LLM synthesis + CSR storage.
- API endpoints for dashboard backend.

### Phase 2 — Frontend + Routing + What-If (≈4 weeks)
- Next.js ops dashboard w/ MapLibre layers + report panel.
- Safe-routing service (rule-based edge costs) for drive/walk/cycle.
- What-if studio (cookbook scenarios for flood×traffic; deterministic payload).
- E2E Playwright suite.

### Phase 3 — ML Enablement (≈6 weeks)
- Historical backfill scripts + dataset builder + feature materialized views.
- Train electricity demand predictor → first promoted ML model.
- Flood water-level / flash-flood classifier (if PUB history verified).
- Predictor service behind tools; agents upgraded to call predictions.
- Drift monitoring.

### Phase 4 — Hardening (≈4 weeks)
- Alerting (email/webhook), audit log review UI, role expansion.
- Performance tuning (Timescale compression, indexes).
- Cloud deployment (K8s) optional; otherwise hardened Compose.

### Phase 5 — Extensions
- Multi-city adapters, report retrieval (pgvector), chat Q&A, scenario presets, write-back (with legal review).

## Key Decisions to Make Before Implementation

1. **LLM provider & model tier**: GLM-5.2 exclusive? OpenAI-grade fallback? Way-1 model for Coordinator vs domain agents? — affects latency + cost.
2. **Live vs historical data scope per domain**: which domains require ML in MVP, and what is "MVP-complete" if we wait 3 months for data?
3. **Authentication provider**: NextAuth credentials vs OIDC (future govt SSO?), team domain for MVP.
4. **Map tile server**: self-host tileserver-GL with OSM extract, versus MapTiler/Mapbox paid (license + cost).
5. **Routing road network source**: OSM-derived, or pursue LTA road dataset (licensing?).
6. **TimescaleDB edition**: Community vs Enterprise; acceptable compression features in community.
7. **Whether to include ML predictor of any kind in Phase 1** (recommend: no), or ship rule-only and reduce risk.
8. **LLM safety review gate**: human-in-the-loop before publishing CSRs to dashboard? Recommended yes for first 90 days.
9. **Memory-of-truth for source health**: store in Postgres vs Redis; whether to alert from app or external monitoring.
10. **Single monorepo confirmed** (polyrepo later if team scales beyond ~5 engineers).
11. **Windows-only dev but Linux containers**: confirm OK for all team workstations (Docker Desktop + WSL2).
12. **SG agency licences**: confirm each data source's terms of use allows dashboard redistribution; some are research/internal-use only — may require manual acknowledgement.

---

This proposal is code-free as instructed. Once you confirm the open questions above (especially LLM model tier, source licensing verdicts, and MVP-vs-ML boundary), I can move to ADRs (`docs/adr/`) and schema-first specs.
