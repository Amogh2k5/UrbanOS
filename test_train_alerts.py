import os
os.environ.setdefault('LTA_ACCOUNT_KEY', 'dummy')
import sys
sys.path.insert(0, 'C:/projects/UrbanOS')
from backend.app.mobility.transit.data import collect_transit_alerts_once

result = collect_transit_alerts_once()
print('Timestamp:', result.timestamp)
print('Train alerts received:', result.train_alerts_received)
print('Train alerts stored:', result.train_alerts_stored)
print('Errors:', result.errors)