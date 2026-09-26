import sys
sys.path.insert(0, 'C:/projects/UrbanOS')
from backend.app.mobility.transit.data import TransitDataStore, StoredTrainAlert
from datetime import datetime, timezone, timedelta

SG_OFFSET = timezone(timedelta(hours=8))
store = TransitDataStore()
alert = StoredTrainAlert(
    id=0,
    line="NSL",
    direction="1",
    station="Bishan",
    message="Test alert",
    status="active",
    source="live_api:LTA_train_alerts",
    fetched_at=datetime.now(SG_OFFSET).isoformat(),
    created_at=datetime.now(SG_OFFSET).isoformat(),
    category="metro"
)
inserted = store.insert_train_alerts([alert])
print('Inserted:', inserted)
alerts = store.get_latest_train_alerts(limit=5)
for a in alerts:
    print(a)