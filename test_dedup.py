import asyncio
from backend.app.overview.api import (
    _fetch_traffic_incidents, _fetch_fire_incidents, 
    _fetch_flood_alerts, _fetch_road_events, _fetch_transit_alerts
)

async def test():
    traffic = await _fetch_traffic_incidents()
    fire = await _fetch_fire_incidents()
    flood = await _fetch_flood_alerts()
    roads = await _fetch_road_events()
    transit = await _fetch_transit_alerts()
    
    print(f"Traffic: {len(traffic)}")
    print(f"Fire: {len(fire)}")
    print(f"Flood: {len(flood)}")
    print(f"Roads: {len(roads)}")
    print(f"Transit: {len(transit)}")
    
    all_alerts = []
    all_alerts.extend(traffic)
    all_alerts.extend(fire)
    all_alerts.extend(flood)
    all_alerts.extend(roads)
    print(f"Total before dedup: {len(all_alerts)}")
    
    # Test dedup
    seen = set()
    deduped = []
    for alert in all_alerts:
        alert_id = alert.get("id") or alert.get("alert_id") or alert.get("alert_id")
        if alert_id:
            key = (alert.get("domain", ""), str(alert_id))
        else:
            key = (
                alert.get("domain", ""),
                alert.get("title", "")[:50],
                alert.get("timestamp", "")[:20],
            )
        if key not in seen:
            seen.add(key)
            deduped.append(alert)
    
    print(f"After dedup: {len(deduped)}")
    deduped.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    top = deduped[:10]
    print(f"Top 10: {len(top)}")

asyncio.run(test())