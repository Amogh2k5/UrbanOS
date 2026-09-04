# UrbanOS Phase 1 PM2.5 ML pipeline

Offline ML pipeline for next-day PM2.5 prediction (per `docs/ml/PHASE1_PM25_ML_SPEC.md`).

## Quickstart

```powershell
# From repo root
pip install -r requirements/phase1_pm25.txt

python -m ml.phase1_pm25.run
# or with options
python -m ml.phase1_pm25.run --run-id my_run_v1
python -m ml.phase1_pm25.run --no-catboost       # skip CatBoost candidate (spec §11.3)
python -m ml.phase1_pm25.run --seed 12345
```

Artifacts are written to `ml/datasets/processed/phase1_pm25/runs/<run_id>/`.

## Pipeline overview

1. **Ingest** (`ingest_pm25.py`, `ingest_weather.py`) — reads the immutable raw CSVs and produces
   clean in-memory tables. Raw files are never modified.
   - PM2.5 → long format `(observed_at, region, pm25_value, is_haze_period, data_quality_flag)`
     per audit §21-A. Malformed `010:00:00` row repaired; 3 duplicate-timestamp pairs de-duplicated
     keeping later-in-file (audit §14).
   - Weather 24h → `weather_24h_forecast_national` (per `(date, timestamp)`, national fields)
     + `weather_24h_forecast_period` (per `(date, timestamp, time_period_start)`, regional fields).
     Year-offset rows flagged `year_offset_repaired` per audit §15.4.

2. **Feature builder** (`features.py`) — leakage-safe at `t0 = 23:00 Asia/Singapore`.
   - PM2.5 lag features (t-24/48/72h), rolling aggregates (6/12/24h mean + max, ending at t0).
   - Calendar features (hour, day of week, month, weekend, NEA monsoon flag).
   - Weather forecast features (national fields + region forecast code + rain/haze code counts).
   - Weather coverage features (`wf_window_coverage`, `wf_n_issues_used`).

3. **Targets** — `pm25_next_day_mean` and `pm25_next_day_max` computed from PM2.5 observations
   strictly after t0, window `[t0+1h, t0+24h]`. Per region.

4. **Chronological split** (`splits.py`) per spec §8.1 —
   train 2016-04-01 → 2021-12-31, validation 2022-01-01 → 2023-06-30, test 2023-07-01 → 2024-12-31.
   No random shuffling. Test set is used exactly once per selected model.

5. **Baselines** (`baselines.py`) — B-A persistence (last 24h at t0), B-B climatological
   (month × day-of-week bucket means, train-only), B-C trailing-7-day rolling.

6. **Candidate models** (`models.py`) — Ridge, Extra Trees, XGBoost, LightGBM, CatBoost
   (last one optional). All candidates share the SAME feature matrix and chronological splits.

7. **Model selection** (`experiment.py`, `metrics.py`) — per region and per target the best
   candidate is chosen on **validation MAE (primary), RMSE (tiebreak), R² (secondary)**.
   Only eligibility: must beat the persistence baseline on validation MAE + RMSE.
   The selected model is then evaluated once on the untouched test period.

## Reproducibility artefact

Every run produces, in `runs/<run_id>/`:
- `experiment_config.json` — full config incl. library versions, seed, split dates.
- `modelling_dataset.parquet` (or `.csv`) — the leakage-safe modelling dataset.
- `split_info.json` — train/validation/test start/end timestamps and date lists.
- `feature_definitions.json` — feature column definitions.
- `validation_metrics.csv` — every candidate's validation MAE/RMSE/R² + persistence delta.
- `validation_predictions.csv` — per-row predictions on validation.
- `test_predictions.csv` — per-row predictions on test for the selected model per (region, target).
- `selections.csv` — selected model + rationale per (region, target) + test metrics vs persistence.
- `models/<region>_<target>_<model>.joblib` — saved fitted pipelines.
- `summary.json` — top-level machine-readable summary of the run.
- `pm25_ingest_dropped_audit.csv` — audit-trail of PM2.5 de-duplication.
- `ingest_feature_reports.json` — diagnostics from ingest + feature build steps.

## Configuration

All paths, seeds, split dates, regions, and target definitions live in `config.py`.
No machine-specific hardcoded paths; everything derives from `REPO_ROOT`.

## What's implemented vs. deferred

In scope: data ingestion, leakage-safe feature generation, leakage-safe target
generation, baselines, multiple candidate ML models, validation-based model selection, one-shot
test evaluation, reproducibility artefact.

Deferred (per spec §11A.2): live APIs, dashboard, agent system, risk engine, classifiers,
quantile regression, stacking, automatic retraining, drift monitoring, production deployment.
