import sys
sys.path.insert(0, '.')
from backend.app.mobility.traffic.predictor import TrafficPredictor
from backend.app.mobility.traffic.data import TrafficObservationStore

store = TrafficObservationStore()
predictor = TrafficPredictor()
features_df, link_preds, diagnostics = predictor.predict_latest(store)
print(f'Number of link predictions: {len(link_preds)}')
print('Diagnostics:', diagnostics)
if link_preds:
    zones = set()
    for lp in link_preds:
        if lp.zone_id:
            print(f'  {lp.link_id}: zone={lp.zone_id}, current={lp.current_speed}, pred={lp.predicted_speed}')
    # Count by zone
    from collections import Counter
    zones = [lp.zone_id for l in link_preds if l.zone_id]
    print('Zone counts:', Counter(zones))