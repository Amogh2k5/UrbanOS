"""Official Singapore crime data adapters.

Primary machine-readable source:
data.gov.sg datastore API, using datasets published by SINGSTAT from
Singapore Police Force data.

Static scam detail source:
Singapore Police Force Annual Scam and Cybercrime Brief 2025 infographic.
Those values are kept as source-attributed release data because the official
SPF publication is a PDF/infographic rather than a machine-readable dataset.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger(__name__)

DATASTORE_URL = "https://data.gov.sg/api/action/datastore_search"

DATASET_CRIME_CASES = "d_ca0b908cf06a267ca06acbd5feb4465c"
DATASET_MAJOR_OFFENCES = "d_02d07531b84cd0cf2cf901fc1bf5d395"
DATASET_ARRESTS = "d_08433c469bbe2768daf9e2b86217991d"
DATASET_NPC = "d_5767147db6e5b4c4cfa874db132fef39"

SPF_SCAM_BRIEF_2025 = (
    "https://www.police.gov.sg/-/media/SPF/Media-Room/Statistics/"
    "Annual-Scams-and-Cybercrime-Brief-2025-Infographic/"
    "Infographic-for-ASCB-2025.pdf"
)

# Values below are transcribed from the official SPF 2025 infographic.
# They are not generated or predicted by UrbanOS.
SCAM_TYPES_2025 = [
    {"name": "E-commerce scams", "cases": 6703, "loss_sgd_million": 16.7, "average_loss_sgd": 2503},
    {"name": "Phishing scams", "cases": 6264, "loss_sgd_million": 39.9, "average_loss_sgd": 6384},
    {"name": "Job scams", "cases": 5575, "loss_sgd_million": 123.5, "average_loss_sgd": 22163},
    {"name": "Investment scams", "cases": 5462, "loss_sgd_million": 336.2, "average_loss_sgd": 61559},
    {"name": "Government officials impersonation scams", "cases": 3363, "loss_sgd_million": 242.9, "average_loss_sgd": 72229},
    {"name": "Fake friend call scams", "cases": 1551, "loss_sgd_million": 4.7, "average_loss_sgd": 3056},
    {"name": "Sexual services scams", "cases": 1150, "loss_sgd_million": 3.9, "average_loss_sgd": 3464},
    {"name": "Insurance services scams", "cases": 1003, "loss_sgd_million": 25.2, "average_loss_sgd": 25125},
    {"name": "Loan scams", "cases": 935, "loss_sgd_million": 7.0, "average_loss_sgd": 7515},
    {"name": "Internet love scams", "cases": 917, "loss_sgd_million": 24.9, "average_loss_sgd": 27202},
]


@dataclass
class CrimeDataSnapshot:
    generated_at: str
    source_status: str = "unavailable"
    datasets: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class DataGovCrimeClient:
    def __init__(self, timeout_s: float = 20.0) -> None:
        self.timeout_s = timeout_s
        self.api_key = os.getenv("DATA_GOV_SG_API_KEY")

    def fetch_dataset(self, dataset_id: str) -> List[Dict[str, Any]]:
        params = {"resource_id": dataset_id, "limit": 5000}
        headers = {}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key

        try:
            with httpx.Client(timeout=self.timeout_s, follow_redirects=True) as client:
                response = client.get(DATASTORE_URL, params=params, headers=headers)
            if response.status_code == 429:
                raise RuntimeError("data.gov.sg rate limit exceeded (HTTP 429)")
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(f"data.gov.sg dataset {dataset_id} request failed: {exc}") from exc

        if payload.get("success") is not True:
            raise RuntimeError(
                f"data.gov.sg dataset {dataset_id} returned an unsuccessful response"
            )
        result = payload.get("result") or {}
        records = result.get("records")
        if not isinstance(records, list):
            raise RuntimeError(f"data.gov.sg dataset {dataset_id} returned no records array")
        return records

    def fetch_all(self) -> CrimeDataSnapshot:
        from datetime import datetime, timezone

        snapshot = CrimeDataSnapshot(
            generated_at=datetime.now(timezone.utc).isoformat()
        )
        for key, dataset_id in {
            "crime_cases": DATASET_CRIME_CASES,
            "major_offences": DATASET_MAJOR_OFFENCES,
            "arrests": DATASET_ARRESTS,
            "npc": DATASET_NPC,
        }.items():
            try:
                snapshot.datasets[key] = self.fetch_dataset(dataset_id)
            except Exception as exc:
                snapshot.errors.append(str(exc))
                log.warning("Crime dataset %s unavailable: %s", key, exc)

        snapshot.source_status = (
            "available" if len(snapshot.datasets) == 4
            else ("partial" if snapshot.datasets else "unavailable")
        )
        if len(snapshot.datasets) < 4:
            snapshot.warnings.append(
                "One or more official data.gov.sg crime datasets could not be retrieved; "
                "missing datasets are not represented as zero."
            )
        return snapshot
