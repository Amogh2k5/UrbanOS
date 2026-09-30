"""Weather predictor — reuses the completed Phase 1B weather run (phase1b_v1).

The Phase 1B run trained 7 next-day targets (temperature/RH/wind high/low +
forecast_code) over the national weather forecast dataset. Selection outcome:
`bl_persist` won every target on validation (no ML candidate beat persistence),
so the run persisted **no** `*.joblib` artifacts. Per the audit (proposal §18:
no silent fallbacks) we therefore expose the persistence baseline transparently.

This module does NOT train or retrain. It loads `summary.json` + `selections.csv`
from the run dir, emits per-target next-day weather predictions using the
selected strategy (persistence baseline), and returns a structured
`WeatherPrediction` dataclass consumable by the LangGraph agent and the
EnvironmentReport envelope.

Persistence rule (matches `ml/phase1b_weather/baselines.py`):
    predicted_next_day_value = latest_observed_value_at_or_before(t0)

For the Phase 1B national dataset the "observation" at t0 is the latest NEA
national forecast issue with `timestamp <= t0` (matching weather_loader.py).
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from backend.app.environment.weather.data import latest_forecast_summary
from ml.pm25.config import REPO_ROOT

SG_TZ = "Asia/Singapore"
DEFAULT_WEATHER_RUN_ID = "phase1b_v1"
DEFAULT_WEATHER_RUNS_DIR = (
    REPO_ROOT / "ml" / "datasets" / "processed" / "phase1b_weather" / "runs"
)

# Targets and persistence field mapping (which source column each target
# persists). Source columns come from the ingested national weather table.
REGRESSION_TARGETS = (
    "temperature_high_next_day",
    "temperature_low_next_day",
    "relative_humidity_high_next_day",
    "relative_humidity_low_next_day",
    "wind_speed_high_next_day",
    "wind_speed_low_next_day",
)
CLASSIFICATION_TARGET = "forecast_code_next_day"
ALL_TARGETS = REGRESSION_TARGETS + (CLASSIFICATION_TARGET,)

# Map each next-day target to the source observation column it persists.
_PERSIST_FIELD = {
    "temperature_high_next_day": "temperature_high",
    "temperature_low_next_day": "temperature_low",
    "relative_humidity_high_next_day": "relative_humidity_high",
    "relative_humidity_low_next_day": "relative_humidity_low",
    "wind_speed_high_next_day": "wind_speed_high",
    "wind_speed_low_next_day": "wind_speed_low",
    "forecast_code_next_day": "forecast_code",
}

log = logging.getLogger(__name__)


@dataclass
class TargetPrediction:
    target: str
    value: Optional[float]            # None for classification when no issue found
    code: Optional[str]              # populated for forecast_code_next_day
    strategy: str                    # "bl_persist" | <model_name>
    is_ml_model: bool                # False for persistence fallback
    fallback_reason: Optional[str]
    metrics: Dict[str, object] = field(default_factory=dict)


@dataclass
class WeatherPrediction:
    """Result of running the weather predictor at issuance t0."""
    prediction_timestamp: pd.Timestamp
    selected_model: str   # overall (primary target) selection — all `bl_persist` for phase1b_v1
    is_ml_model: bool
    targets: Dict[str, TargetPrediction]
    forecast_issue_timestamp: Optional[pd.Timestamp]
    fallback_reason: Optional[str]

    def to_dict(self) -> dict:
        return {
            "prediction_timestamp": self.prediction_timestamp.isoformat(),
            "selected_model": self.selected_model,
            "is_ml_model": self.is_ml_model,
            "label": "baseline_fallback" if not self.is_ml_model else "ml_model",
            "fallback_reason": self.fallback_reason,
            "forecast_issue_timestamp": (
                self.forecast_issue_timestamp.isoformat()
                if self.forecast_issue_timestamp is not None
                else None
            ),
            "targets": {
                t: {
                    "target": p.target,
                    "value": p.value,
                    "code": p.code,
                    "strategy": p.strategy,
                    "is_ml_model": p.is_ml_model,
                    "label": "baseline_fallback" if not p.is_ml_model else "ml_model",
                    "fallback_reason": p.fallback_reason,
                    "metrics": p.metrics,
                }
                for t, p in self.targets.items()
            },
        }


class WeatherPredictor:
    """Loads Phase 1B weather run + ingested national table; emits persistence predictions.

    Reuses the ingestion path from `backend.app.environment.weather_loader` so the
    same NEA-frost ingestion semantics as the Environment module apply.
    """

    def __init__(
        self,
        runs_dir: Path = DEFAULT_WEATHER_RUNS_DIR,
        run_id: str = DEFAULT_WEATHER_RUN_ID,
    ) -> None:
        self.runs_dir = Path(runs_dir)
        self.run_id = run_id
        self.run_dir = self.runs_dir / run_id
        self.summary_path = self.run_dir / "summary.json"
        self.selections_csv = self.run_dir / "selections.csv"
        if not self.summary_path.exists():
            raise FileNotFoundError(
                f"Weather run summary.json missing: {self.summary_path}"
            )
        self._summary: Optional[dict] = None
        self._selections: Optional[Dict[str, dict]] = None

    # ------------------------------------------------------------------ public

    def predict(
        self,
        t0: pd.Timestamp,
        weather_national: pd.DataFrame,
        weather_period: Optional[pd.DataFrame] = None,
    ) -> WeatherPrediction:
        """Produce next-day weather prediction at issuance t0.

        Uses the latest NEA national forecast issue with `timestamp <= t0`
        (reuses weather_loader.latest_forecast_summary) and applies the
        persistence rule per target selected in selections.csv.
        """
        t0 = _coerce_tz(t0)
        summary, issue_ts = latest_forecast_summary(
            weather_national, t0, period=weather_period
        )

        sel = self._load_selections()
        targets: Dict[str, TargetPrediction] = {}
        for target in ALL_TARGETS:
            decision = sel.get(target)
            if decision is None:
                targets[target] = TargetPrediction(
                    target=target,
                    value=None,
                    code=None,
                    strategy="unknown",
                    is_ml_model=False,
                    fallback_reason=f"no selection row for {target}",
                )
                continue

            strategy = decision["selected_model"]
            is_ml = decision["is_ml_model"]
            rationale = decision.get("selection_rationale")

            if strategy != "bl_persist" and is_ml:
                # Phase 1B persisted no joblib artifacts (persistence won all
                # targets). If a future run selects an ML model, this is where
                # inference would dispatch. For now we surface a clear flag.
                targets[target] = TargetPrediction(
                    target=target,
                    value=None,
                    code=None,
                    strategy=strategy,
                    is_ml_model=True,
                    fallback_reason=(
                        f"ML model '{strategy}' selected but no inference path "
                        "implemented for weather (run persisted no joblib artifacts "
                        "because persistence won all targets)."
                    ),
                )
                continue

            # Persistence baseline: persist the latest observed value at or before t0.
            targets[target] = self._persist_target(
                target, summary, issue_ts, rationale
            )

        primary = sel.get("temperature_high_next_day", {})
        primary_strategy = primary.get("selected_model", "bl_persist")
        primary_is_ml = primary.get("is_ml_model", False)
        primary_rationale = primary.get("selection_rationale")

        return WeatherPrediction(
            prediction_timestamp=t0,
            selected_model=primary_strategy,
            is_ml_model=primary_is_ml,
            targets=targets,
            forecast_issue_timestamp=issue_ts,
            fallback_reason=(None if primary_is_ml else primary_rationale),
        )

    # --------------------------------------------------------------- internals

    def _persist_target(
        self,
        target: str,
        summary,  # WeatherForecastSummary or None
        issue_ts: Optional[pd.Timestamp],
        rationale: Optional[str],
    ) -> TargetPrediction:
        field_name = _PERSIST_FIELD[target]
        if summary is None:
            return TargetPrediction(
                target=target,
                value=None,
                code=None,
                strategy="bl_persist",
                is_ml_model=False,
                fallback_reason=(
                    "no_nea_weather_forecast_at_t0; persistence unavailable. "
                    f"{rationale or ''}".strip()
                ),
            )

        if target == CLASSIFICATION_TARGET:
            return TargetPrediction(
                target=target,
                value=None,
                code=summary.national_forecast_code,
                strategy="bl_persist",
                is_ml_model=False,
                fallback_reason=None,
            )

        # Regression: pull the matching attribute off the summary dataclass.
        attr_map = {
            "temperature_high_next_day": "temperature_high_c",
            "temperature_low_next_day": "temperature_low_c",
            "relative_humidity_high_next_day": "relative_humidity_high_pct",
            "relative_humidity_low_next_day": "relative_humidity_low_pct",
            "wind_speed_high_next_day": "wind_speed_high_kmh",
            "wind_speed_low_next_day": "wind_speed_low_kmh",
        }
        val = getattr(summary, attr_map[target], None)
        return TargetPrediction(
            target=target,
            value=val,
            code=None,
            strategy="bl_persist",
            is_ml_model=False,
            fallback_reason=None,
        )

    def summary(self) -> dict:
        if self._summary is None:
            with open(self.summary_path, "r", encoding="utf-8") as f:
                self._summary = json.load(f)
        return self._summary

    def _load_selections(self) -> Dict[str, dict]:
        """Return {target: selection_row_dict} from selections.csv.

        Phase 1B's selections.csv has one row per target (no region dimension).
        Each row carries selected_model + selection_rationale + val/test metrics.
        """
        if self._selections is not None:
            return self._selections
        if not self.selections_csv.exists():
            raise FileNotFoundError(
                f"Weather selections.csv missing: {self.selections_csv}"
            )
        out: Dict[str, dict] = {}
        with open(self.selections_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                target = row["target"]
                sel = row["selected_model"]
                # is_ml: anything that isn't a baseline label
                is_ml = sel not in ("bl_persist", "bl_clim", "bl_trail7", "", None)
                # Parse val metrics (stringified JSON in the CSV)
                val_metrics = _safe_json(row.get("val_metrics"))
                test_metrics = _safe_json(row.get("test_metrics"))
                out[target] = {
                    "selected_model": sel,
                    "is_ml_model": is_ml,
                    "selection_rationale": row.get("selection_rationale"),
                    "val_metrics": val_metrics,
                    "test_metrics": test_metrics,
                }
        self._selections = out
        return out


def _coerce_tz(t0: pd.Timestamp) -> pd.Timestamp:
    t0 = pd.Timestamp(t0)
    if t0.tzinfo is None:
        return t0.tz_localize(SG_TZ)
    return t0.tz_convert(SG_TZ)


def _safe_json(s: Optional[str]) -> dict:
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {}
