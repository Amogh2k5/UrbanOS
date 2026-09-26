import re

# Read the file
with open(r'C:\projects\UrbanOS\backend\app\mobility\traffic\api.py', 'r') as f:
    content = f.read()

# Define the old function pattern
old_function = r'''def _normalize\(self, payload: dict, is_live: bool\) -> "TrainServiceAlertsSnapshot":
        value = payload.get\("value"\) or payload.get\("Value"\) or \[\]
        alerts: List\["TrainServiceAlert"\] = \[\]
        fetched_at = self\._now_iso\(\)

        # Handle two possible payload structures:
        # 1. value is a list of alert objects \(legacy expectation\)
        # 2. value is a dict with keys: Status, AffectedSegments, Message \(current LTA format\)
        if isinstance\(value, list\):
            items = value
        elif isinstance\(value, dict\):
            # Current LTA format: value = {Status, AffectedSegments, Message: \[...\]}
            messages = value\.get\("Message"\) or value\.get\("message"\) or \[\]
            if isinstance\(messages, list\):
                items = messages
            else:
                log\.warning\("Unexpected Train Service Alerts payload: 'Message' not a list"\)
                items = \[\]
            # Optionally capture top-level status
            top_status = value\.get\("Status"\) or value\.get\("status"\)
        else:
            log\.warning\("Unexpected payload structure for Train Service Alerts"\)
            items = \[\]

        alerts: List\["TrainServiceAlert"\] = \[\]
        fetched_at = self\._now_iso\(\)

        for item in items:
            def _get\(\*keys\):
                for k in keys:
                    v = item\.get\(k\)
                    if v is not None:
                        return v
                return None

            # In current format, each message has Content and CreatedDate
            content = _get\("Content", "content", "Message", "message"\) or ""
            created = _get\("CreatedDate", "created_date", "Created", "created"\)

            alerts\.append\(TrainServiceAlert\(
                line=_get\(item, "Line", "line"\) or "UNKNOWN",
                direction=_get\(item, "Direction", "direction"\),
                station=_get\(item, "Station", "station"\),
                message=content,
                status=_get\(item, "Status", "status"\) or top_status if 'top_status' in locals\(\) else _get\(item, "Status", "status"\),
                source=\(\("live_api:LTA_train_alerts" if is_live else "offline_fixture:LTA_train_alerts"\),
                fetched_at=fetched_at,
            \)\)

        return TrainServiceAlertsSnapshot\(
            snapshot_at=self\._now_iso\(\),
            source=\(\("live_api:LTA_train_alerts" if is_live else "offline_fixture:LTA_train_alerts"\),
            provider="LTA DataMall",
            endpoint=f"\{_DEFAULT_BASE\}\{_ENDPOINT\}",
            alerts=alerts,
            is_live=is_live,
        \)

    def _now_iso\(self\) -> str:
        return datetime.now\(SG_OFFSET\)\.isoformat\(\)'''

new_function = '''def _normalize(self, payload: dict, is_live: bool) -> "TrainServiceAlertsSnapshot":
    value = payload.get("value") or payload.get("Value") or []
    alerts: List["TrainServiceAlert"] = []
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

    alerts: List["TrainServiceAlert"] = []
    fetched_at = self._now_iso()

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

        # Categorize alert based on content
        category = self._categorize_alert(content)

        alerts.append(TrainServiceAlert(
            line=_get(item, "Line", "line") or "UNKNOWN",
            direction=_get(item, "Direction", "direction"),
            station=_get(item, "Station", "station"),
            message=content,
            status=_get(item, "Status", "status") or top_status if 'top_status' in locals() else _get(item, "Status", "status"),
            source=("live_api:LTA_train_alerts" if is_live else "offline_fixture:LTA_train_alerts"),
            fetched_at=fetched_at,
            category=self._categorize_alert(content),
        ))

    return TrainServiceAlertsSnapshot(
        snapshot_at=self._now_iso(),
        source=("live_api:LTA_train_alerts" if is_live else "offline_fixture:LTA_train_alerts"),
        provider="LTA DataMall",
        endpoint=f"{_DEFAULT_BASE}{_ENDPOINT}",
        alerts=alerts,
        is_live=is_live,
    )

def _categorize_alert(self, text: str) -> str:
    """Categorize alert based on content text."""
    from backend.app.mobility.traffic.agent import classify_alert, normalise
    # Create a minimal alert-like object for classification
    class MockAlert:
        def __init__(self, line, message, station):
            self.line = line
            self.message = message
            self.station = station
    mock_alert = MockAlert("", text, "")
    category = classify_alert(mock_alert)
    return category

def _now_iso(self) -> str:
    return datetime.now(SG_OFFSET).isoformat()'''

# Read the file
with open(r'C:\projects\UrbanOS\backend\app\mobility\traffic\api.py', 'r') as f:
    content = f.read()

# Replace the function
content = content.replace(old_function, new_function)

# Write the file
with open(r'C:\projects\UrbanOS\backend\app\mobility\traffic\api.py', 'w') as f:
    f.write(content)

print("Done")