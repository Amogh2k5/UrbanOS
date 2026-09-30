# UrbanOS Phase 1 — Next-Day PM2.5 ML Spec (DESIGN ONLY)

**Status:** Design / pre-implementation. No code, no model training, no raw-file modification.
**Scope note:** This document defines the *full design* for next-day PM2.5 prediction. The **initial implementation scope** (§11A) is a deliberate subset; items outside that subset are kept as design context for later phases but are explicitly **NOT PART OF THE INITIAL ML IMPLEMENTATION**.
**Sources of truth:**
- `docs/data/PM25_1H_DATA_AUDIT.md` (audit of `ml/datasets/raw/pollution_pm25/Historical1hrPM2.5.csv`)
- `docs/data/WEATHER_24H_DATA_AUDIT.md` (audit of `ml/datasets/raw/weather_24h/extracted/*.csv`, 2016–2024)
- `docs/URBANOS_ARCHITECTURE_PROPOSAL.md` §7 (ML pipeline), §16 (model strategy), §20 (MVP boundary)

**Hard constraints inherited from the proposal:**
- **No deep learning, CV, or YOLO.** Phase 1 uses classical ML and tree-based models. Model selection is empirical and must be based on leakage-safe validation performance (proposal §16, §22). The approved Phase 1 comparison experiment (§11) accordingly includes linear/ridge, Random Forest / Extra Trees, XGBoost, LightGBM, and optionally CatBoost.
- Singapore local time = `Asia/Singapore` (UTC+08:00) everywhere; timestamps `timestamptz` with explicit `+08:00`.
- Raw CSV files are immutable — all cleaning happens at ingestion; add `data_quality_flag`, never rewrite the source.
- Walk-forward / chronological evaluation only — random splits leak (proposal §22 drift risk; weather audit §17 caveat 4).
- Phase 1 is the first ML implementation milestone for the UrbanOS Environment domain. The broader UrbanOS MVP remains multi-phase, but this document explicitly defines the initial offline ML implementation for next-day PM2.5 prediction.

---

## 1. Prediction task — exact definition

### 1.1 Forecast issuance time `t₀`
- `t₀ = 23:00 Asia/Singapore` on day `D`.
- A forecast issued at `t₀` must use **only** observations and forecasts available at or before `t₀`.
- Rationale: nightly pre-midnight issuance cadence (mirrors the audit's recommendation `t₀ = 23:00` in PM25 audit §21-C); gives the ops dashboard a fresh nightly run for the next day's haze advisory.

### 1.2 Target window
- `[t₀ + 1h, t₀ + 24h]` = the full 24 hours of calendar day `D+1` when `t₀ = D 23:00`.
- Boundaries are inclusive of the start hour, exclusive of `t₀ + 25h` (i.e. exactly 24 hourly observations per region per forecast).

### 1.3 Target labels (per region, per forecast issuance)

**In scope for the initial Phase 1 ML implementation:**
| Label | Type | Definition | Status |
|---|---|---|---|
| `pm25_next_day_mean` | regression | `mean(pm25_value)` over the 24-hour target window for that region | **IN SCOPE** |
| `pm25_next_day_max` | regression | `max(pm25_value)` over the 24-hour target window for that region | **IN SCOPE** |

**Deferred — documented for context, NOT PART OF THE INITIAL ML IMPLEMENTATION** (see §11A):
| Label | Type | Definition | Status |
|---|---|---|---|
| `pm25_next_day_exceed_50` | binary classification | `1` iff any hour in window exceeds 50 µg/m³ in that region | DEFERRED (Phase 1.5 / Phase 2) |
| `pm25_next_day_exceed_100` | binary classification | `1` iff any hour in window exceeds 100 µg/m³ in that region | DEFERRED (Phase 1.5 / Phase 2) |

- The two deferred classifier targets remain documented here so feature/target design remains forward-compatible, but **no classifier, no probability calibration, no threshold-tuning is implemented in the initial Phase 1 run.**
- Classifier threshold values (50, 100 µg/m³) followed NEA/WHO PM2.5 breakpoints — **VERIFY** against current NEA published advisory thresholds before the classifier targets are eventually implemented; these should be config, not constants.
- Target labels are computed **per region** (5 regions: north / south / east / west / central) — see §7 for regional strategy.

### 1.4 What "next-day" explicitly excludes
- **No same-hour regression.** Same-hour prediction would put the target value into the predictor's feature set at time `t`, causing trivial leakage (PM25 audit §21-C caveat 4).
- **No multi-day horizon** in Phase 1. Single horizon = 24h. Multi-day / rolling horizons deferred to Phase 2.

---

## 2. Data sources used

### 2.1 PM2.5 observations (target source)
- File: `ml/datasets/raw/pollution_pm25/Historical1hrPM2.5.csv`
- Audit: `docs/data/PM25_1H_DATA_AUDIT.md`
- Span: `2014-04-01 01:00` → `2026-08-01 00:00` (Singapore local, ~108k rows, 6 cols).
- Grain: one row per `(timestamp, …5 region columns)`. Wide format in source; **ingest to long format** `(observed_at, region, pm25_value, data_quality_flag)` per PM25 audit §21-A.5.
- All values are **observations** (not forecasts) — usable as supervision signal.

### 2.2 Weather 24h forecasts (feature source)
- Files: `ml/datasets/raw/weather_24h/extracted/*.csv` (9 yearly files, 2016–2024)
- Audit: `docs/data/WEATHER_24H_DATA_AUDIT.md`
- Span: `2016-03-16` → `2024-12-31`; 28 columns stable across all years.
- **These are forecasts, not observations.** Cannot verify PM2.5 predictions against weather observations using this dataset alone (Weather audit §17 caveat 1; §15.8).
- Per-row grain: `(date, timestamp, time_period)`. Region is a **column dimension** (south/north/east/central/west), not a row dimension (Weather audit §7, §16).
- Two-table model on ingest (Weather audit §16, §17):
  - `weather_24h_forecast` — one row per `(date, timestamp)`, national fields.
  - `weather_24h_forecast_period` — one row per `(date, timestamp, time_period_start)`, regional sub-period fields.

### 2.3 Companion datasets NOT in repo (deferred / VERIFY)
These are flagged in PM25 audit §20 caveat 8 as useful but unavailable:
- NEA PSI national readings — **VERIFY** availability / granularity.
- NEA rainfall / wind **observations** (not forecasts) — **VERIFY**. The Weather 24h dataset is forecasts only.
- Haze-event history tables — optional contextual feature; can be derived from PM2.5 itself.

Phase 1 must be designable **without** these; treat their absence as a feature-set limitation.

---

## 3. Prediction-time feature availability

**Rule:** at issuance `t₀ = D 23:00`, a feature is usable only if its value is known with certainty by `t₀`.

### 3.1 Feature classes and cutoff rules
| Class | Cutoff | Usable? |
|---|---|---|
| PM2.5 observations up to and including `t₀` | `observed_at ≤ t₀` | Yes |
| PM2.5 observations strictly after `t₀` (target window) | — | **No** (this is the target) |
| Weather 24h forecasts issued with `timestamp ≤ t₀` whose `valid_period` intersects `[t₀+1h, t₀+24h]` | issue `timestamp ≤ t₀` | Yes |
| Weather 24h forecasts whose `valid_period_start > t₀` but issued earlier | issue `timestamp ≤ t₀` | Yes (forecast already published) |
| NEA 2-hour rainfall nowcast (if/when integrated) | issuance ≤ `t₀` | **VERIFY availability** — not in repo |
| Calendar / monsoon flags | deterministic | Yes |

### 3.2 Concrete Phase-1 feature groups

**Group A — PM2.5 lag features (per region, computed up to `t₀`):**
- `pm25_t0` — value at `t₀` (the hour ending at issuance).
- `pm25_lag_24h, pm25_lag_48h, pm25_lag_72h` — same-region, same hour, prior days (inertia; PM25 audit §21-B.1).
- Rolling aggregates **ending at `t₀`**: `pm25_roll6h_mean, pm25_roll6h_max, pm25_roll12h_mean, pm25_roll12h_max, pm25_roll24h_mean, pm25_roll24h_max` (PM25 audit §21-B.2).
- Cross-region lag (**Phase 1.5 / optional**): `pm25_upwind_lag_24h` using a fixed prevailing-wind region map. Demands wind-direction join — guard behind a feature flag; skip if wind obs unavailable.

**Group B — Calendar / temporal features (deterministic):**
- `hour_of_day` at `t₀`, `day_of_week`, `month`, `is_weekend`, holiday flag.
- `monsoon_flag` ∈ {NE, SW, transitional} per NEA monsoon windows (boreal winter NE, boreal summer SW, Apr & Oct transitional). **VERIFY** monsoon-window dates with NEA official season definitions before pinning.

**Group C — Weather 24h forecast features (aligned to target window, see §5):**
- `wf_temp_high`, `wf_temp_low`, `wf_rh_high`, `wf_rh_low`, `wf_wind_high`, `wf_wind_low`, `wf_wind_dir` (national fields from `weather_24h_forecast`).
- `wf_forecast_code` (national, categorical) and the region-specific `{region}_forecast_code` for the target region (categorical).
- Regional sub-period aggregates over the target window: count of rain-related codes (RA, SH, PS, TL, LR, LS, HS, HR, HG), count of haze-related codes (HZ, HG, HR, HS, HT), fraction of window covered by cloud codes (CL, PC, PN).
- Weather forecast issue lead time: `t₀ - forecast.timestamp` (proxy for forecast skill; closer-to-`t₀` issues should weight higher).

**Group D — Target-window weather coverage features (data-completeness guards):**
- `wf_window_coverage` = fraction of `[t₀+1h, t₀+24h]` hours that are inside any issued-≤-`t₀` forecast's `valid_period`/`time_period` interval (per §5 alignment). Low coverage → model confidence should be flagged downstream; do not silently drop.
- `wf_n_issues_used` = number of distinct forecast-issue timestamps contributing to the window.

### 3.3 Features explicitly excluded from Phase 1
- PSI readings (not in repo; **VERIFY**).
- Rainfall **observations** (not in repo; weather dataset is forecasts only; **VERIFY**). Weather codes are used as a categorical proxy.
- Live NEA 2h nowcast (not in repo; **VERIFY**).
- Any feature requiring a future observation.

---

## 4. Prediction cutoff — operational contract

- **Cutoff time:** `t₀ = 23:00 Asia/Singapore` of day `D`.
- **Snapshot rule:** all feature queries must filter `observed_at ≤ t₀` (PM2.5) and `timestamp ≤ t₀` (weather forecasts), with timestamps stored as `timestamptz` carrying explicit `+08:00`.
- **Issuance cadence:** one forecast per (region, day) at `t₀`. Persisted as rows in the `forecasts` hypertable per proposal §6 / §7.
- **Tool exposure (deferred to production phase — NOT in initial Phase 1 ML implementation):** the predictor service would expose `predict_pm25_next_day(issuance_date, region)` per PM25 audit §21-E. The initial Phase 1 implementation only trains and evaluates models offline; it does not expose a live predictor or write to the `forecasts` hypertable.
- **Retry / backfill:** historical re-issuance is supported by the same code path — given a past `t₀`, the feature builder must reconstruct features using only data available by that past `t₀` (no lookahead). This is required for walk-forward CV (§8).

---

## 5. Weather 24h forecast alignment

### 5.1 Alignment key
- For a given `t₀` (day `D 23:00`), candidate weather rows are all `(date, timestamp, time_period)` rows where:
  - `forecast.timestamp ≤ t₀` (issued at or before cutoff), **and**
  - `forecast.valid_period` overlaps `[t₀ + 1h, t₀ + 24h]` (covers part of the target window).

### 5.2 Choosing among multiple issues
NEA issues multiple forecasts per day (Weather audit §9: up to 23 distinct `timestamp` per `date` in recent years). Alignment rule:
- **Deduplicate by target hour:** for each target hour `h ∈ [t₀+1h, t₀+24h]`, pick the **latest issue at-or-before `t₀`** whose `valid_period` covers `h`. The "latest issue" is by `timestamp` tie-breaker.
- Aggregate national fields over the 24 target hours: if the latest issue covering `h` differs across `h`, take the issue with most covered hours as representative; fall back to per-hour weighting for sub-period codes.
- Rationale: NEA's later issues presumably supersede earlier ones (PM25 audit §14 dedupe rule applied the same "keep later publication" principle for PM2.5; same convention here).

### 5.3 Regional alignment
- The 5 weather regions (S/N/E/C/W) **match** the 5 PM2.5 regions (Weather audit §7; PM25 audit §7) — same NEA region definitions. Per-region join is direct.
- **VERIFY** the region-polygon mapping between datasets is identical (no boundary drift over years). The source files carry only region *names*, not polygons.

### 5.4 Coverage limitation — constrains the chronological split

- Weather 24h forecasts in this repo cover **2016-03-16 → 2024-12-31 only** (Weather audit §1: 9 yearly files 2016–2024; §12: max `date = 2024-12-31`). The accompanying `Historical24hourWeatherForecast.zip` contains the same 9 files (audit §1: "not inspected beyond file listing"); **no 2025 or 2026 weather forecast file exists in the repo**. **VERIFY** before implementation whether a 2025 / 2026 NEA 24-hour forecast export can be obtained; if so, re-open a larger split. Until then, this is a hard data-availability boundary.
- PM2.5 observations, by contrast, run to **2026-08-01 00:00** (PM25 audit §9). The 2025-01 → 2026-07 PM2.5 rows are real observations but have **no matching weather features** at all.
- **Design rule (no invented data):** every split must have full weather-feature availability. The chronological split in §8.1 is therefore **re-scoped to end at 2024-12-31** for all three sub-splits (train / validation / test). A test split covering 2025-2026 (as earlier drafts proposed) would silently use missing weather features and is **rejected**.
- The 2014-04 → 2016-03 PM2.5 rows likewise have no weather features (Weather audit coverage start) and remain ineligible for the weather-featured Phase 1 model — unchanged.

### 5.5 Source defects propagating to features
Carry forward from the Weather audit into feature design (do **not** silently trust):
- **Year-offset bug** in `valid_period_start`/`valid_period_end` (Weather audit §15.4): feature builder derives canonical year from `date`, not `valid_period_*`, and flags affected rows. If a target hour falls inside a flagged period, set `wf_quality_flag = year_offset_repaired` and keep the row (do not drop).
- **Separator drift** ` - ` vs ` to ` in `valid_period_text` (Weather audit §13.4, §15.5): feature builder does **not** parse `valid_period_text`. Always use the structured `valid_period_start`/`valid_period_end` columns.
- **Per-row grain is `(date, timestamp, time_period)`** — feature builder joins on those, never re-keys on region column.
- **No coordinates**: weather regions join only by region name; no spatial-polygon join is possible from source data alone (**VERIFY** NEA polygon source separately).

---

## 6. PM2.5 data-quality handling (at ingestion, not in this spec's scope to implement)

Inherited verbatim from PM25 audit §21-A and the architecture proposal §12 ("fix at ingestion, never rewrite raw"). The feature builder in Phase 1 **consumes the ingested long-format observations; it does not re-clean**. The ingested table is assumed to have:

1. `observed_at timestamptz` parsed from the `1hr_pm25` col with `format="%d/%m/%Y %H:%M"`, then cast `+08:00`.
2. The single malformed row `"2016-04-04 010:00:00"` (PM25 audit §6, row ~17,616) normalized to `2016-04-04 01:00:00` and flagged `data_quality_flag = repaired`.
3. Three duplicate-timestamp pairs (2016-03-07 00:00, 2018-04-24 00:00, 2018-08-16 02:00; PM25 audit §14) de-duplicated by **keeping the later row in file order**; discarded rows persisted to an audit table for traceability.
4. Four missing single-hour gaps (PM25 audit §15) represented as absent rows — no synthetic imputation at ingestion; downstream rolling aggregates must tolerate them via `skipna`/min-periods semantics.
5. Long-format rows: one per `(observed_at, region)` with `pm25_value` int → numeric and `data_quality_flag` text.
6. `is_haze_period` boolean feature materialized for `pm25_value > 200` rows — preservation, not clipping (PM25 audit §17, §21-A.6).
7. No clipping/filtering of haze values `> 200` µg/m³ — they are the signal, not outliers (PM25 audit §17; PM25 audit §20 caveat 4).

Feature-builder contract (Phase 1 design):
- Read only from the ingested long-format `observations` table; raw CSV is never re-read.
- Propagate the `data_quality_flag` as a feature-builder input but do not let it gate modelling (training data asserts PM2.5 ground truth equals the observation).
- Compute lags/rollups with explicit NaN propagation; do not impute missing PM2.5 hours (only 4 such hours in 12 years — they will simply not contribute to rollups).

---

## 7. Regional modelling strategy

### 7.1 Decision for the initial Phase 1 implementation: per-region models
- **Train 5 independent regional models** (north / south / east / west / central), **per regression target** (`pm25_next_day_mean`, `pm25_next_day_max`). That is 5 regions × 2 targets = 10 model slots per candidate algorithm in the comparison experiment (§11).
- Rationale:
  - PM25 audit §18 shows full per-region coverage parity (identical counts across regions per year), so per-region training is feasible without imbalance corrections.
  - West region behaves distinctly (PM25 audit §16: max 471, 45 hours >200) — central tendency similar across regions but tail behaviour differs; per-region trees capture this without shared regularizers.
  - Per-region models are simpler to debug, retrain, and roll back via the model registry (proposal §7, §16).

### 7.2 Experiment design: per-region vs. global-with-region-feature
- The initial Phase 1 implementation uses **per-region models only** as the default strategy.
- **However, the model comparison experiment (§11) is explicitly designed to allow a later, optional evaluation of a single global model with `region` as a categorical feature** for each target, using the same features, splits, and metrics as the per-region models. This is to be attempted only if early per-region results suggest the regional signal is weak or data scarcity per region hurts, and to be reported alongside per-region results in the comparison artefact.
- **Selection rule:** the global-with-region-feature variant may replace per-region models as the recommended approach **only if it outperforms the per-region winning model on validation MAE/RMSE/R² (§10) for the same target**; otherwise per-region remains the default.
- What the initial Phase 1 implementation explicitly does NOT do:
  - No hierarchical / multi-output model (deferred to Phase 2).
  - No spatial kriging / GP / region-polygon feature — no coordinates in source (Weather audit §15.7; PM25 audit §7).

### 7.3 (Removed — haze-class-imbalance handling was tied to the deferred `exceed_100` classifier and is therefore NOT PART OF THE INITIAL ML IMPLEMENTATION. It remains recorded above in §1.3 as deferred context for Phase 1.5 / Phase 2.)

---

## 8. Train / validation / test split (chronological)

Walk-forward only (Weather audit §17 caveat 4; PM25 audit §21-D.3; proposal §22). No random shuffling.

### 8.1 Static three-way split (Phase 1 baseline)

**Hard rule:** every sub-split (train, validation, test) must have weather-feature availability per §5.4. Weather 24h data in this repo ends **2024-12-31**. PM2.5 alone runs to 2026-08 but has no weather features after 2024-12-31 — those rows are therefore ineligible for the weather-featured Phase 1 model. **No weather data is invented.**

| Split | Start (`t₀ = 23:00 Asia/Singapore`) | End | Notes |
|---|---|---|---|
| Train | `2016-04-01 00:00` | `2021-12-31 23:00` | Earliest usable issuance is 1 April 2016: weather features become available 2016-03-16 (Weather audit §1) and PM2.5 rolling/lag features need ≥2 weeks of back-history from the long-format observations table (which itself begins 2014-04-01 per PM25 audit §9, so back-history for 2016-04 issuances is plentiful). ~5.75 years of training data. |
| Validation | `2022-01-01 00:00` | `2023-06-30 23:00` | 1.5-year validation window. Used for early stopping (where applicable), hyperparameter selection, and **model selection**. The validation split is the sole basis for choosing the final model per target — never the test split. |
| Test | `2023-07-01 00:00` | `2024-12-31 23:00` | 1.5-year held-out test window, evaluated **exactly once** per finally-selected model per target. Ends at the weather-data boundary (2024-12-31 per Weather audit §12). |

**Why this split, in short:**
1. PM2.5 alone reaches 2026-08 but the Weather 24h feature source stops at 2024-12-31 (Weather audit §12). A test period with no weather features would silently degrade the model.
2. The full split window therefore lives inside the dataset intersection (PM2.5 ∩ Weather 24h): 2016-04-01 → 2024-12-31.
3. The split is chronological (train < validation < test) and respects §8.3 leakage guards.
4. Train + validation + test together span 2016-04 → 2024-12 (~8.75 years), giving a reasonable climate-cycle depth for training while reserving ~3 years (2022 H1 → 2024 H2) for validation + test.

- Forecast issuance `t₀` is assigned to a split by `t₀.date()`, not by target-window date.
- **No row with `t₀` in the test split may have any feature value computed from a row whose `observed_at` / `timestamp` is in or after the test split start.** (This is the cutoff rule from §4.)
- The 2023-07 → 2024-12 test window covers the 2023 haze-sparse normal period (PM25 audit §17 shows the major SE haze windows were 2013/2015/2019; 2023 H2–2024 are not in those windows). It therefore tests generalisation under haze-free conditions; interpretation of `pm25_next_day_max` metrics in test must account for the limited tail exposure.
- The 2025–2026 PM2.5-only segment is held out from this experiment. It can be used in a **future, descriptor-only** baseline experiment (weather-coded features dropped, PM2.5 lags + calendar features only) if such a variant is explicitly proposed — **not in the initial Phase 1 scope**. The Weather 24h VERIFY item (§13) governs whether a re-scoped split with 2025+ test data can later be opened.

### 8.2 Walk-forward CV (optional robustness supplement — not for selection)
- The static §8.1 split is the basis for §11.4 model selection. Walk-forward CV is an **optional supplement** for reporting metric variance across chronological folds; it is not used to make the final selection.
- If implemented: rolling-origin, expanding-window with initial train 2016-04 → 2019-12 (3.75 years) and ≤6-month validation folds rolling forward inside the 2020-01 → 2021-12 train-validation band, twice before the §8.1 validation window (2022 H1 → 2023 H1) is reached. Do not let walk-forward folds cross into the §8.1 test window (starts 2023-07-01). Accumulate metrics across folds.
- The mandatory §11A.1 acceptance path uses only the §8.1 static train/validation/test split for selection + one-shot test evaluation.

### 8.3 Leakage guards enforced at feature-builder level
- Per-issuance row, the feature builder only emits features computed over rows with `observed_at ≤ t₀` (PM2.5) or `timestamp ≤ t₀` (weather forecasts).
- Target labels (§1.3) computed only from `observed_at > t₀`.
- No global statistics (mean / std / min / max over the full dataset) enter the feature set. Any normalisation (e.g. for the linear / ridge baseline, §11) is **fit on the training split only** — **VERIFY** library defaults for scikit-learn pipeline steps (`StandardScaler` / `OneHotEncoder` must be fit on train only); tree models (RF / ExtraTrees / XGBoost / LightGBM / CatBoost) need no scaling.
- Calendar features are deterministic and future-safe (no leakage).

---

## 9. Baselines (regression only — classifiers deferred)

Baselines are computed for both in-scope regression targets (`pm25_next_day_mean`, `pm25_next_day_max`) per region. Every ML candidate in the §11 comparison experiment must be reported alongside these baselines.

### 9.1 Baseline A — Persistence (per region, per regression target)
- `pm25_next_day_max_BL_persist` = `max(pm25 over last 24h ending at t₀)` for that region (i.e., "tomorrow's max will equal today's max").
- `pm25_next_day_mean_BL_persist` = `mean(pm25 over last 24h ending at t₀)`.

### 9.2 Baseline B — Climatological mean (per region, per regression target)
- For a forecast issued at `t₀ = D 23:00`, predict the **historical mean of the target** for the same region and same (month, day-of-week) bucket, computed using only training-split rows (leakage-safe — see §8.3).
- Same approach for both `pm25_next_day_max` and `pm25_next_day_mean`.

### 9.3 Baseline C — 7-day trailing rolling mean
- `pm25_next_day_max_BL_roll7` = mean of `pm25_next_day_max` over the last 7 forecast issuances (per region), using only issuances at-or-before the current `t₀`. Captures short-term haze inertia.
- Analogous for `pm25_next_day_mean`.

### 9.4 Baseline comparison rule (regression)
- Every ML candidate's validation metrics (§10) are reported against all three baselines on the same chronological validation split.
- **The final selected model per target must outperform the persistence baseline (A) on every primary metric on the validation split.** Climatological (B) and rolling (C) are reported for context but persistence is the floor.
- (Classifier promotion / threshold rules are deferred together with the classifier targets — §1.3, §11A.)

---

## 10. Evaluation metrics

### 10.1 In-scope metrics (initial Phase 1 implementation)
For both in-scope regression targets (`pm25_next_day_mean`, `pm25_next_day_max`), compute and report:

- **MAE** (mean absolute error) in µg/m³ — primary; interpretable in source units, robust to the haze tail.
- **RMSE** (root mean squared error) in µg/m³ — primary; penalises large misses, which is the safety-relevant behaviour for haze spikes.
- **R²** (coefficient of determination) — secondary; conveys fraction of variance explained relative to the climatological mean.

All three are computed on the **same prediction set** so they are directly comparable across models.

### 10.2 Reporting granularity (mandatory)
Every metric is reported at three levels:
- **per region** (north / south / east / west / central),
- **per target** (`pm25_next_day_mean` vs `pm25_next_day_max` — never merged),
- **per model** (including every baseline A / B / C and every ML candidate in §11).

No macro-averaging across regions in the primary comparison table; aggregates are optional and clearly labelled as such. This prevents West-region haze skill masking poor Central-region performance or vice versa (PM25 audit §16 shows West has the distinct tail).

### 10.3 Comparison against persistence
- Every ML candidate's metrics are reported side-by-side with **Baseline A (persistence)** on the same split.
- Reporting the delta `(ML_metric − persistence_metric)` is required for MAE / RMSE / R² on both validation and (for selected models only) test.
- This mirrors the selection rule in §9.4 (must beat persistence on validation → eligible for selection) and §11.4 (test-set reporting for the finally-selected model only).

### 10.4 Operational signals (secondary, reported but not selection-criterion)
For each candidate model, also record:
- **Training wall-clock time** (seconds, on a fixed reference machine to be specified at implementation time; record machine spec in the experiment artefact, §11.6).
- **Inference wall-clock time per issuance × region** (mean and p95 over the validation split).
- **Model complexity proxies**: number of parameters / number of trees × max depth for tree models; feature-count for linear models; on-disk artefact size in MB.
- These are reported as context. **Predictive performance (MAE / RMSE / R²) remains the primary selection criterion** (§11.4); a faster / smaller model is preferred only as a tie-breaker between statistically comparable predictive metrics.

### 10.5 Reproducibility of metric computation
- Metric computation is deterministic and seeded for any stochastic component.
- The validation-split predictions and the test-split predictions (for the selected model only) are persisted as artefacts (CSV / Parquet) keyed by `(issuance_date, region, model_id, target)` so numbers can be re-derived offline.
- Metric values are written into the experiment artefact (§11.6) as JSON, not into prose.

### 10.6 Out-of-scope metric work (deferred)
The following are NOT part of the initial Phase 1 evaluation:
- Haze-stratified MAE on `pm25_next_day_max > 50` — useful, **but the test split (2023-07 → 2024-12) is haze-tail-light (PM25 audit §17: documented SE haze windows were Oct 2015 and Sep 2019; Oct 2015 falls before weather-feature coverage begins and Sep 2019 falls in train)**; deferred until a split-strategy decision accommodates haze events meaningfully inside the test window (see §13 haze-stratification VERIFY).
- sMAPE, Pinball loss, quantile loss — tied to quantile regression which is deferred (§11A).
- All classifier metrics (Recall@precision, AUPRC, F2, Brier, ECE) — class is deferred (§1.3).

---

## 11. Model comparison experiment (initial Phase 1 implementation)

### 11.1 Approach
Phase 1 does **not** pre-mandate LightGBM or XGBoost (or any algorithm) as the final model. Phase 1 implements a **model comparison experiment** that compares several appropriate non-deep-learning models on the **exact same**:
- training data (§2, §8),
- features (§3),
- chronological splits (§8),
- targets (§1.3 — `pm25_next_day_mean` and `pm25_next_day_max` only),
- evaluation metrics (§10).

Deep learning remains prohibited (proposal §16, §22).

### 11.2 Candidate model families (all in-scope; mandatory)
Every initial Phase 1 run must include at minimum:
- **B-A: Persistence baseline** (§9.1) — non-ML, no training; the floor to beat.
- **B-B: Climatological baseline** (§9.2) — non-ML, deterministic bucketed mean.
- **B-C: Trailing-7-day baseline** (§9.3) — non-ML, rolling mean.
- **M1: Linear / Ridge regression** — a simple regularised linear baseline. Serves as the linear floor for ML and exercises the leakage-safe normalisation contract (§8.3: scaler / one-hot fit on train only).
- **M2: Random Forest** or **Extra Trees** (pick one per region per target; record which) — bagging baseline; cheap, robust to categoricals.
- **M3: XGBoost (gradient-boosted trees)** — `tree_method=hist`, `objective=reg:squarederror`.
- **M4: LightGBM (gradient-boosted trees)** — `objective=regression` (L2).

Hyperparameter search for M3/M4 (and M2 where relevant) is done on the validation split only, with placeholders for the search space to be defined at implementation time (this spec fixes only the metric criteria, not the values).

### 11.3 Optional candidate — conditional inclusion only
- **M5: CatBoost** — included **only if** its native handling of the actual Phase-1 categorical feature types (e.g. `wf_forecast_code`, `wf_wind_dir`, region codes, `monsoon_flag`) provides a materially simpler / more correct pipeline than one-hot encoding for the linear and tree baselines. Document the reason in the experiment artefact (§11.6).
- **Do not add CatBoost — or any other algorithm — simply to have more candidates in the comparison.** The list in §11.2 is the mandatory minimum; additions require a documented reason tied to the actual feature types.

### 11.4 Selection rule — two-stage, per-target
Two regression targets means the final model is selected **separately** for each:

1. **Stage 1 — Validation selection (for each target independently):** for each candidate (B-A, B-B, B-C, M1, M2, M3, M4, optionally M5), train on the train split and evaluate on the validation split per §10 metrics. For each target, rank candidates by validation MAE (primary), then RMSE, then R². Apply the §9.4 baseline rule: a candidate is **eligible** only if it beats persistence (B-A) on every primary validation metric. Among eligible candidates, the one with best validation MAE (RMSE as tiebreaker, R² next) is selected for that target.
2. **Stage 2 — Test-set evaluation (for each target's selected model, once):** the validation-selected model for each target is then evaluated **exactly once** on the untouched chronological test split. The test metrics (per region, per target) are reported as the final generalisation estimate.

**Hard rule:** the test split is never used to choose the final model. Test-set performance does not feed back into model selection; if the selected model underperforms on test it is reported as-is and the finding is documented (no re-selection, no further tuning).

### 11.5 Per-region and per-target independence
- Selection (§11.4) is performed **independently per target** (`pm25_next_day_mean`, `pm25_next_day_max`). Different targets may end up with different model families.
- Selection is performed **within the default per-region strategy** (§7.1): 5 regions × 2 targets = 10 final selected models. The optional global-with-region-feature experiment (§7.2), if run at all in the initial Phase 1, is reported alongside per-region results and follows the same §11.4 two-stage rule.

### 11.6 Experiment artefact (reproducibility)
For every run of the comparison experiment, persist a self-contained artefact containing:
- Versions of all libraries (Python, scikit-learn, XGBoost, LightGBM, CatBoost if used, pandas, etc.).
- Feature builder commit / version string.
- Splits used (start/end timestamps for train / validation / test).
- Per-candidate, per-region, per-target: validation metrics (MAE, RMSE, R²) + training time + inference time + model-complexity proxies (§10.4).
- Per-selected-model, per-region, per-target: test metrics + the deterministic seed used.
- The selected model artefact paths and the selection rationale (which candidate won, on what metric, by what margin).
- Baseline metrics (B-A / B-B / B-C) reported in the same structure as ML candidate metrics.

The artefact's purpose is to make the model-selection decision fully reproducible from raw ingested data forward.

## 11A. Initial Phase 1 Implementation Scope

This section is the authority on what the initial Phase 1 ML implementation does and does not include. Where other sections describe additional context, those descriptions are forward-looking design, not implementation scope.

### 11A.1 IN SCOPE NOW — initial Phase 1 ML implementation
- Long-format ingestion of `Historical1hrPM2.5.csv` into the `observations` table per PM25 audit §21-A (raw CSV untouched; defect handling at ingestion only — malformed `010:00:00` row, duplicate-timestamp dedupe keeping later-in-file, 4 hourly-gaps tolerated without imputation, haze `>200` preserved, `is_haze_period` boolean materialised, `data_quality_flag` populated).
- Ingestion of Weather 24h forecasts into `weather_24h_forecast` + `weather_24h_forecast_period` per Weather audit §16/§17 (raw CSV untouched; year-offset flagged, separator drift ignored by using structured timestamps only).
- Leakage-safe feature generation respecting `t₀ = 23:00 Asia/Singapore` cutoff (§3, §4, §8.3): PM2.5 lags and rolling aggregates, deterministic calendar/monsoon flags, weather-forecast features aligned per §5, weather-coverage guards.
- Next-day target label generation for **`pm25_next_day_mean`** and **`pm25_next_day_max`** per region, target window `[t₀+1h, t₀+24h]` (§1).
- Baselines: persistence (B-A), climatological (B-B), trailing-7-day (B-C) per region, per target (§9).
- Model comparison experiment (§11): M1 linear/ridge, M2 RF/ExtraTrees, M3 XGBoost, M4 LightGBM, optional M5 CatBoost with documented reason, all trained and evaluated on identical inputs.
- Two-stage model selection per target on the validation split; one-shot test-set evaluation for the selected model per target (§11.4).
- Metrics MAE, RMSE, R² per region / per target / per model, with persistence deltas, plus training time / inference time / complexity proxies (§10).
- Persisted reproducibility artefact (§11.6) capturing library versions, splits, per-candidate validation metrics, per-selected-model test metrics, seeds, model paths.
- Chronological train / validation / test split (§8.1) and leakage guards (§8.3) strictly enforced.

### 11A.2 DEFERRED / FUTURE — NOT PART OF THE INITIAL ML IMPLEMENTATION
These items are kept elsewhere in this document as design context, but **must not** be implemented in the initial Phase 1 run:
- `pm25_next_day_exceed_50` and `pm25_next_day_exceed_100` classifier targets (§1.3) and **all** classifier-side machinery: probability calibration (isotonic / Platt), threshold tuning, `scale_pos_weight`, focal loss, Brier / ECE / AUPRC / F2 / Recall@precision metrics.
- Quantile regression (e.g. LightGBM `quantile` objective at τ=0.9) and Pinball loss metrics.
- Stacked ensembles and any meta-learning over candidates.
- Automatic drift monitoring and rolling-MAE alerting (§12 future version).
- Automatic monthly retraining and automatic model auto-promotion (`active=true` flipping without human sign-off).
- Live inference integration: no APScheduler job at `0 23 * * *` writing into the `forecasts` hypertable; no `predict_pm25_next_day` tool exposed to agents; no `mode=baseline` fallback path (these are design-only in §12).
- Dashboard integration: no API endpoint, no SSE stream, no MapLibre overlay (frontend Phase 2 per proposal §13).
- Haze-stratified MAE reporting (§10.6) — deferred pending a split-strategy decision that accommodates haze events in the test window.
- Global-with-region-feature model as a *recommended* strategy (§7.2) — it is allowed as an *optional, later, comparison-only* variant in the experiment, but the default initial Phase 1 strategy is per-region models. Replacing per-region as the recommended approach requires validation evidence (§7.2).

The model registry (`models` table) writes for the initial Phase 1 implementation are limited to recording the comparison experiment's results (and persistence paths) — not to an `active` flag that the live system reads, because there is no live system in Phase 1.

---

## 12. Production inference concept (DESIGN CONTEXT ONLY — NOT PART OF THE INITIAL PHASE 1 ML IMPLEMENTATION)

> The whole of §12 is design context for later phases. The initial Phase 1 implementation is fully offline (§11A.1) and does not expose any live predictor, scheduler, drift monitor, or dashboard fallback. Nothing below should be read as initial scope.

### 12.1 Scheduler (deferred)
- APScheduler job at `cron: 0 23 * * *` `Asia/Singapore` (`t₀ = D 23:00`) per proposal §12. Job emits 5 regional forecasts × regression targets into the `forecasts` hypertable per proposal §6. (Classifier targets excluded per §11A.2.)

### 12.2 Feature snapshot (deferred)
- At `t₀`, the feature builder reconstructs the §3.2 feature groups from:
  - PM2.5 observations long-format table, filtered `observed_at ≤ t₀`.
  - Weather 24h forecast tables (national + region sub-period), filtered `timestamp ≤ t₀` and aligned per §5.
- The feature snapshot is persisted (keyed by `issuance_date, region`) — enables reproducible retraining and what-if replay per proposal §11 (what-if scenario determinism).

### 12.3 Predictor service (deferred)
- Tool `predict_pm25_next_day(issuance_date, region)` per PM25 audit §21-E.
- Loads the selected models for the regression targets for that region (selected per §11.4), runs inference, returns `{pm25_next_day_max, pm25_next_day_mean, model_refs}`. (Classifier outputs are not part of this deferred design — they would be re-scoped if/when classifier targets are ever implemented per §11A.2.)
- All numeric results produced by the model; the rule engine (proposal §3, §16) decides severity / advisory, not the LLM.

### 12.4 Drift & retraining (deferred — NOT auto in the initial Phase 1)
- Compare each issued forecast's MAE vs the realized `pm25_next_day_max` over a rolling 30-day window. Alert if rolling MAE exceeds the training-time MAE threshold for `N` consecutive days.
- **Automatic monthly retrain and automatic model auto-promotion (`active=true` flipping) are explicitly deferred (§11A.2).** Any re-run of the comparison experiment in Phase 1 is a human-triggered offline action that records a fresh experiment artefact (§11.6), not an automatic promotion. A human decides whether the new artefact's selected model replaces the prior one.

### 12.5 Fallback when model unavailable (deferred)
- Per proposal §18 "no silent fallbacks": if the `active` model is not loadable (signature mismatch, missing file), the predictor returns `mode=baseline` and surfaces `pm25_next_day_max_BL_persist` (§9.1) with a `degraded=true` flag visible on the dashboard. Never silently returns zeros or empty. (This is design for the production phase; the initial Phase 1 implementation has no live inference path, so no fallback path exists.)

---

## 13. Open VERIFY items (not invented; explicitly open)

These are uncertain and must be confirmed before final training, not assumed:

| Item | Where in this doc | Source |
|---|---|---|
| NEA advisory PM2.5 thresholds (50, 100 µg/m³) for the **deferred** classifier targets | §1.3 | PM25 audit §20 caveat 2; assumption derived from WHO ranges. Not blocking for the initial regression-only Phase 1. |
| NEA monsoon season window dates (NE vs SW vs transitional) | §3.2 Group B | Assumed convention |
| Tree / linear / ridge pipeline: `StandardScaler` / `OneHotEncoder` fit-on-train-only defaults in scikit-learn wrappers | §8.3 | Library default |
| Region-polygon identity between Weather 24h and PM2.5 datasets (no boundary drift over years) | §5.3 | Weather audit §7 + PM25 audit §7 — region names match but polygons are external |
| NEA PSI national readings availability/granularity | §2.3, §3.3 | PM25 audit §20 caveat 8 |
| NEA rainfall / wind **observations** availability | §2.3, §3.3 | PM25 audit §20 caveat 8; Weather audit is forecasts only |
| NEA 2-hour rainfall nowcast (live) availability | §3.1, §3.3 | Not in repo |
| **Whether a 2025 / 2026 NEA 24-hour weather forecast export can be obtained** (would allow re-scoping §8.1 to a larger split and the test set to a more recent period) | §5.4, §8.1 | Weather audit §12 (max date 2024-12-31); no 2025/2026 file present in repo. **Until resolved, the §8.1 split ends at 2024-12-31.** |
| Test-split haze-event count > 0 per region (affects *interpretation* of regression metrics, not the evaluation procedure) | §8.1, §10.6 | PM25 audit §17: documented SE haze windows were Oct 2015 + Sep 2019; under the corrected §8.1 split these fall in train (Sep 2019) or before-weather-coverage (Oct 2015). The 2023-07 → 2024-12 test window is haze-tail-light by construction, not by error. |
| Whether the optional CatBoost candidate (§11.3) provides materially better native categorical handling than one-hot for the actual Phase-1 feature types | §11.3 | Conditional — to be decided at implementation time |
| 7-day rolling baseline vs longer windows (14-day, 30-day) | §9.3 | Tunable |
| PM2.5 region-aggregation method (mean vs max of stations) | §2.1 | PM25 audit §7 caveat |
| Unit convention µg/m³ confirmed against NEA docs | §1.3, §2.1 | PM25 audit §8 caveat |
| Reference machine spec for training / inference wall-clock reporting (§10.4) | §10.4, §11.6 | To be specified at implementation time |

Items previously listed that have been removed because their subject is no longer in initial scope (classifiers, quantile regression, stacked ensembles): classifier threshold, classifier target recall, ensemble marginal benefit. These will re-enter the VERIFY table if/when their associated deferred items are pulled into a future phase.

---

## 14. Out of scope for this spec (deferred or implementation-defined)

- Hyperparameter search *values* (only metric criteria, selection rules, and reproducibility requirements are fixed; the search space is implementation-defined at run time).
- Live-data integration (Phase 3 per proposal §20) — see §11A.2.
- Dashboard rendering of forecasts (frontend Phase 2 per proposal §13) — see §11A.2.
- Classifier targets `exceed_50` / `exceed_100` and all associated machinery — see §1.3, §11A.2.
- Quantile regression, stacked ensembles, focal loss, probability calibration — see §11A.2.
- Automatic drift monitoring, automatic monthly retraining, automatic model auto-promotion — see §11A.2, §12.4.
- Single live predictor tool / fallback path — see §11A.2, §12.
- PSI 24h forecasting (depends on whether NEA publishes a PSI forecast — proposal §5).
- Multi-day horizons (Phase 2).
- Haze-stratified MAE reporting on the test split (§10.6 — blocked on split-strategy decision).
- The global-with-region-feature strategy is **optional, comparison-only in the initial Phase 1** and is not a recommended strategy until §7.2 validation evidence is produced — implementing it as a replacement default is out of scope.

The authoritative enumeration of what is IN scope for the initial Phase 1 implementation is §11A.1; the authoritative enumeration of what is deferred is §11A.2.

---

## 15. Phase 1 implementation acceptance criteria

The initial Phase 1 ML implementation is considered **complete** when, reproducibly and from the immutable raw CSVs forward:

1. **Data ingestion works** — PM2.5 ingests to long-format `observations` per PM25 audit §21-A; Weather 24h ingests to `weather_24h_forecast` + `weather_24h_forecast_period` per Weather audit §16/§17; raw CSVs are unchanged; defects are flagged via `data_quality_flag` (or equivalent) and not silently dropped; haze `>200` values preserved; `is_haze_period` boolean materialised.
2. **Leakage-safe features are generated** — every feature respects `t₀ = 23:00 Asia/Singapore` cutoff; PM2.5 features computed only over `observed_at ≤ t₀`, weather features only over `timestamp ≤ t₀` aligned per §5; no fold-lookahead normalisation; §8.3 guards are verified for each candidate.
3. **Next-day targets are generated** — `pm25_next_day_mean` and `pm25_next_day_max` are produced for every `(issuance_date, region)` eligible row, target window `[t₀+1h, t₀+24h]`, exactly 24 hours per issued forecast; classifier targets are not produced (deferred).
4. **Baselines are established** — B-A persistence, B-B climatological, B-C trailing-7-day are computed for both regression targets per region on the chronological splits, and their metrics are recorded alongside candidates.
5. **Multiple candidate ML models are trained** — at minimum the M1 (linear/ridge), M2 (Random Forest or Extra Trees), M3 (XGBoost), M4 (LightGBM) candidates in §11.2 are trained for both targets, on the train split; M5 (CatBoost) included only if its §11.3 rationale is documented.
6. **Models are compared on validation data** — every candidate's validation-split MAE, RMSE, and R² are recorded per region / per target / per model, alongside the three baselines; the persistence-delta per §10.3 is reported; training and inference time + complexity proxies per §10.4 are recorded.
7. **The best model is selected for each target** — selection is per §11.4: per target, per region (default per-region strategy), independently, by validation metrics only; §9.4 baseline rule applied (must beat persistence); selection rationale recorded in the §11.6 experiment artefact.
8. **Selected models are evaluated on the untouched chronological test set** — each selected model is evaluated exactly once on the §8.1 test split; per-region, per-target MAE / RMSE / R² + persistence-delta are reported; no re-selection or re-tuning based on test metrics.
9. **Metrics and experiment results are saved reproducibly** — the §11.6 experiment artefact is persisted (library versions, splits, seeds, per-candidate validation metrics, per-selected-model test metrics, model artefact paths, selection rationale); re-running the experiment from the same ingested data yields byte-identical metric values (modulo non-determinism explicitly logged, e.g. XGBoost/LightGBM threading).

Acceptance is at the **implementation level**; nothing in §11A.2 (classifier / quantile / ensemble / live-inference / dashboard / auto-retrain / auto-promotion) is required for Phase 1 to be considered complete. Those items are evaluated separately when/if they are pulled into a future phase.
