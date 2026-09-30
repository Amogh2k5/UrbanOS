"""LangGraph Environment Agent — orchestrates the UrbanOS Environment domain.

Graph:
    START
      -> prepare_inputs        (resolve t0 + ingest once; share cache)
      -> predict_pm25         (reuse PM25Predictor + Phase 1 artifacts)
      -> predict_weather      (reuse WeatherPredictor + Phase 1B run; persistence baseline)
      -> build_report         (assemble EnvironmentReport)
    -> END

Constraints honored:
    * NO training. NO model artifacts created or modified.
    * API data is NOT consumed here (LangGraph agent works off the ML
      artifacts + raw CSVs only). Live API feeds the FastAPI KPI endpoints.
    * Persistence is labelled as a baseline/fallback, not as an ML model.
    * EnvironmentReport contract (proposal §2) preserved.

State is a `TypedDict` carrying the shared ingest cache, t0, the partial
predictions, and the final report. The graph is built once per process
(`build_agent()`); `EnvironmentAgent.invoke(...)` runs it.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, TypedDict

import pandas as pd
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from backend.app.environment.environment_module import EnvironmentModule
from backend.app.environment.pm25.predictor import PM25Predictor, _IngestCache
from backend.app.environment.result import EnvironmentReport, RegionPrediction, utcnow_sg
from backend.app.environment.weather.predictor import WeatherPredictor, WeatherPrediction
from backend.app.environment.weather.data import latest_forecast_summary
from ml.pm25.config import RAW_PM25_CSV, RAW_WEATHER_DIR, RUNS_DIR

log = logging.getLogger(__name__)

SG_TZ = "Asia/Singapore"
REGIONS = ("north", "south", "east", "west", "central")
DEFAULT_PM25_RUN_ID = "phase1_v1"
DEFAULT_WEATHER_RUN_ID = "phase1b_v1"
DEFAULT_WEATHER_RUNS_DIR = (
    Path(RUNS_DIR).parent.parent / "phase1b_weather" / "runs"
)


# ---------------------------------------------------------------- state

class AgentState(TypedDict, total=False):
    """State passed through the LangGraph nodes."""
    t0: pd.Timestamp
    ingest_cache: _IngestCache
    pm25_features_df: pd.DataFrame
    pm25_per_region: Dict[str, RegionPrediction]
    pm25_diag: Dict[str, Any]
    weather_prediction: WeatherPrediction
    report_dict: Dict[str, Any]
    pm25_run_id: str
    weather_run_id: str
    errors: Annotated[List[str], lambda a, b: a + b]


# ---------------------------------------------------------------- agent

class EnvironmentAgent:
    """Thin orchestrator wrapping the LangGraph environment agent.

    Reuses `PM25Predictor` (Phase 1) and `WeatherPredictor` (Phase 1B). All
    ingestion happens once in `prepare_inputs` and is threaded through state
    so neither predictor re-reads the raw CSVs mid-graph.
    """

    def __init__(
        self,
        pm25_runs_dir: Path = RUNS_DIR,
        pm25_run_id: str = DEFAULT_PM25_RUN_ID,
        weather_runs_dir: Path = DEFAULT_WEATHER_RUNS_DIR,
        weather_run_id: str = DEFAULT_WEATHER_RUN_ID,
        pm25_csv: Path = RAW_PM25_CSV,
        weather_dir: Path = RAW_WEATHER_DIR,
    ) -> None:
        self.pm25_runs_dir = Path(pm25_runs_dir)
        self.pm25_run_id = pm25_run_id
        self.weather_runs_dir = Path(weather_runs_dir)
        self.weather_run_id = weather_run_id
        self.pm25_csv = Path(pm25_csv)
        self.weather_dir = Path(weather_dir)

        self.pm25_predictor = PM25Predictor(
            runs_dir=self.pm25_runs_dir, run_id=self.pm25_run_id
        )
        self.weather_predictor = WeatherPredictor(
            runs_dir=self.weather_runs_dir, run_id=self.weather_run_id
        )
        # Underlying module reused for EnvironmentReport assembly + provenance.
        self._module = EnvironmentModule(
            runs_dir=self.pm25_runs_dir,
            run_id=self.pm25_run_id,
            pm25_csv=self.pm25_csv,
            weather_dir=self.weather_dir,
        )

        self.graph: CompiledStateGraph = self._build_graph()

    # ---------------------------------------------------------------- public

    def invoke(
        self, prediction_timestamp: Optional[pd.Timestamp] = None
    ) -> Dict[str, Any]:
        """Run the graph. Returns the final state (contains 'report_dict')."""
        t0 = self._coerce_t0(prediction_timestamp)
        initial: AgentState = {
            "t0": t0,
            "pm25_run_id": self.pm25_run_id,
            "weather_run_id": self.weather_run_id,
            "errors": [],
        }
        return self.graph.invoke(initial, debug=False)

    def run_report(self, prediction_timestamp: Optional[pd.Timestamp] = None) -> dict:
        """Convenience: returns just the final `report_dict`."""
        return self.invoke(prediction_timestamp)["report_dict"]

    # ---------------------------------------------------------------- graph

    def _build_graph(self) -> CompiledStateGraph:
        g = StateGraph(AgentState)
        g.add_node("prepare_inputs", self._node_prepare_inputs)
        g.add_node("predict_pm25", self._node_predict_pm25)
        g.add_node("predict_weather", self._node_predict_weather)
        g.add_node("build_report", self._node_build_report)

        g.add_edge(START, "prepare_inputs")
        g.add_edge("prepare_inputs", "predict_pm25")
        g.add_edge("predict_pm25", "predict_weather")
        g.add_edge("predict_weather", "build_report")
        g.add_edge("build_report", END)
        return g.compile()

    # ---------------------------------------------------------------- nodes

    def _node_prepare_inputs(self, state: AgentState) -> Dict[str, Any]:
        t0 = state["t0"]
        log.info("prepare_inputs: ingesting PM2.5 + Weather for t0=%s", t0.isoformat())
        cache = self._module._ensure_ingested()
        return {"ingest_cache": cache}

    def _node_predict_pm25(self, state: AgentState) -> Dict[str, Any]:
        t0 = state["t0"]
        cache = state["ingest_cache"]
        log.info("predict_pm25: predicting all 5 regions @ t0=%s", t0.isoformat())
        features_df, per_region, diag = self.pm25_predictor.predict_all_regions(
            prediction_timestamp=t0,
            pm25_csv=self.pm25_csv,
            weather_dir=self.weather_dir,
            ingest_cache=cache,
        )
        return {
            "pm25_features_df": features_df,
            "pm25_per_region": per_region,
            "pm25_diag": diag,
        }

    def _node_predict_weather(self, state: AgentState) -> Dict[str, Any]:
        t0 = state["t0"]
        cache = state["ingest_cache"]
        log.info("predict_weather: phase1b_v1 lookup @ t0=%s", t0.isoformat())
        weather_pred = self.weather_predictor.predict(
            t0=t0,
            weather_national=cache.weather_national,
            weather_period=cache.weather_period,
        )
        return {"weather_prediction": weather_pred}

    def _node_build_report(self, state: AgentState) -> Dict[str, Any]:
        t0 = state["t0"]
        cache = state["ingest_cache"]
        per_region = state["pm25_per_region"]
        diag = state.get("pm25_diag", {})
        weather_pred: WeatherPrediction = state["weather_prediction"]

        # Re-use the module's run() so the EnvironmentReport contract and
        # provenance stay identical. We then enrich the report `prediction`
        # block with the weather prediction.
        report: EnvironmentReport = self._module.run(force_t0=t0)
        report_dict = report.to_dict()

        # ---- Enrich the `prediction` block with weather + strategy labels.
        pm25_section = report_dict["prediction"].get("regions", [])
        weather_dict = weather_pred.to_dict()

        report_dict["prediction"]["weather_next_day"] = weather_dict
        report_dict["prediction"]["strategies"] = {
            "pm25": self._summarize_pm25_strategy(per_region),
            "weather": {
                "selected_model": weather_pred.selected_model,
                "is_ml_model": weather_pred.is_ml_model,
                "label": "baseline_fallback" if not weather_pred.is_ml_model else "ml_model",
                "fallback_reason": weather_pred.fallback_reason,
                "note": (
                    "Persistence baseline (Phase 1B selection). No ML artifact "
                    "available because no candidate beat persistence on validation."
                    if not weather_pred.is_ml_model
                    else "ML model inference."
                ),
            },
        }
        report_dict["prediction"]["prediction_timestamp"] = t0.isoformat()

        # Surface any LangGraph-collected errors as a data quality flag.
        errs = state.get("errors", [])
        if errs:
            report_dict.setdefault("data_quality_flags", []).extend(
                f"agent_error:{e}" for e in errs
            )

        # Mark the report generation time freshly.
        report_dict["generated_at"] = utcnow_sg().isoformat()

        return {"report_dict": report_dict}

    # ---------------------------------------------------------------- helpers

    def _coerce_t0(self, t0: Optional[pd.Timestamp]) -> pd.Timestamp:
        if t0 is None:
            # Compute default from PM2.5 latest observation hour.
            cache = self._module._ensure_ingested()
            return self._module._default_t0_from_pm25(
                cache.pm25_long, cache.weather_national
            )
        ts = pd.Timestamp(t0)
        if ts.tzinfo is None:
            ts = ts.tz_localize(SG_TZ)
        return ts.tz_convert(SG_TZ)

    @staticmethod
    def _summarize_pm25_strategy(
        per_region: Dict[str, RegionPrediction],
    ) -> dict:
        ml_regions = sorted(
            r for r, p in per_region.items() if p.is_ml_model
        )
        persist_regions = sorted(
            r for r, p in per_region.items()
            if not p.is_ml_model and p.selected_model == "bl_persist"
        )
        missing_regions = sorted(
            r for r, p in per_region.items()
            if p.selected_model == "MISSING_FEATURES"
        )
        overall: str
        if missing_regions and not ml_regions:
            overall = "missing_features"
        elif not ml_regions:
            overall = "baseline_fallback"
        else:
            overall = "ml_model"
        return {
            "overall": overall,
            "regions_ml": ml_regions,
            "regions_persist": persist_regions,
            "regions_missing": missing_regions,
            "label": (
                "ml_model" if ml_regions else "baseline_fallback"
            ),
            "note": (
                "Persistence baseline selected by Phase 1 selection policy "
                "(no ML candidate beat persistence on validation MAE+RMSE). "
                "Persistence is a baseline, not an ML model."
                if not ml_regions
                else "Phase 1 CatBoost ML artifact(s) used."
            ),
        }


def build_agent() -> EnvironmentAgent:
    """Construct the default LangGraph Environment agent with repo-standard paths."""
    return EnvironmentAgent()
