#!/usr/bin/env python
"""Rebuild CSV cache using the store's export method."""

import logging
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app.mobility.traffic.data import TrafficObservationStore

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

if __name__ == "__main__":
    store = TrafficObservationStore()
    csv_path = Path("data/traffic/traffic_observations.csv")
    print(f"Exporting latest 7 observations per link to {csv_path}...")
    store.export_latest_seven_per_link(csv_path)
    print("Done!")