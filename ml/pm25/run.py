"""CLI entrypoint for the Phase 1 PM2.5 ML experiment.

Usage:
    python -m ml.phase1_pm25.run                 # default run_id timestamp-based
    python -m ml.phase1_pm25.run --run-id custom_name
    python -m ml.phase1_pm25.run --no-catboost   # disable CatBoost (spec §11.3 conditional)

This module builds a default ExperimentConfig (config.get_default_config),
optionally overrides from CLI flags, then calls experiment.run_experiment().
All configuration is centralized in config.py — no hardcoded machine-specific paths.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from .config import get_default_config
from .experiment import run_experiment


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the UrbanOS Phase 1 PM2.5 ML experiment")
    parser.add_argument("--run-id", default=None,
                        help="Run identifier (default: timestamp YYYYMMDD_HHMMSS_UTC)")
    parser.add_argument("--no-catboost", action="store_true",
                        help="Skip CatBoost candidate (spec §11.3: conditionally included)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Override random seed (default: config.RANDOM_SEED)")
    args = parser.parse_args(argv)

    cfg = get_default_config()
    if args.run_id is None:
        args.run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    cfg.run_id = args.run_id
    if args.no_catboost:
        cfg.enable_catboost = False
    if args.seed is not None:
        cfg.random_seed = args.seed

    summary = run_experiment(cfg)
    print()
    print("===== Phase 1 PM2.5 experiment complete =====")
    print(f"run_id          : {summary['run_id']}")
    print(f"run_dir         : {summary['run_dir']}")
    print(f"dataset rows    : {summary['modelling_dataset_rows']:,}")
    print(f"split train/val/test: {summary['split_train_rows']:,} / "
          f"{summary['split_val_rows']:,} / {summary['split_test_rows']:,}")
    print(f"seed            : {summary['random_seed']}")
    print(f"candidates      : {summary['candidates']}")
    print(f"baselines       : {summary['baselines']}")
    print()
    print("Selections (region | target | selected_model | val MAE | test MAE | persist val MAE | persist test MAE):")
    for s in summary["selections"]:
        print(f"  {s['region']:7s} | {s['target']:20s} | {s['selected_model']:12s} | "
              f"val MAE={s['val_mae']:.3f} | test MAE={s['test_mae']:.3f} | "
              f"persist val={s['persist_val_mae']:.3f} | persist test={s['persist_test_mae']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
