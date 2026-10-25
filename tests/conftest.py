"""Session-wide guard against launching real coordinator runs.

``backend.app.main`` warms the City Coordinator cache when the app is built, and
a run costs roughly 74 seconds of live API calls across every domain agent. The
test session must never trigger that, so this module disables background runs.

Two things are needed because the warm-up fires at import time:

1. The environment variable below is read when
   ``backend.app.coordinator.access`` is first imported. Setting it here - before
   pytest collects anything - is the only way to stop a run that starts during
   collection, since ``backend.app.main`` is imported at module scope by some
   test files.
2. The autouse fixture re-asserts the flag before every test, because
   ``tests/intelligence/test_city_coldstart.py`` restores it to enabled in its
   own fixture teardown.

Tests that genuinely need a background run enable it themselves - see
``test_cold_cache_starts_exactly_one_background_run``, which also patches
``_run_coordinator`` so no real run happens.
"""

import os
import sys

os.environ["URBANOS_COORDINATOR_BACKGROUND"] = "0"
os.environ["URBANOS_BACKGROUND_SERVICES"] = "0"

import pytest  # noqa: E402

# A few legacy tests import ``coordinator.city_agent`` after placing
# ``backend/app`` on PYTHONPATH, while production and the offline fixtures use
# ``backend.app.coordinator.city_agent``. Make both spellings resolve to one
# module so provider stubs actually intercept the registered graph callbacks.
from backend.app.coordinator import city_agent as _canonical_city_agent  # noqa: E402
sys.modules["coordinator.city_agent"] = _canonical_city_agent


@pytest.fixture(autouse=True)
def _coordinator_background_runs_disabled():
    from backend.app.coordinator import access

    access.set_background_runs_enabled(False)
    yield


@pytest.fixture(autouse=True)
def _offline_new_coordinator_domains():
    """Keep added domain-graph providers deterministic at the graph boundary."""
    from unittest.mock import patch
    from contextlib import ExitStack
    from backend.app.coordinator import city_agent

    with ExitStack() as stack:
        for name in (
            "run_transit_agent", "run_roads_agent", "run_weather_agent",
            "run_pm25_agent", "run_construction_agent",
        ):
            stack.enter_context(patch.object(
                city_agent, name,
                return_value={"error": f"{name.removeprefix('run_').removesuffix('_agent')} test provider unavailable"},
            ))
        yield


@pytest.fixture(autouse=True)
def _offline_remaining_coordinator_providers():
    """Prevent coordinator endpoint tests from reaching unrelated live APIs."""
    from unittest.mock import patch
    from contextlib import ExitStack
    from backend.app.coordinator import city_agent

    names = (
        "run_traffic_agent", "run_flood_agent_v3",
        "run_water_agent", "run_land_agent", "run_fire_agent", "run_crime_agent",
    )
    with ExitStack() as stack:
        for name in names:
            stack.enter_context(patch.object(
                city_agent, name,
                return_value={"error": f"{name.removeprefix('run_').removesuffix('_agent')} test provider unavailable"},
            ))
        yield


@pytest.fixture(autouse=True)
def _no_live_air_quality_in_unit_tests():
    """Unit tests must not depend on current NEA air quality.

    The coordinator's environment domain reads *observed* PM2.5 from the live
    collector store so its cross-domain rules can see real conditions. Without
    this guard a unit test asserting a MODERATE environment would pass or fail
    depending on whether the city's air happened to be unhealthy that morning.

    Defaults to "no observation", which is the conservative path: the domain
    then reports only its forecast. Tests that exercise observed air quality
    patch ``city_agent._observed_air_quality`` explicitly.
    """
    from backend.app.coordinator import city_agent

    original = city_agent._observed_air_quality
    city_agent._observed_air_quality = lambda: {
        "available": False, "reason": "patched out for unit tests",
    }
    yield
    city_agent._observed_air_quality = original


@pytest.fixture(autouse=True)
def _offline_waste_agent():
    """Patch the waste agent so coordinator tests never hit data.gov.sg.

    The City Coordinator imports and calls ``run_waste_agent``. Without this
    patch, the first coordinator test that triggers the collect node would fire
    live HTTP to data.gov.sg (six datasets, with rate limits) and also depend on
    the module's on-disk cache layout. This fixture provides a deterministic,
    offline stub that returns a ``STATISTICS_AVAILABLE`` report with a handful of
    KPIs so cross-domain rules that reference waste can be exercised without the
    network.
    """
    from unittest.mock import patch
    from backend.app.infrastructure.waste.models import (
        WasteReport, Indicator, SourceInfo, WasteAlert, WasteInsight,
        GenerationSection, CategorySection, CategoryRow, CategorySeries,
        FoodSection, ServicesSection, ServiceClass,
        InfrastructureSection, FacilityKindSummary,
        ForecastSection, DataQualitySection, QualityCheck,
    )
    from datetime import datetime, timezone, timedelta

    SG = timezone(timedelta(hours=8))

    def _stub() -> WasteReport:
        now = datetime.now(SG)
        return WasteReport(
            generated_at=now,
            status="STATISTICS_AVAILABLE",
            overall_risk="UNKNOWN",
            summary="Singapore generated 7.00 million tonnes of waste in 2023, of which 3.50 million tonnes (50%) was recycled and 3.50 million tonnes was disposed of.",
            kpis=[
                Indicator(key="total_generated", label="Total Waste Generated", period="2023", value=7_000_000, change_abs=None, change_pct=-0.5, previous_period="2022", unit="tonnes", data_kind="latest_available"),
                Indicator(key="total_recycled", label="Total Recycled", period="2023", value=3_500_000, change_abs=None, change_pct=0.2, previous_period="2022", unit="tonnes", data_kind="latest_available"),
                Indicator(key="total_disposed", label="Total Disposed", period="2023", value=3_500_000, change_abs=None, change_pct=-1.0, previous_period="2022", unit="tonnes", data_kind="latest_available"),
                Indicator(key="overall_recycling_rate", label="Overall Recycling Rate", period="2023", value=50.0, change_abs=0.1, change_pct=None, previous_period="2022", unit="%", data_kind="latest_available"),
                Indicator(key="recycling_rate_excl_cd", label="Recycling Rate (excl. C&D)", period="2023", value=55.0, change_abs=0.2, change_pct=None, previous_period="2022", unit="%", data_kind="latest_available"),
            ],
            generation=GenerationSection(
                latest_year=2023,
                total_generated_tonnes=7_000_000,
                generated_change_since_peak_pct=-5.0,
                peak_generated_year=2017,
                peak_generated_tonnes=8_000_000,
                peak_recycling_rate_pct=61.0,
                peak_recycling_rate_year=2018,
                limitations=[],
            ),
            categories=CategorySection(
                latest_year=2023,
                rows=[],
                top_disposed=["food", "paper", "plastic"],
            ),
            food=FoodSection(
                latest_year=2023,
                generated=Indicator(key="food_generated", label="Food Waste Generated", period="2023", value=800_000, change_abs=None, change_pct=None, previous_period="2022", unit="tonnes", data_kind="latest_available"),
                recycling_rate=Indicator(key="food_recycling_rate", label="Food Waste Recycling Rate", period="2023", value=18.0, change_abs=None, change_pct=None, previous_period="2022", unit="%", data_kind="latest_available"),
                share_of_total_disposed_pct=22.0,
            ),
            services=ServicesSection(
                licensee_count=15,
                classes=[
                    ServiceClass(key="A", label="General Waste", description="Test fixture class", licensees=12),
                    ServiceClass(key="B", label="Specialised", description="Test fixture class", licensees=3),
                ],
            ),
            infrastructure=InfrastructureSection(
                map_available=True,
                kinds=[
                    FacilityKindSummary(label="Recycling Bins", count=10000, status="ok"),
                    FacilityKindSummary(label="E-Waste Points", count=450, status="ok"),
                    FacilityKindSummary(label="Disposal Sites", count=7, status="ok"),
                ],
                limitations=[],
            ),
            unavailable_metrics=[],
            forecast=ForecastSection(available=False, reason="Annual waste statistics are too sparse (26 observations) for reliable ML forecasting; minimum 48 required."),
            data_quality=DataQualitySection(checks=[]),
            alerts=[],
            insights=[],
            sources=[
                SourceInfo(key="waste_statistics", organization="NEA", name="Waste Statistics", identifier="d_daf568968ab40dc81e7b08887a83c8fa", layer_name="", url="", purpose="", update_frequency="annual", coverage="2000-2025", authentication="api_key", data_kind="latest_available", crs="", component="", status="ok", last_fetched_at=now.isoformat(), latest_data_period="2023", error=None),
            ],
            data_timestamps={},
            confidence="high",
            limitations=[
                "All waste data is official annual statistics or static location/licence listings; nothing in this module is live.",
                "Facility, collection-point and disposal-site layers are reference data with per-record dates from 2017-2022; they may not reflect today's network.",
                "Domestic vs non-domestic waste, per-capita figures, landfill capacity, truck tracking and bin fill levels are not available as official open data and are not shown.",
                "Waste does not assess water, energy, flood, fire, roads or traffic; cross-domain reasoning is done by the City Coordinator.",
            ],
            warnings=[],
            errors=[],
            is_ml_prediction=False,
        )

    with patch("backend.app.coordinator.city_agent.run_waste_agent", side_effect=_stub):
        yield


@pytest.fixture(autouse=True)
def _offline_housing_agent():
    """Patch the housing agent so coordinator tests never hit data.gov.sg.

    The City Coordinator imports and calls ``run_housing_agent``. Without this
    patch, the first coordinator test that triggers the collect node would fire
    live HTTP to data.gov.sg (three datasets). This fixture provides a
    deterministic, offline stub that returns an ``AVAILABLE`` report.
    """
    from unittest.mock import patch
    from backend.app.planning.housing.models import HousingReport, HousingSource, HousingInsight
    from datetime import datetime, timezone, timedelta

    SG = timezone(timedelta(hours=8))

    def _stub() -> HousingReport:
        now = datetime.now(SG)
        return HousingReport(
            generated_at=now,
            status="AVAILABLE",
            kpis={
                "latest_median_resale_period": "2025-Q4",
                "town_flat_type_median_price_rows": 120,
                "latest_resale_applications_period": "2025-Q4",
                "resale_applications": 4500,
                "hdb_property_records": 10500,
                "hdb_total_dwelling_units_in_records": 1_050_000,
            },
            resale_trend=[
                {"period": "2025-Q3", "mean_of_town_flat_medians": 580_000, "observations": 110},
                {"period": "2025-Q4", "mean_of_town_flat_medians": 595_000, "observations": 120},
            ],
            town_prices=[{"town": "ANG MO KIO", "prices": {"4-room": 550_000, "5-room": 700_000}}],
            resale_by_flat_type=[{"flat_type": "4-room", "median_price_across_towns": 550_000, "towns_with_data": 25}],
            housing_stock={
                "available": True,
                "source_period": "through Dec 2025 (source catalogue)",
                "hdb_property_records": 10500,
                "total_dwelling_units_in_records": 1_050_000,
                "town_unit_counts": [{"town": "ANG MO KIO", "units": 80000}],
                "completion_year_building_counts": [{"year": 2010, "buildings": 120}],
                "sample_blocks": [{"block": "101", "street": "TEST ST", "town": "ANG MO KIO", "year_completed": 2010, "total_dwelling_units": 120}],
                "note": "Sum reflects the current returned HDB property records; not a separately published national stock KPI.",
            },
            rental_market={"available": False, "hdb_median_rent": None, "private_rent_index": None,
                           "note": "No current median-rent dataset was configured as an accessible machine-readable source in this build."},
            private_residential={"available": False, "price_index": None, "rental_index": None, "vacancy_rate": None,
                                 "note": "URA publishes private residential market releases, but a reliable unauthenticated structured API/feed was not confirmed here.",
                                 "official_release_url": "https://www.ura.gov.sg/news/"},
            supply_pipeline={"available": False, "items": [], "note": "No verified structured pipeline feed is wired into this module."},
            household_context={"available": False, "resident_households": None, "average_household_size": None,
                               "owner_occupied_share": None, "dwelling_type_share": None,
                               "note": "SingStat household indicators are not represented as live data; a verified machine-readable table is needed."},
            map_data={"available": False, "type": "FeatureCollection", "features": [],
                      "note": "HDB property dataset has block/street fields but no verified coordinates; map markers are intentionally omitted."},
            sources=[
                HousingSource(key="median_resale", name="Median Resale Prices", agency="HDB", url="", status="available",
                              retrieved_at=now.isoformat(), error=None, record_count=13000, fields=["quarter", "town", "flat_type", "price"]),
                HousingSource(key="resale_applications", name="Resale Applications", agency="HDB", url="", status="available",
                              retrieved_at=now.isoformat(), error=None, record_count=5000, fields=["quarter", "flat_type", "no_of_resale_applications"]),
                HousingSource(key="hdb_property", name="HDB Property Information", agency="HDB", url="", status="available",
                              retrieved_at=now.isoformat(), error=None, record_count=10500, fields=["blk_no", "street", "year_completed", "total_dwelling_units", "bldg_contract_town"]),
            ],
            errors=[],
            warnings=[],
            limitations=[
                "This is a periodic/historical housing intelligence view, not a live property market feed.",
                "HDB median resale price is a town/flat-type statistic, not an individual flat valuation.",
                "HDB property inventory provides block/street reference fields but no verified latitude/longitude in this dataset; no map markers are fabricated.",
                "Detailed current URA private-market datasets and SingStat household tables were not confirmed as accessible machine-readable feeds in this implementation; their metrics remain unavailable rather than inferred.",
            ],
            insights=[
                HousingInsight(question="How are HDB resale prices changing?", answer="Latest available town/flat-type median period is 2025-Q4.", data_kind="latest_available"),
                HousingInsight(question="Which towns have the highest median resale prices?", answer="Compare towns using the latest-period town/flat-type table; prices vary by flat type, so a single town ranking would be misleading.", data_kind="latest_available"),
                HousingInsight(question="How is private housing supply changing?", answer="Unavailable in this module until a verified structured URA supply feed is connected.", data_kind="unavailable"),
                HousingInsight(question="What is happening with residential vacancy?", answer="Unavailable in this module until verified structured URA vacancy data is connected.", data_kind="unavailable"),
                HousingInsight(question="How is housing stock distributed?", answer="Returned HDB property inventory includes 10500 records.", data_kind="latest_available"),
            ],
            confidence="high",
            data_timestamps={
                "median_resale": {"last_fetched_at": now.isoformat(), "latest_data_period": "2025-Q4", "status": "available", "data_kind": "latest_available"},
                "resale_applications": {"last_fetched_at": now.isoformat(), "latest_data_period": "2025-Q4", "status": "available", "data_kind": "latest_available"},
                "hdb_property": {"last_fetched_at": now.isoformat(), "latest_data_period": "2025", "status": "available", "data_kind": "latest_available"},
            },
            is_ml_prediction=False,
        )

    with patch("backend.app.coordinator.city_agent.run_housing_agent", side_effect=_stub):
        yield


@pytest.fixture(autouse=True)
def _offline_energy_agent():
    """Patch the energy agent so coordinator tests never hit data.gov.sg.

    The City Coordinator imports and calls ``run_energy_agent``. Without this
    patch, the first coordinator test that triggers the collect node would fire
    live HTTP to data.gov.sg (four datasets). This fixture provides a
    deterministic, offline stub that returns an ``OK`` report.
    """
    from unittest.mock import patch
    from backend.app.infrastructure.energy.models import EnergyReport, EnergySource
    from datetime import datetime, timezone, timedelta

    SG = timezone(timedelta(hours=8))

    def _stub() -> EnergyReport:
        now = datetime.now(SG)
        return EnergyReport(
            generated_at=now,
            status="OK",
            summary="4 of 4 official energy datasets are available. Demand, consumption and solar indicators are historical statistics, not live grid telemetry.",
            key_metrics={
                "latest_peak_demand_mw": 7200.0,
                "latest_peak_demand_period": "2021-07",
                "max_peak_demand_mw": 7500.0,
                "average_peak_demand_mw": 6800.0,
                "latest_solar_capacity_mwp": 500.0,
                "latest_solar_capacity_year": "2021",
                "demand_records": 198,
                "consumption_records": 220,
            },
            peak_demand=[
                {"period": "2021-06", "value_mw": 7100.0},
                {"period": "2021-07", "value_mw": 7200.0},
            ],
            consumption=[
                {"year": "2019", "sector": "Industrial", "energy_product": "Electricity", "consumption_ktoe": 1500.0},
                {"year": "2019", "sector": "Transport", "energy_product": "Diesel", "consumption_ktoe": 800.0},
            ],
            solar_by_region=[
                {"year": "2021", "region": "Central", "residential_status": "Residential", "installations": 150, "capacity_kwac": 500.0, "share_percent": 15.0},
            ],
            solar_capacity=[
                {"year": "2021", "residential_status": "Residential", "user_type": "HDB", "capacity_mwp": 200.0, "capacity_mwac": 180.0},
            ],
            sources=[
                EnergySource(name="Peak System Demand", dataset_id="d_926d3e30", url="", frequency="monthly", coverage="2005-Jul 2021", unit="MW", status="ok", latest_period="2021-07", records=198, error=None),
                EnergySource(name="Total Final Energy Consumption", dataset_id="d_500440fb", url="", frequency="annual", coverage="2009-2019", unit="ktoe", status="ok", latest_period="2019", records=220, error=None),
                EnergySource(name="Solar PV by URA Planning Region", dataset_id="d_cd4f91f7", url="", frequency="annual", coverage="Jan 2008-Mar 2021", unit="kWac", status="ok", latest_period="2021", records=150, error=None),
                EnergySource(name="Installed Capacity of Grid-Connected Solar PV", dataset_id="d_51adcf3c", url="", frequency="annual", coverage="Jan 2008-Mar 2021", unit="MWp", status="ok", latest_period="2021", records=160, error=None),
            ],
            limitations=[
                "The verified public peak-system-demand dataset ends in July 2021 and is monthly; it cannot support a truthful current-demand KPI or half-hourly forecast.",
                "The verified solar datasets end in March 2021; figures must be labelled historical and must not be presented as current installed capacity.",
                "The consumption dataset covers 2009–2019 and reports total final energy consumption in ktoe, not electricity-only consumption in MWh.",
                "No half-hourly system-demand series was verified as accessible in the public dataset catalogue during implementation. ML forecasting is therefore disabled rather than fabricated.",
                "A current USEP series, current generation mix, generation capacity/availability, and transmission availability were not added because a directly accessible, verified dataset was not established in this implementation."
            ],
            warnings=[],
            errors=[],
            confidence="high",
            data_timestamps={},
            is_ml_prediction=False,
        )

    with patch("backend.app.coordinator.city_agent.run_energy_agent", side_effect=_stub):
        yield
