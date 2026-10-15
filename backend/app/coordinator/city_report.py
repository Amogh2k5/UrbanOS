"""City Coordinator report models.

The coordinator's output contract. These are re-exported from
``backend.app.intelligence.contracts`` so the coordinator, the Overview API
and the frontend all speak one schema - there is deliberately only one
definition of ``CitySituationReport`` in the codebase.

``coordinator.city_report`` is the historical import path used by
``tests/test_city_coordinator.py``.
"""

from backend.app.intelligence.contracts import (
    AlertSeverity, CityRisk, CitySituationReport, CityStatus,
    CrossDomainImpact, CrossDomainSeverity, DomainStatus, Finding,
    PriorityIncident, validate_finding, validate_report,
)

__all__ = [
    "AlertSeverity", "CityRisk", "CitySituationReport", "CityStatus",
    "CrossDomainImpact", "CrossDomainSeverity", "DomainStatus", "Finding",
    "PriorityIncident", "validate_finding", "validate_report",
]