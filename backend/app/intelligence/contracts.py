"""Shared intelligence contracts for UrbanOS.

This package holds the one vocabulary that every layer speaks: domain modules
produce :class:`Finding` objects, the coordinator normalises them into
:class:`DomainStatus`, and the narrative layer may only rephrase conclusions
that are already present here.

Design rules (lifted from the Water and Land modules, which are the reference
implementations and already share this shape):

  * Every finding says what kind of data it is built on (:data:`DataKind`).
  * Missing data is ``None`` / ``"unavailable"`` - never zero, never guessed.
  * A finding without evidence may not claim a condition. Either it carries
    evidence, or its ``data_kind`` is ``"unavailable"``.
  * Severity is assigned by deterministic rules, never by a language model.

This module deliberately imports **no domain package**. Domain reports are
converted by :mod:`backend.app.intelligence.normalize`, which depends on this
module but never the reverse, so no import cycle is possible.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# Reused verbatim from backend.app.infrastructure.water.models and
# backend.app.planning.land.models so existing reports validate unchanged.
DataKind = Literal["live", "latest_available", "historical", "forecast", "unavailable"]
AlertSeverity = Literal["LOW", "MODERATE", "HIGH"]
CrossDomainSeverity = Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]
CityStatus = Literal["NORMAL", "ELEVATED", "DISRUPTED", "CRITICAL", "UNKNOWN"]
CityRisk = Literal["LOW", "MODERATE", "HIGH", "CRITICAL", "UNKNOWN"]
Trend = Literal["rising", "falling", "stable", "unknown"]

#: Freshness of the underlying data, independent of ``DataKind``.
Freshness = Literal["live", "recent", "stale", "unknown"]


class EvidenceRef(BaseModel):
    """A single traceable measurement behind a finding."""

    source_key: Optional[str] = None
    source_name: Optional[str] = None
    metric: str
    value: Optional[Any] = None
    unit: str = ""
    observed_at: Optional[str] = None
    data_kind: DataKind = "latest_available"

    def citation(self) -> str:
        """Human-readable form used verbatim in prompts and the UI."""
        bits = [self.metric]
        if self.value is not None:
            bits.append(f"{self.value}{(' ' + self.unit) if self.unit else ''}")
        if self.observed_at:
            bits.append(f"at {self.observed_at}")
        if self.source_name or self.source_key:
            bits.append(f"({self.source_name or self.source_key})")
        return " ".join(bits)


class Finding(BaseModel):
    """One evidence-backed statement about a domain.

    A finding is the atom of UrbanOS intelligence. City Situation, Active Risk
    Signals, KPI insight panels and Copilot answers are all *projections* of
    these objects - they are never generated separately.
    """

    id: str
    domain: str
    title: str
    answer: str
    data_kind: DataKind

    category: str = "general"
    question: Optional[str] = None

    # Deterministic severity. None means "not enough basis to rank".
    severity: Optional[AlertSeverity] = None

    evidence: List[str] = Field(default_factory=list)
    evidence_refs: List[EvidenceRef] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)

    observed_at: Optional[str] = None
    freshness: Freshness = "unknown"

    affected_area: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)

    #: Canonical numbers behind this finding. The narrative validator checks
    #: every number the LLM emits against these values.
    metrics: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


class DomainStatus(BaseModel):
    """Normalised per-domain view shared by every consumer.

    Field names and severities match ``frontend/src/types/index.ts``
    (``DomainStatus``) exactly, so no frontend change is required to consume it.
    """

    domain: str
    available: bool = False

    overall_status: Optional[str] = None
    overall_risk: Optional[str] = None
    risk_level: Optional[str] = None

    key_metrics: Dict[str, Any] = Field(default_factory=dict)
    active_alert_count: Optional[int] = None

    affected_zones: List[str] = Field(default_factory=list)
    primary_risk_factors: List[str] = Field(default_factory=list)

    confidence: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)
    is_ml_prediction: bool = False

    # Backend-only additions. Safe: the frontend type is a strict subset.
    generated_at: Optional[str] = None
    source_status: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)
    error: Optional[str] = None
    detail_route: Optional[str] = None
    display_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


class CrossDomainImpact(BaseModel):
    """A relationship between two domains that required real evidence."""

    type: str
    description: str
    severity: CrossDomainSeverity
    affected_zones: List[str] = Field(default_factory=list)
    domains_involved: List[str] = Field(default_factory=list)
    #: Mandatory. An impact with no evidence is correlation, not intelligence.
    evidence: List[str] = Field(default_factory=list)


class PriorityIncident(BaseModel):
    id: str
    type: str
    domain: str
    severity: AlertSeverity
    description: str
    affected_zones: List[str] = Field(default_factory=list)
    source_report: str = ""
    related_domains: List[str] = Field(default_factory=list)
    cascading_risk: Optional[str] = None


class CitySituationReport(BaseModel):
    """Output of the deterministic coordinator.

    Matches ``frontend/src/types/index.ts`` ``CitySituationReport``.
    """

    generated_at: str
    overall_city_status: CityStatus = "UNKNOWN"
    overall_risk_level: CityRisk = "UNKNOWN"

    domain_status: Dict[str, DomainStatus] = Field(default_factory=dict)
    priority_incidents: List[PriorityIncident] = Field(default_factory=list)
    cross_domain_impacts: List[CrossDomainImpact] = Field(default_factory=list)
    city_level_recommendations: List[str] = Field(default_factory=list)
    affected_zones: List[str] = Field(default_factory=list)

    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"
    limitations: List[str] = Field(default_factory=list)
    source_reports: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    is_ml_prediction: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


# ----------------------------------------------------------------- validation
def validate_finding(finding: Finding) -> List[str]:
    """Return a list of contract violations for one finding (empty = valid).

    This is the single gate every finding passes through before it can reach a
    consumer. It is deliberately pure so it can be unit-tested without any
    network, model or database.
    """
    problems: List[str] = []
    if not finding.title.strip():
        problems.append("title is empty")
    if not finding.answer.strip():
        problems.append("answer is empty")
    if finding.data_kind != "unavailable" and not (
        finding.evidence or finding.evidence_refs or finding.metrics
    ):
        problems.append(
            "finding claims a condition but carries no evidence or metrics"
        )
    if finding.data_kind == "unavailable" and finding.severity is not None:
        problems.append("unavailable data must not be assigned a severity")
    return problems


def validate_report(report: CitySituationReport) -> List[str]:
    """Contract checks for a whole coordinator report."""
    problems: List[str] = []
    for impact in report.cross_domain_impacts:
        if not impact.evidence:
            problems.append(
                f"cross-domain impact '{impact.type}' has no evidence"
            )
        if len(impact.domains_involved) < 2:
            problems.append(
                f"cross-domain impact '{impact.type}' involves fewer than 2 domains"
            )
    for domain_id, status in report.domain_status.items():
        if status.available and status.error:
            problems.append(f"domain '{domain_id}' is available but carries an error")
        if not status.available and status.overall_status not in (None, "UNKNOWN"):
            problems.append(
                f"unavailable domain '{domain_id}' must not report status "
                f"{status.overall_status!r}"
            )
    return problems