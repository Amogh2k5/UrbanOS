"""LTA DataMall Live API adapter for Train Service Alerts.

Endpoint: https://datamall2.mytransport.sg/ltaodataservice/TrainServiceAlerts
Auth: AccountKey header
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger(__name__)

SG_OFFSET = timezone(timedelta(hours=8))
_DEFAULT_BASE = "https://datamall2.mytransport.sg/ltaodataservice"
_ENDPOINT = "/TrainServiceAlerts"
_TIMEOUT = 15.0


@dataclass
class TrainServiceAlert:
    """Train service alert from LTA."""
    line: str
    direction: Optional[str]
    station: Optional[str]
    message: str
    status: Optional[str]
    source: str
    fetched_at: str


@dataclass
class TrainServiceAlertsSnapshot:
    snapshot_at: str
    source: str
    provider: str
    endpoint: str
    alerts: List[TrainServiceAlert]
    is_live: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_at": self.snapshot_at,
            "source": self.source,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "is_live": self.is_live,
            "count": len(self.alerts),
            "alerts": [
                {
                    "line": a.line,
                    "direction": a.direction,
                    "station": a.station,
                    "message": a.message,
                    "status": a.status,
                }
                for a in self.alerts
            ],
        }


class TrainServiceAlertsApiClient:
    """Adapter for LTA TrainServiceAlerts endpoint."""

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE,
        account_key: Optional[str] = None,
        offline: bool = False,
        allow_fallback_fixture: bool = True,
        timeout: float = _TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.account_key = account_key or os.getenv("LTA_ACCOUNT_KEY")
        self.offline = offline
        self.allow_fallback_fixture = allow_fallback_fixture
        self.timeout = timeout

    def fetch(self) -> TrainServiceAlertsSnapshot:
        """Fetch latest train service alerts."""
        payload, is_live = self._get_payload()
        return self._normalize(payload, is_live=is_live)

    def _get_payload(self):
        if self.offline:
            log.info("Train Service Alerts adapter offline=True; using fallback fixture.")
            return {"value": []}, False

        if not self.account_key:
            log.warning("LTA_ACCOUNT_KEY not set; using fallback fixture.")
            if self.allow_fallback_fixture:
                return {"value": []}, False
            raise ValueError("LTA_ACCOUNT_KEY not configured")

        headers = {"AccountKey": self.account_key, "accept": "application/json"}
        url = f"{self.base_url}{_ENDPOINT}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                return resp.json(), True
        except httpx.TimeoutException as e:
            log.warning("Train Service Alerts live fetch timeout: %s", e)
        except httpx.HTTPStatusError as e:
            log.warning("Train Service Alerts HTTP error: %s", e)
        except httpx.RequestError as e:
            log.warning("Train Service Alerts connection error: %s", e)
        except ValueError as e:
            log.warning("Train Service Alerts malformed response: %s", e)

        if self.allow_fallback_fixture:
            log.warning("Train Service Alerts falling back to deterministic fixture.")
            return {"value": []}, False
        raise

    def _normalize(self, payload: dict, is_live: bool) -> TrainServiceAlertsSnapshot:
        value = payload.get("value") or payload.get("Value") or []
        alerts: List[TrainServiceAlert] = []
        fetched_at = self._now_iso()

        # Handle two possible payload structures:
        # 1. value is a list of alert objects (legacy expectation)
        # 2. value is a dict with keys: Status, AffectedSegments, Message (current LTA format)
        if isinstance(value, list):
            items = value
        elif isinstance(value, dict):
            # Current LTA format: value = {Status, AffectedSegments, Message: [...]}
            messages = value.get("Message") or value.get("message") or []
            if isinstance(messages, list):
                items = messages
            else:
                log.warning("Unexpected Train Service Alerts payload: 'Message' not a list")
                items = []
            # Optionally capture top-level status
            top_status = value.get("Status") or value.get("status")
        else:
            log.warning("Unexpected payload structure for Train Service Alerts")
            items = []

        for item in items:
            def _get(*keys):
                for k in keys:
                    v = item.get(k)
                    if v is not None:
                        return v
                return None

            # In current format, each message has Content and CreatedDate
            content = _get("Content", "content", "Message", "message") or ""
            created = _get("CreatedDate", "created_date", "Created", "created")

            alerts.append(TrainServiceAlert(
                line=_get("Line", "line") or "UNKNOWN",
                direction=_get("Direction", "direction"),
                station=_get("Station", "station"),
                message=content,
                status=_get("Status", "status") or top_status if 'top_status' in locals() else _get("Status", "status"),
                source=("live_api:LTA_train_alerts" if is_live else "offline_fixture:LTA_train_alerts"),
                fetched_at=fetched_at,
            ))

        return TrainServiceAlertsSnapshot(
            snapshot_at=self._now_iso(),
            source=("live_api:LTA_train_alerts" if is_live else "offline_fixture:LTA_train_alerts"),
            provider="LTA DataMall",
            endpoint=f"{_DEFAULT_BASE}{_ENDPOINT}",
            alerts=alerts,
            is_live=is_live,
        )

    def _now_iso(self) -> str:
        return datetime.now(SG_OFFSET).isoformat()