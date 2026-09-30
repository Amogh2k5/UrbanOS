"""CLI runner for the LangGraph Environment Agent.

Runs the graph end-to-end (no training, no API calls — graph works off ML
artifacts + raw CSVs only) and prints the EnvironmentReport JSON.

Usage (from repo root):
    python -m backend.app.environment.run_agent
    python -m backend.app.environment.run_agent --t0 2024-12-30T23:00:00+08:00
    python -m backend.app.environment.run_agent --out report.json --verbose

To also start the KPI HTTP server (separate concern):
    uvicorn backend.app.main:app --port 8010
    (or set URBANOS_API_OFFLINE=1 to force the offline fixtures)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

# Allow running as a plain script from repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.environment.agent import EnvironmentAgent, build_agent
from ml.pm25.config import RAW_PM25_CSV, RAW_WEATHER_DIR, RUNS_DIR


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the LangGraph Environment agent.")
    p.add_argument(
        "--t0", type=str, default=None,
        help="Issuance cutoff t0, ISO or YYYY-MM-DD. Defaults to latest available PM2.5 obs.",
    )
    p.add_argument("--pm25-run-id", type=str, default="phase1_v1")
    p.add_argument("--weather-run-id", type=str, default="phase1b_v1")
    p.add_argument("--pm25-runs-dir", type=str, default=str(RUNS_DIR))
    p.add_argument(
        "--weather-runs-dir", type=str,
        default=str(Path(RUNS_DIR).parent.parent / "phase1b_weather" / "runs"),
    )
    p.add_argument("--pm25-csv", type=str, default=str(RAW_PM25_CSV))
    p.add_argument("--weather-dir", type=str, default=str(RAW_WEATHER_DIR))
    p.add_argument("--out", type=str, default=None, help="Optional path to write JSON report.")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)

    t0_arg = None
    if args.t0:
        t0_arg = pd.Timestamp(args.t0)
        if t0_arg.tzinfo is None:
            t0_arg = t0_arg.tz_localize("Asia/Singapore")
        if t0_arg.hour == 0 and t0_arg.minute == 0:
            t0_arg = t0_arg + pd.Timedelta(hours=23)

    agent = EnvironmentAgent(
        pm25_runs_dir=Path(args.pm25_runs_dir),
        pm25_run_id=args.pm25_run_id,
        weather_runs_dir=Path(args.weather_runs_dir),
        weather_run_id=args.weather_run_id,
        pm25_csv=Path(args.pm25_csv),
        weather_dir=Path(args.weather_dir),
    )

    print("=" * 78, flush=True)
    print("UrbanOS LangGraph Environment Agent", flush=True)
    print("=" * 78, flush=True)
    print(f"Graph nodes: START -> prepare_inputs -> predict_pm25 -> "
          f"predict_weather -> build_report -> END", flush=True)
    print(f"PM2.5 run   : {args.pm25_run_id}", flush=True)
    print(f"Weather run : {args.weather_run_id}", flush=True)
    print(f"t0          : {t0_arg.isoformat() if t0_arg is not None else '<auto: latest PM2.5 obs>'}", flush=True)
    print("-" * 78, flush=True)

    state = agent.invoke(prediction_timestamp=t0_arg)
    report = state["report_dict"]

    print(json.dumps(report, indent=2, default=str, ensure_ascii=False), flush=True)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        print(f"\nReport written to: {out_path}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
