"""UrbanOS City Coordinator Module.

City Coordinator orchestrates Environment, Traffic, and Flood domain agents
to produce a unified City Situation Report.
"""

from coordinator.city_agent import (
    CityCoordinatorState,
    create_city_coordinator,
    get_city_coordinator,
    run_city_coordinator,
    collect_reports,
    normalize_state,
    analyze_cross_domain_impacts,
    prioritize_risks,
    generate_recommendations,
    build_report,
)
from coordinator.city_report import (
    CitySituationReport,
    DomainStatus,
    CrossDomainImpact,
    PriorityIncident,
)

__all__ = [
    # Agent
    "CityCoordinatorState",
    "create_city_coordinator",
    "get_city_coordinator",
    "run_city_coordinator",
    "collect_reports",
    "normalize_state",
    "analyze_cross_domain_impacts",
    "prioritize_risks",
    "generate_recommendations",
    "build_report",
    # Report models
    "CitySituationReport",
    "DomainStatus",
    "CrossDomainImpact",
    "PriorityIncident",
]