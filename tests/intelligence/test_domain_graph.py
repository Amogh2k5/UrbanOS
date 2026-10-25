from backend.app.coordinator.domain_graph import BaseDomainGraph, DomainGraphRegistry


class EchoGraph:
    nodes = {"fetch": object(), "build_report": object()}

    def __init__(self):
        self.inputs = []

    def invoke(self, state, config=None):
        self.inputs.append(state)
        return {"report": {"domain": "weather", "available": False}, "errors": [], "warnings": []}


def test_domain_invocations_get_independent_input_mappings():
    graph = EchoGraph()
    adapter = BaseDomainGraph("weather", graph)

    first = adapter.invoke({"request_id": "one"})
    second = adapter.invoke({"request_id": "two"})

    assert first.domain == second.domain == "weather"
    assert graph.inputs == [{"request_id": "one"}, {"request_id": "two"}]
    assert graph.inputs[0] is not graph.inputs[1]


def test_domain_graph_failure_is_reported_as_unavailable():
    class FailingGraph:
        nodes = {}

        def invoke(self, state, config=None):
            raise TimeoutError("source timed out")

    result = BaseDomainGraph("roads", FailingGraph()).invoke({})

    assert result.status.available is False
    assert result.status.overall_status is None
    assert "source timed out" in result.errors[0]


def test_malformed_and_explicitly_unavailable_reports_stay_unavailable():
    class MalformedGraph:
        nodes = {"build": object()}
        def invoke(self, state, config=None):
            return {"report": ["not", "a", "mapping"]}

    malformed = BaseDomainGraph("roads", MalformedGraph()).invoke({})
    assert not malformed.status.available
    assert malformed.errors

    class UnavailableGraph:
        nodes = {"fetch": object()}
        def invoke(self, state, config=None):
            return {"report": {"available": False}}

    unavailable = BaseDomainGraph("transit", UnavailableGraph()).invoke({})
    assert not unavailable.status.available
    assert unavailable.status.overall_status is None
    assert unavailable.errors


def test_all_required_domain_graphs_are_registered_and_invokable():
    from backend.app.coordinator.city_agent import DomainGraphRegistry

    required = {
        "traffic", "transit", "roads", "weather", "pm25", "flood",
        "energy", "water", "waste", "land", "housing", "construction",
        "crime", "fire",
    }
    assert required <= set(DomainGraphRegistry.get_all_domains())
    for domain in required:
        registered = DomainGraphRegistry.get(domain)
        assert registered is not None, domain
        assert callable(getattr(registered.graph, "invoke", None)), domain
        assert registered.get_capabilities()["graph_nodes"], domain


def test_new_domain_graphs_use_real_provider_boundaries(monkeypatch):
    from types import SimpleNamespace
    from backend.app.mobility.roads import aggregator
    from backend.app.mobility.roads.agent import get_roads_agent
    from backend.app.mobility.transit import data as transit_data
    from backend.app.mobility.transit.agent import get_transit_agent
    from backend.app.environment.weather import api as weather_api
    from backend.app.environment.weather.agent import get_weather_agent
    from backend.app.environment.pm25 import live_service
    from backend.app.environment.pm25.agent import get_pm25_agent

    road_payload = {"road_works": {"active": 4}, "road_openings": {"active": 1},
                    "taxi_stands": {"active": 0}, "source_status": "available",
                    "fetched_at": "2026-10-24T10:00:00+08:00"}
    monkeypatch.setattr(aggregator, "get_roads_snapshot", lambda: road_payload)
    assert get_roads_agent().invoke({})["report"]["road_works"]["active"] == 4

    alert = SimpleNamespace(category="rail", line="NSL", direction=None,
                            station="City Hall", message="Service delay", status="active")
    class Store:
        def get_stats(self):
            return {"bus_services": 20, "bus_routes": 30, "bus_stops": 40}
        def get_latest_train_alerts(self, limit):
            return [alert]
    monkeypatch.setattr(transit_data, "TransitDataStore", Store)
    assert get_transit_agent().invoke({})["report"]["active_train_alerts"] == 1

    snapshot = SimpleNamespace(
        is_live=True,
        to_dict=lambda: {"snapshot_at": "2026-10-24T10:00:00+08:00",
                         "general": {"forecast_code": "CL"}, "source": "NEA"},
    )
    class WeatherClient:
        def __init__(self, **kwargs):
            assert kwargs["allow_fallback_fixture"] is False
        def fetch(self):
            return snapshot
    monkeypatch.setattr(weather_api, "WeatherApiClient", WeatherClient)
    assert get_weather_agent().invoke({})["report"]["source_status"] == "live"

    pm_snapshot = SimpleNamespace(
        is_live=False,
        snapshot_at="2026-10-24T09:00:00+08:00",
        raw_issue_timestamp="2026-10-24T08:00:00+08:00",
        to_dict=lambda: {"regions": {"central": {"value": 8.0}}},
    )
    class PmService:
        def snapshot(self):
            return pm_snapshot
    monkeypatch.setattr(live_service, "get_pm25_live_service", lambda: PmService())
    assert get_pm25_agent().invoke({})["report"]["regions"]["central"]["value"] == 8.0


def test_registry_clear_removes_graphs_and_capabilities():
    existing = DomainGraphRegistry.get_all()
    graph = BaseDomainGraph("test-domain", EchoGraph())
    DomainGraphRegistry.register(graph)
    assert DomainGraphRegistry.get("test-domain") is graph
    assert "test-domain" in DomainGraphRegistry.get_all_capabilities()

    DomainGraphRegistry.clear()

    assert DomainGraphRegistry.get("test-domain") is None
    assert "test-domain" not in DomainGraphRegistry.get_all_capabilities()
    for registered in existing:
        DomainGraphRegistry.register(registered)
