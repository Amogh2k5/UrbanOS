"""Run the Environment module end-to-end and print the Environment Situation Report.

Usage (from repo root):
    python -m backend.app.environment.run_environment                     # auto t0
    python -m backend.app.environment.run_environment --t0 2024-12-30T23:00:00+08:00
    python -m backend.app.environment.run_environment --t0 2024-12-30  # date -> normalized to 23:00 +08:00

Requirements: pandas, numpy, scikit-learn, catboost, joblib (see requirements/phase1_pm25.txt).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

# Allow running as `python backend/app/environment/run_environment.py` from repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.environment.environment_module import EnvironmentModule
from backend.app.environment.result import EnvironmentReport
from ml.pm25.config import RAW_PM25_CSV, RAW_WEATHER_DIR, RUNS_DIR


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="UrbanOS Environment module runner")
    p.add_argument(
        "--runs-dir", type=str, default=str(RUNS_DIR),
        help="Directory containing phase1_v1/ run artifacts (default: ml/datasets/processed/phase1_pm25/runs).",
    )
    p.add_argument("--run-id", type=str, default="phase1_v1", help="Experiment run id (default: phase1_v1).")
    p.add_argument("--pm25-csv", type=str, default=str(RAW_PM25_CSV), help="Raw PM2.5 CSV path (default: NEA csv in repo).")
    p.add_argument("--weather-dir", type=str, default=str(RAW_WEATHER_DIR), help="Directory with NEA 24h weather CSVs.")
    p.add_argument(
        "--t0", type=str, default=None,
        help="Issuance cutoff t0, ISO or YYYY-MM-DD. If omitted, uses the latest available observation date.",
    )
    p.add_argument("--out", type=str, default=None, help="Optional path to write the JSON report.")
    p.add_argument("--verbose", action="store_true", help="Verbose logging.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)

    t0_arg = None
    if args.t0:
        # If date-only, normalize to 23:00 Asia/Singapore per spec.
        t0_arg = pd.Timestamp(args.t0)
        if t0_arg.tzinfo is None:
            t0_arg = t0_arg.tz_localize("Asia/Singapore")
        if t0_arg.hour == 0 and t0_arg.minute == 0:
            t0_arg = t0_arg + pd.Timedelta(hours=23)

    module = EnvironmentModule(
        runs_dir=Path(args.runs_dir),
        run_id=args.run_id,
        pm25_csv=Path(args.pm25_csv),
        weather_dir=Path(args.weather_dir),
    )

    print("=" * 78, flush=True)
    print("UrbanOS Environment Module — Environment Situation Report", flush=True)
    print("=" * 78, flush=True)

    report = module.run(force_t0=t0_arg)

    # Concise human-readable summary to stdout, full JSON to --out if requested.
    _print_summary(report)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report.to_json(indent=2), encoding="utf-8")
        print(f"\nFull JSON report written to: {out_path}")

    return 0


def _print_summary(report: EnvironmentReport) -> None:
    d = report.to_dict()
    scope = d["scope"]
    print(f"Generated at      : {d['generated_at']}")
    print(f"Prediction t0     : {scope['prediction_timestamp']}")
    print(f"Forecast date     : {scope['forecast_date']}")
    print(f"Target window     : [{scope['target_window_start']}  ..  {scope['target_window_end']}]")
    print(f"Regions           : {', '.join(scope['regions'])}")
    print()

    wf = d["current_state"]["weather_forecast"]
    if wf:
        print("--- NEA 24h Weather Forecast (at t0) ---")
        print(f"  Issue timestamp       : {wf['forecast_issue_timestamp']}")
        print(f"  Valid period          : {wf['valid_period_start']}  ->  {wf['valid_period_end']}")
        print(f"  National forecast     : {wf['national_forecast_text']} ({wf['national_forecast_code']})")
        print(f"  Temp (high/low)       : {wf['temperature_high_c']} / {wf['temperature_low_c']} °C (VERIFY unit)")
        print(f"  RH  (high/low)        : {wf['relative_humidity_high_pct']} / {wf['relative_humidity_low_pct']} %")
        print(f"  Wind (high/low)       : {wf['wind_speed_high_kmh']} / {wf['wind_speed_low_kmh']} km/h (VERIFY unit)")
        print(f"  Wind direction        : {wf['wind_direction']}")
    else:
        print("--- NEA 24h Weather Forecast (at t0) ---")
        print("  No eligible forecast issue at t0.")
    print()

    print("--- PM2.5 Predictions (next-day, per region) ---")
    print(f"  {'Region':<8} {'Model':<10} {'ML?':<5} {'mean (µg/m³)':<14} {'max (µg/m³)':<14} {'per-target models'}")
    for r in d["prediction"]["regions"]:
        tm = ", ".join(f"{t}={m}" for t, m in r["target_models"].items())
        print(
            f"  {r['region']:<8} {r['selected_model']:<10} "
            f"{'Y' if r['is_ml_model'] else 'N':<5} "
            f"{(_fmt(r['pm25_next_day_mean'])):<14} "
            f"{(_fmt(r['pm25_next_day_max'])):<14} "
            f"{tm}"
        )
    print()

    if d["data_quality_flags"]:
        print("--- Data Quality Flags ---")
        for f in d["data_quality_flags"]:
            print(f"  - {f}")
    else:
        print("--- Data Quality Flags --- (none)")
    print()

    prov = d["provenance"]
    print("--- Provenance ---")
    print(f"  Run id                    : {prov['run_id']}")
    print(f"  Run dir                   : {prov['run_dir']}")
    print(f"  ML-selected regions        : {prov['regions_ml']}")
    print(f"  Persistence regions       : {prov['regions_persist']}")
    if prov["regions_missing_features"]:
        print(f"  Regions missing features   : {prov['regions_missing_features']}")
    print(f"  Decisions:")
    for k, v in prov["decisions"].items():
        print(f"    {k:<40} = {v}")


def _fmt(v) -> str:
    return "n/a" if v is None else f"{float(v):.3f}"


if __name__ == "__main__":
    raise SystemExit(main())
