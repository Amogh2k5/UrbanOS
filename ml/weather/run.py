"""Entrypoint for the Phase 1B Weather ML pipeline.

Usage (from repo root):
    python -m ml.phase1b_weather.run --run-id phase1b_v1
    python -m ml.phase1b_weather.run --no-catboost
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Permit running as `python ml/phase1b_weather/run.py` from repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ml.phase1b_weather.config import get_default_config
from ml.phase1b_weather.experiment import run_experiment


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="UrbanOS Phase 1B Weather ML experiment runner")
    p.add_argument("--run-id", type=str, default="phase1b_v1")
    p.add_argument("--seed", type=int, default=20240101)
    p.add_argument("--no-catboost", action="store_true", help="Skip CatBoost (default: enabled)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = get_default_config()
    cfg.run_id = args.run_id
    cfg.random_seed = args.seed
    cfg.enable_catboost = not args.no_catboost
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
    summary = run_experiment(cfg)
    print("=" * 70)
    print("Phase 1B Weather experiment complete.")
    print(f"  run_id          : {summary['run_id']}")
    print(f"  run_dir         : {summary['run_dir']}")
    print(f"  modelling rows  : {summary['modelling_dataset_rows']}")
    print(f"  split           : train={summary['split_train_rows']}, val={summary['split_val_rows']}, test={summary['split_test_rows']}")
    print(f"  targets         : {summary['targets']}")
    print(f"  candidates      : {summary['candidates']}")
    print(f"  baselines        : {summary['baselines']}")
    print("=" * 70)
    print("Selections:")
    for sel in summary["selections"]:
        print(f"  {sel['target']:<38} -> {sel['selected_model']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
