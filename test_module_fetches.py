import asyncio
import sys
sys.path.insert(0, r'C:\projects\UrbanOS')

# We need to simulate the app.state
# Let's test each fetch function individually

async def test_fetch(name, coro):
    try:
        result = await asyncio.wait_for(coro, timeout=10.0)
        print(f"{name}: OK - {type(result)}")
    except asyncio.TimeoutError:
        print(f"{name}: TIMEOUT")
    except Exception as e:
        print(f"{name}: ERROR - {e}")

async def test():
    # We need to import the functions and create a mock app_state
    from backend.app.overview.api import (
        _fetch_traffic_overview, _fetch_roads_overview, _fetch_transit_overview,
        _fetch_pm25_overview, _fetch_weather_overview, _fetch_flood_overview, _fetch_fire_overview
    )
    
    # Create a mock app_state
    class MockAppState:
        def __init__(self):
            from backend.app.environment.pm25.live_service import get_pm25_live_service
            from backend.app.environment.weather.api import WeatherApiClient, AirTemperatureApiClient
            from backend.app.environment.flood.api import FloodAlertsApiClient
            from backend.app.mobility.traffic.api import TrafficSpeedBandsV2ApiClient, TrafficIncidentsApiClient
            from backend.app.mobility.traffic.prediction_service import get_traffic_prediction_service
            
            self.traffic_prediction_service = get_traffic_prediction_service()
            self.pm25_live_service = get_pm25_live_service()
            self.weather_client = WeatherApiClient(offline=False, air_temperature_client=AirTemperatureApiClient(offline=True))
            self.flood_client = FloodAlertsApiClient(offline=True)
            self.traffic_incidents_client = TrafficIncidentsApiClient(offline=False)
    
    mock_state = MockAppState()
    
    from backend.app.overview.api import (
        _fetch_traffic_overview, _fetch_roads_overview, _fetch_transit_overview,
        _fetch_pm25_overview, _fetch_weather_overview, _fetch_flood_overview, _fetch_fire_overview
    )
    
    tasks = [
        ("traffic", _fetch_traffic_overview(mock_state)),
        ("roads", _fetch_roads_overview(mock_state)),
        ("transit", _fetch_transit_overview(mock_state)),
        ("pm25", _fetch_pm25_overview(mock_state)),
        ("weather", _fetch_weather_overview(mock_state)),
        ("flood", _fetch_flood_overview(mock_state)),
        ("fire", _fetch_fire_overview(mock_state)),
    ]
    
    for name, coro in [
        ("traffic", _fetch_traffic_overview(mock_state)),
        ("roads", _fetch_roads_overview(mock_state)),
        ("transit", _fetch_transit_overview(mock_state)),
        ("pm25", _fetch_pm25_overview(mock_state)),
        ("weather", _fetch_weather_overview(mock_state)),
        ("flood", _fetch_flood_overview(mock_state)),
        ("fire", _fetch_fire_overview(mock_state)),
    ]:
        try:
            result = await asyncio.wait_for(coro, timeout=15.0)
            print(f"{name}: OK - keys: {list(result.keys()) if isinstance(result, dict) else type(result)}")
        except asyncio.TimeoutError:
            print(f"{name}: TIMEOUT")
        except Exception as e:
            print(f"{name}: ERROR - {e}")

asyncio.run(test())