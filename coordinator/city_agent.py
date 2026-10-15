"""Import-path compatibility alias for the City Coordinator.

The coordinator's implementation lives in ``backend/app/coordinator/`` where
every other agent in this repository lives.

Two pre-existing call sites import it as a **top-level** ``coordinator``
package:

  * ``backend/app/main.py``  -> ``from coordinator.city_agent import run_city_coordinator``
    (it prepends the repository root to ``sys.path`` first)
  * ``tests/water/test_water_agent_report_api.py`` -> ``from coordinator.city_agent import ...``

Those references predate this package and are left untouched, so this shim makes
``coordinator.city_agent`` resolve to the very same module object. It is an
alias, not a wrapper: ``coordinator.city_agent is
backend.app.coordinator.city_agent`` holds, so ``unittest.mock.patch`` on either
path patches the same globals and the real graph behaviour is what gets
tested.
"""

import sys

from backend.app.coordinator import city_agent as _impl

# Replace this module in sys.modules so `import coordinator.city_agent` hands
# back the implementation module itself rather than this shim.
sys.modules[__name__] = _impl