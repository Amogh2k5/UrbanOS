# AGENTS.md — UrbanOS

Read this before working in this repo. Short, repo-specific, high-signal.

## Current state (verify before assuming)

This repo is **pre-implementation**. There is no `backend/`, `frontend/`, `infra/`, `tools/`, or `package.json` / `pyproject.toml` yet — only:
- `docs/` — architecture proposal + per-dataset audit reports (the real sources of truth)
- `ml/datasets/{raw,processed}/` — raw historical CSVs + `.gitkeep` placeholders
- `ml/{features,prediction,training,evaluation}/`, `scripts/data/` — empty (`.gitkeep` only)
- `ml/datasets/raw/weather_24h/extracted/*.csv` (9 yearly files, 2016–2024)
- `ml/datasets/raw/pollution_pm25/Historical1hrPM2.5.csv` (one file, 2014-04 → 2026-08)

No git, no `.gitignore`, no lockfiles, no CI, no build/test/lint commands exist. **Do not invent commands.** When asked to "run tests" or "lint", say the repo has none yet and stop.

## Source of truth

- **`docs/URBANOS_ARCHITECTURE_PROPOSAL.md`** — full system design. Read it before proposing architecture. Phase plan, schema sketch, MVP boundary, and "no DL / no ML in MVP" constraint all live here.
- **`docs/data/WEATHER_24H_DATA_AUDIT.md`** and **`docs/data/PM25_1H_DATA_AUDIT.md`** — ingestion rules for the only two datasets present. Information there cost reading files cell-by-cell; trust it over re-deriving.
- Target folder layout is in §14 of the architecture proposal (planned `backend/ frontend/ ml/ infra/ data/ tools/ docs/` monorepo). The existing dirs (`ml/`, `docs/`, `scripts/`) are seeds, not the final layout — scaffold new code per §14, don't pile everything into `ml/`.

## Hard constraints from the proposal (do not violate silently)

- **No deep learning, no CV, no YOLO** (proposal §16, §22). Use gradient-boosted trees (XGBoost/LightGBM) for any ML model.
- **No ML in MVP** (proposal §20). Rule-based agents + Coordinator + dashboard first; ML is Phase 3+.
- **Windows-only dev team, Linux containers via Docker Compose + WSL2** (proposal §22, "Key Decisions" #11). Don't suggest macOS/Linux-native workflows.
- **Storage stack**: PostgreSQL 16 + TimescaleDB + PostGIS + Redis. No Kafka in MVP (proposal §1, §4). Use Postgres LISTEN/NOTIFY + Redis pub/sub.
- **Singapore local time = UTC+08:00** (`Asia/Singapore`) everywhere; all timestamps `timestamptz` with explicit `+08:00`. NEA source strings carry no offset — cast on read.
- **Original CSV files must not be modified.** All cleaning happens at ingestion (proposal §12 + audit dispositions). Add a `data_quality_flag` field, never rewrite the raw file.
- **No silent fallbacks** (proposal §18): any degradation must be logged + surfaced on the dashboard.

## Dataset-specific ingestion rules (from the audits — verified)

### Weather 24-hour forecast (`ml/datasets/raw/weather_24h/extracted/`)
- 9 files, 2016→2024, 28 columns, schema stable across all years.
- **These are FORECASTS, not observations.** Cannot be used as ground truth. Pair with NEA observation datasets (not yet in repo) for any supervised task.
- **`valid_period_start.year` ≠ `date.year` bug** in 7 of 9 files (≤7 rows each; absent in 2016 and 2020). Derive canonical year from `date`, never trust `valid_period_*` blindly. Flag affected rows.
- **Separator drift in `valid_period_text`**: ` - ` in 2016–2022, mixed in 2023, fully ` to ` in 2024. Don't key logic on that text column — use the structured `valid_period_start`/`valid_period_end` timestamps.
- Per-row grain is `(date, timestamp, time_period)`; "region" is a column dimension (5 region pairs: south/north/east/central/west), not a row dimension. Model accordingly (proposal: two related tables `weather_24h_forecast` + `weather_24h_forecast_period`).
- Coverage gaps per year by **omission**, not nulls — all 28 columns have zero nulls in every file. Use walk-forward CV, not random splits.
- No coords in source — NEA region polygons must be sourced separately (still a **VERIFY** item in the architecture proposal).

### PM2.5 1-hour (`ml/datasets/raw/pollution_pm25/Historical1hrPM2.5.csv`)
- One file, 2014-04-01 → 2026-08-01, ~108k rows, 6 columns. **Observations** (not forecasts) — usable as supervision signal.
- Timestamp col is named `1hr_pm25` (misleading — it's the datetime, not a value). Format `d/M/yyyy H:mm`, no padding, no timezone token. Parse with `format="%d/%m/%Y %H:%M"` then cast to `timestamptz +08:00`.
- **One malformed row**: `"2016-04-04 010:00:00"` (row ~17,616). Normalize to `2016-04-04 01:00:00` at ingestion; flag as `repaired`. Do not touch the raw file.
- **Three duplicate-timestamp pairs** (2016-03-07, 2018-04-24, 2018-08-16) with conflicting PM2.5 values. Resolution rule per audit: **keep the later row in file order**; log discarded row to an audit table.
- **Four missing single-hour gaps** (2016 & 2018 only). Represent as absent rows; downstream daily aggregation must tolerate them.
- Haze readings **>200 µg/m³ are legitimate observations, not outliers** (Oct 2015, Sep 2019 haze). Do NOT clip/filter. Add `is_haze_period` boolean feature.
- Per-region values load natively as int64; no sentinel strings, no nulls, no negatives, no zeros (floor = 1).
- Model ingestion target (per audit §21): long format, one row per `(observed_at, region, pm25_value, data_quality_flag)` — normalizes schema with the weather dataset.
- Target construction for "next-day" prediction: issuance `t₀ = 23:00`, target window `[t₀+1h, t₀+24h]`. Avoid same-hour regression (leakage).

## Conventions to follow when code starts landing

- Backend: FastAPI async + SQLAlchemy 2.0 async + `asyncpg` + Alembic + Pydantic v2 + `structlog` + APScheduler in-process for MVP (proposal §12). No Celery/RQ yet.
- Frontend (when scaffolded): Next.js 14 App Router + TS + Tailwind + MapLibre GL (no token) + TanStack Query + Zustand + Auth.js (proposal §13).
- Agents: abstract `BaseDomainAgent` with `ingest_tick() / snapshot() / analyze() / analyze_whatif() / emit()` (proposal §2). Subclass per domain; don't hand-roll each.
- Tools exposed to LLMs are **pure Python functions** registered with JSON-schema params; tools never call the LLM; every tool call logged (proposal §9). Tool manifest is a first-class artefact (`tools/manifest.yaml`).
- LLM sizing: frontier model for Coordinator, smaller/cheaper per-domain. LLM never does arithmetic or severity ranking — rule engine does (proposal §3, §9).
- Conflict resolution = pure-Python rule functions in `rules/*.py`, not LLM (proposal §3). Priority order: safety > life > infra > comfort.
- Envelope JSON contract (proposal §2, §8) is canonical for all agent IO; don't redefine per agent.
- Time-series tables are TimescaleDB hypertables partitioned on `observed_at`; index `(metric_id, location_id, observed_at DESC)`. Raw obs 90 days hot → 7 years compressed; rollups permanent (proposal §6, §15).
- Model registry = `models` table with `version / metrics / trained_at / active`; promote via `active` flag only (proposal §7, §16). `dev → staging → prod`.
- Adapter pattern owns **all** per-source quirks (paging, rate limits, auth, units, timezone, nulls). Idempotent writes via natural key `(source, observed_at, station_id, metric)` upsert (proposal §4).
- Secrets: `.env.example` only in repo; real keys via vault/secrets manager. Pre-commit hook scans for high-entropy strings (proposal §17).

## What-if / scenario rules

- What-if inputs are **strict JSON only** — never interpolate raw user text into prompts. Any free-text "notes" field gets prefixed `UNTRUSTED NOTE:` and isolated (proposal §17).
- What-if determinism: same scenario + same model versions = identical result. Persist a `deterministic_payload` alongside the LLM report so scenarios can be diffed without LLM noise (proposal §11).

## Things still flagged VERIFY in the docs

Don't report these as problems you discovered — they are known open questions:
- NEA region polygon definitions (no coords in either source dataset)
- LTA historical traffic CSV availability (may need 3–6 months of self-accumulation)
- PUB flood-incident historical availability/structure
- EMA half-hourly demand granularity & licence
- NEA pollution forecast publication policy (decides whether PSI 24h ML is needed)
- Per-source unit conventions (°C, %, km/h, µg/m³) — assumed per NEA standard, not documented in headers
- Map tile + OSM licensing for commercial dashboard use

## Review checklist before proposing changes

1. Did you read the matching § of the architecture proposal?
2. Are you about to propose DL, CV/YOLO, or ML in the MVP? Stop.
3. Are you modifying a raw CSV? Stop — fix at ingestion instead.
4. Did you respect the timestamp rule (`Asia/Singapore`, explicit `+08:00`, derive year from `date` for weather)?
5. Are haze >200 values being clipped or filtered? Stop.
6. Did you check the existing audit(s) for the dataset you're touching before re-deriving rules?
7. If scaffolding new code: does the path match proposal §14's target monorepo layout?
