"""Selection table loader — bridges the completed Phase 1 ML experiment to live use.

Reads `selections.csv` from the run artifact dir. This is the table that recorded,
per (region, target), which model the experiment selected:

    - "catboost"  -> use the trained CatBoost joblib artifact
    - "bl_persist" -> use persistence (PM2.5 at t0 as next-day prediction). NOT an ML model.

The selection rule (spec §9.4): a candidate is eligible only if it beat persistence
on BOTH validation MAE and RMSE; otherwise fall back to persistence. We do not
re-run that logic — we trust the saved decision.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple


REGIONS = ("north", "south", "east", "west", "central")
TARGETS = ("pm25_next_day_mean", "pm25_next_day_max")


@dataclass(frozen=True)
class SelectionDecision:
    region: str
    target: str
    selected_model: str  # "catboost" | "bl_persist" | <other>
    is_ml_model: bool    # False for "bl_persist"
    fallback_reason: Optional[str]
    val_mae: Optional[float]
    persist_val_mae: Optional[float]


def _is_ml(model_name: str) -> bool:
    return model_name not in ("bl_persist", "bl_clim", "bl_trail7", "", None)


def load_selections(selections_csv: Path) -> Dict[Tuple[str, str], SelectionDecision]:
    """Read selections.csv into a {(region, target): SelectionDecision} map."""
    if not selections_csv.exists():
        raise FileNotFoundError(f"selections.csv not found: {selections_csv}")

    out: Dict[Tuple[str, str], SelectionDecision] = {}
    with open(selections_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            region = row["region"]
            target = row["target"]
            sel = row["selected_model"]
            rationale = row.get("selection_rationale", "") or ""

            val_raw = row.get("val_metrics", "")
            pers_raw = row.get("persistence_val_metrics", "")
            val_mae = _parse_mae(val_raw)
            pers_mae = _parse_mae(pers_raw)

            out[(region, target)] = SelectionDecision(
                region=region,
                target=target,
                selected_model=sel,
                is_ml_model=_is_ml(sel),
                fallback_reason=(None if _is_ml(sel) else rationale),
                val_mae=val_mae,
                persist_val_mae=pers_mae,
            )

    # Sanity: every (region, target) combination should be represented.
    missing = [(r, t) for r in REGIONS for t in TARGETS if (r, t) not in out]
    if missing:
        raise ValueError(f"selections.csv missing rows for: {missing}")
    return out


def _parse_mae(metrics_str: str) -> Optional[float]:
    """Extract the 'mae' float from a stringified dict like "{'mae': 1.95, 'rmse': ...}"."""
    if not metrics_str:
        return None
    # Cheap parse: find 'mae': <number>
    import re
    m = re.search(r"'mae':\s*([0-9eE.+-]+)", metrics_str)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def per_region_target_decisions(
    selections: Dict[Tuple[str, str], SelectionDecision],
    region: str,
) -> Dict[str, SelectionDecision]:
    """Return {target: SelectionDecision} for one region."""
    return {t: selections[(region, t)] for t in TARGETS}
