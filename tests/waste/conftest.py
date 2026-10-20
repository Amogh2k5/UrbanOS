"""Keep the Waste tests hermetic: no real disk cache, no real throttle sleeping, clean shared state."""
import pytest


@pytest.fixture(autouse=True)
def _hermetic_waste(monkeypatch):
    monkeypatch.setenv("URBANOS_WASTE_DISK_CACHE", "0")
    monkeypatch.delenv("DATA_GOV_SG_API_KEY", raising=False)
    monkeypatch.delenv("URBANOS_WASTE_POLL_INTERVAL_S", raising=False)
    from backend.app.infrastructure.waste import sources
    sources._LAST_POLL[0] = 0.0
    sources._GLOBAL_CACHE.clear()
    monkeypatch.setattr(sources, "_DEFAULT_CLIENT", None)
    yield
