"""Compatibility alias package -> ``backend.app.coordinator``.

See ``coordinator/city_agent.py`` for why this exists. Both this package and
the implementation module are replaced in ``sys.modules`` so that the
top-level ``coordinator.city_agent`` path used by ``backend/app/main.py`` and
by the existing water coordinator tests resolves to the real module.
"""

import sys

import backend.app.coordinator as _impl

from backend.app.coordinator import city_agent  # noqa: F401  (populate attribute)

_impl.city_agent = city_agent
sys.modules[__name__] = _impl