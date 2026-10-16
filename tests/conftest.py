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

os.environ["URBANOS_COORDINATOR_BACKGROUND"] = "0"

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _coordinator_background_runs_disabled():
    from backend.app.coordinator import access

    access.set_background_runs_enabled(False)
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