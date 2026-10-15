"""Shared intelligence contracts and normalisation for UrbanOS."""

from backend.app.intelligence.contracts import (
    AlertSeverity, CityRisk, CitySituationReport, CityStatus, CrossDomainImpact,
    CrossDomainSeverity, DataKind, DomainStatus, EvidenceRef, Finding, Freshness,
    PriorityIncident, Trend, validate_finding, validate_report,
)
from backend.app.intelligence.normalize import (
    DOMAIN_NAMES, DOMAIN_ROUTES, build_findings, build_kpi, determine_status,
    normalize_domain_report,
)

__all__ = [
    "AlertSeverity", "CityRisk", "CitySituationReport", "CityStatus",
    "CrossDomainImpact", "CrossDomainSeverity", "DataKind", "DomainStatus",
    "EvidenceRef", "Finding", "Freshness", "PriorityIncident", "Trend",
    "validate_finding", "validate_report", "DOMAIN_NAMES", "DOMAIN_ROUTES",
    "build_findings", "build_kpi", "determine_status", "normalize_domain_report",
]