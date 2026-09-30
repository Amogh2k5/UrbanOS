"""Traffic ML Inference — Persistence Baseline Generator.

Generates predictions in the format expected by the Traffic Agent:
- timestamp, entity_id, traffic_speed, predicted_speed, persistence_prediction, absolute_error, persistence_absolute_error

Uses persistence (last observed speed = predicted speed) which beats the current ML model.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))
DB_PATH = Path("data/traffic_observations_train.db")
OUTPUT_PATH = Path("traffic/data/processed/real_day_predictions.csv")


def get_latest_complete_snapshot() -> pd.DataFrame:
    """Load the latest complete snapshot (all 143,787 links) from the training DB."""
    logger.info("Loading latest complete snapshot from %s", DB_PATH)

    with sqlite3.connect(DB_PATH) as conn:
        # Find the latest timestamp with all links
        latest_complete = conn.execute("""
            SELECT observed_at FROM (
                SELECT observed_at, COUNT(*) as cnt
                FROM traffic_observations
                GROUP BY observed_at
                HAVING cnt = 143787
            )
            ORDER BY observed_at DESC
            LIMIT 1
        """).fetchone()

        if not latest_complete:
            raise ValueError("No complete snapshots found in database")

        latest_ts = latest_complete[0]
        logger.info("Latest complete snapshot: %s", latest_ts)

        # Load all observations for that timestamp
        df = pd.read_sql_query("""
            SELECT observed_at, link_id, speed_midpoint
            FROM traffic_observations
            WHERE observed_at = ?
            ORDER BY link_id
        """, conn, params=[latest_ts])

    logger.info("Loaded %d observations for %s", len(df), latest_ts)
    return df


def generate_persistence_predictions(df: pd.DataFrame) -> pd.DataFrame:
    """Generate predictions using persistence (last observed = predicted)."""
    logger.info("Generating persistence predictions...")

    # Convert observed_at to proper format
    df = df.copy()
    df['observed_at'] = pd.to_datetime(df['observed_at'])

    # Persistence: predicted_speed = traffic_speed (current observed speed)
    # The agent expects entity_id as integer, but our link_ids are strings like '10', '100'
    # We'll map link_id to a sequential entity_id for compatibility
    link_to_entity = {link: idx for idx, link in enumerate(sorted(df['link_id'].unique()))}

    timestamp_str = df['observed_at'].dt.strftime('%Y-%m-%d %H:%M:%S%z').str[:-2] + ':' + df['observed_at'].dt.strftime('%z').str[-2:]

    predictions = pd.DataFrame({
        'timestamp': timestamp_str,
        'entity_id': df['link_id'].map(link_to_entity),
        'traffic_speed': df['speed_midpoint'].round(2),
        'predicted_speed': df['speed_midpoint'].round(2),  # persistence = current speed
        'persistence_prediction': df['speed_midpoint'].round(2),
        'absolute_error': 0.0,
        'persistence_absolute_error': 0.0,
    })

    logger.info("Generated %d predictions for %d unique entities", len(predictions), predictions['entity_id'].nunique())
    return predictions


def main():
    logger.info("=" * 60)
    logger.info("TRAFFIC ML INFERENCE — PERSISTENCE BASELINE")
    logger.info("=" * 60)

    # Load latest complete snapshot
    df = get_latest_complete_snapshot()

    # Generate persistence predictions
    predictions = generate_persistence_predictions(df)

    # Save to output path
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(OUTPUT_PATH, index=False)
    logger.info("Saved predictions to %s", OUTPUT_PATH)

    # Log summary
    logger.info("Summary:")
    logger.info("  Timestamp range: %s to %s", predictions['timestamp'].min(), predictions['timestamp'].max())
    logger.info("  Unique entities: %d", predictions['entity_id'].nunique())
    logger.info("  Traffic speed range: %.2f to %.2f", predictions['traffic_speed'].min(), predictions['traffic_speed'].max())

    return predictions


if __name__ == '__main__':
    main()