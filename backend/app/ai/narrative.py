"""Grounded narrative input, deterministic fallback, and output validation.

The City Coordinator owns every factual conclusion. This module turns its
report into the *only* set of facts the LLM is permitted to speak about, and
then checks that the text the model returns is traceable back to them.

Design rules:

  * The narrative input is a bounded projection of ``CitySituationReport``. Raw
    module payloads never reach the prompt.
  * If the coordinator produced nothing usable, there is no narrative input
    and the caller must fall back to :func:`deterministic_summary`.
  * A number in the narrative must appear in the supplied evidence, unless it
    is a small ordinal. A number carrying a unit must always appear.
  * Status and severity words in the narrative must exist in the report.
  * Nothing here ever modifies the deterministic fields: the narrative is a
    separate, additive string.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

#: Units that, when attached to a number, make that number a factual claim.
#: Every such number must be traceable to the evidence.
_UNIT_TOKENS = (
    "km/h", "kmh", "kph",
    "µg/m³", "µg/m3", "ug/m3",
    "km²", "km2",
    "%", "°c", "c", "mm", "mm/hr", "cm", "m3", "million", "mw", "gw",
)

#: Plain integers this small are treated as ordinals ("three domains", "two
#: conditions") rather than measurements, so they do not require evidence.
_ORDINAL_MAX = 12

_NUMBER_RE = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(%|[a-zA-Zµ°][a-zA-Zµ°/³²0-9]*)?"
)

#: Vocabulary of status/severity words the model must not invent.
_STATUS_WORDS = {"NORMAL", "ELEVATED", "DISRUPTED", "CRITICAL",
                 "LOW", "MODERATE", "HIGH", "UNKNOWN"}

#: Task-meta commentary: the model talking *about* the job instead of doing it.
#: Observed live from nvidia/nemotron-3-ultra-550b-a55b, which restated the
#: instructions as prose. Such text contains no fabricated numbers or statuses,
#: so it passed the grounding checks and was being returned - and cached - as the
#: City Situation paragraph. A narrative describes the city, never the request.
_TASK_META_PATTERNS = (
    re.compile(r"\bthe user (?:wants|asks|is asking|requested|would like)\b", re.I),
    re.compile(r"\bi(?:'m| am)\b", re.I),
    re.compile(r"\bi (?:need|should|must|will|would|could|have to|am going to)\b", re.I),
    re.compile(r"\bas (?:an ai|a language model|requested|instructed)\b", re.I),
    re.compile(r"\bthe (?:above|following|preceding) (?:json|data|instructions?)\b", re.I),
    re.compile(r"\bi(?:'ll)? (?:first )?(?:need to|will|must|should)\b", re.I),
)


class NarrativeDomainFact(BaseModel):
    domain: str
    available: bool
    status: Optional[str] = None
    risk: Optional[str] = None
    key_metrics: Dict[str, Any] = Field(default_factory=dict)
    affected_zones: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    generated_at: Optional[str] = None


class NarrativeInput(BaseModel):
    """The bounded, evidence-carrying facts the model may speak about."""

    generated_at: str
    overall_city_status: str
    overall_risk_level: str
    confidence: str

    findings: List[str] = Field(default_factory=list)
    cross_domain_impacts: List[Dict[str, Any]] = Field(default_factory=list)
    priority_incidents: List[Dict[str, Any]] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)

    domains: List[NarrativeDomainFact] = Field(default_factory=list)
    affected_zones: List[str] = Field(default_factory=list)
    unavailable_domains: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)

    def evidence_numbers(self) -> Set[float]:
        """Every number the model was shown, at any depth of this input."""
        blob = self.model_dump_json()
        found: Set[float] = set()
        for m in _NUMBER_RE.finditer(blob):
            raw = m.group(1).replace(",", "")
            try:
                found.add(float(raw))
            except ValueError:
                continue
        return found

    def allowed_status_words(self) -> Set[str]:
        """Status/severity words that actually appear in this report.

        Deliberately *not* seeded with the whole vocabulary: a word the
        coordinator never used (claiming CRITICAL when it said HIGH) is a
        fabricated escalation and must be rejected.
        """
        words: Set[str] = {self.overall_city_status, self.overall_risk_level, "UNKNOWN"}
        for d in self.domains:
            if d.status:
                words.add(str(d.status).upper())
            if d.risk:
                words.add(str(d.risk).upper())
        for impact in self.cross_domain_impacts:
            sev = impact.get("severity")
            if sev:
                words.add(str(sev).upper())
        for incident in self.priority_incidents:
            sev = incident.get("severity")
            if sev:
                words.add(str(sev).upper())
        for rec in self.recommendations:
            for w in re.findall(r"\b[A-Z]{3,}\b", rec):
                if w in _STATUS_WORDS:
                    words.add(w)
        return {w for w in words if w}

    def canonical(self) -> str:
        """Stable serialization used for the cache key."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def cache_canonical(self) -> str:
        """Serialization that identifies the *evidence*, not the run.

        Identical to :meth:`canonical` except that timestamps are dropped: the
        report-level ``generated_at`` **and** the per-domain ``generated_at``.
        The coordinator re-runs every cache TTL and re-stamps both even when
        every assessed value is unchanged, so keying on them re-called the
        provider on every dashboard load - 720 calls/day against a 50/day
        free-tier quota.

        Only timestamps are removed. Every field that can change what the
        narrative says - statuses, risk, confidence, key metrics, affected
        zones, findings, impacts, recommendations, limitations and
        unavailable domains - stays in the key, so changed evidence can never
        reuse a previous narrative. The timestamps are still sent in the
        prompt; they simply do not identify which evidence this is.
        """
        payload = self.model_dump(mode="json")
        payload.pop("generated_at", None)
        domains = payload.get("domains")
        if isinstance(domains, list):
            for domain in domains:
                if isinstance(domain, dict):
                    domain.pop("generated_at", None)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class NarrativeValidation(BaseModel):
    ok: bool
    reasons: List[str] = Field(default_factory=list)
    unsupported_numbers: List[str] = Field(default_factory=list)
    unsupported_status_words: List[str] = Field(default_factory=list)


def _has_unit(suffix: Optional[str]) -> bool:
    if not suffix:
        return False
    s = suffix.strip().lower()
    return any(s == u.lower() or s.startswith(u.lower()) for u in _UNIT_TOKENS)


def _traceable(value: float, evidence: Set[float]) -> bool:
    for candidate in evidence:
        if abs(candidate - value) < 0.005:
            return True
        # Tolerate honest rounding ("about 55 km/h" for 54.6).
        if candidate != 0 and abs(candidate - value) / abs(candidate) <= 0.02:
            return True
    return False


def build_narrative_input(report: Any) -> Optional[NarrativeInput]:
    """Project a coordinator report into the bounded narrative input.

    Returns ``None`` when the report cannot support any statement, so the
    caller falls back to a deterministic summary instead of prompting a model
    with nothing.
    """
    if report is None:
        return None

    statuses = getattr(report, "domain_status", None) or {}
    impacts = [_i.model_dump(mode="json") if hasattr(_i, "model_dump") else dict(_i)
               for _i in (getattr(report, "cross_domain_impacts", None) or [])]
    incidents = [_i.model_dump(mode="json") if hasattr(_i, "model_dump") else dict(_i)
                 for _i in (getattr(report, "priority_incidents", None) or [])]

    domains: List[NarrativeDomainFact] = []
    unavailable: List[str] = []
    for name, ds in sorted(statuses.items()):
        ds = ds.model_dump(mode="json") if hasattr(ds, "model_dump") else dict(ds)
        domains.append(NarrativeDomainFact(
            domain=name,
            available=bool(ds.get("available")),
            status=ds.get("overall_status"),
            risk=ds.get("overall_risk"),
            key_metrics=ds.get("key_metrics") or {},
            affected_zones=[str(z) for z in (ds.get("affected_zones") or [])],
            limitations=[str(x) for x in (ds.get("limitations") or [])][:2],
            generated_at=ds.get("generated_at"),
        ))
        if not ds.get("available"):
            unavailable.append(name)

    recs = [str(r) for r in (getattr(report, "city_level_recommendations", None) or [])]

    city_status = str(getattr(report, "overall_city_status", None) or "UNKNOWN")
    confidence = str(getattr(report, "confidence", None) or "low")

    # Nothing validated and nothing available means nothing to narrate.
    has_signal = bool(impacts or incidents or recs)
    has_available_domain = any(d.available for d in domains)
    if not has_signal and not has_available_domain:
        return None

    return NarrativeInput(
        generated_at=str(getattr(report, "generated_at", "") or ""),
        overall_city_status=city_status,
        overall_risk_level=str(getattr(report, "overall_risk_level", None) or "UNKNOWN"),
        confidence=confidence,
        findings=[f"{i.get('type')}: {i.get('description')}" for i in impacts],
        cross_domain_impacts=impacts,
        priority_incidents=incidents,
        recommendations=recs,
        domains=domains,
        affected_zones=[str(z) for z in (getattr(report, "affected_zones", None) or [])],
        unavailable_domains=unavailable,
        limitations=[str(x) for x in (getattr(report, "limitations", None) or [])][:6],
    )


def deterministic_summary(report: Any) -> Optional[str]:
    """Always-available city summary. Never invents; never fails."""
    if report is None:
        return None
    ni = build_narrative_input(report)
    if ni is None:
        return ("City situation unavailable: no domain reported a usable status, "
                "and no validated findings are available.")

    parts = [
        f"City status {ni.overall_city_status} (risk {ni.overall_risk_level}, "
        f"confidence {ni.confidence})."
    ]
    if ni.findings:
        parts.append("Validated findings: " + "; ".join(ni.findings[:3]) + ".")
    if ni.affected_zones:
        parts.append(f"Affected zones: {', '.join(ni.affected_zones[:5])}.")
    if ni.unavailable_domains:
        parts.append(
            "Could not be assessed: " + ", ".join(ni.unavailable_domains)
            + ". Absence of data is not evidence of normal conditions."
        )
    return " ".join(parts)


def deterministic_summary_from_domains(domain_status: Optional[Dict[str, Any]]) -> Optional[str]:
    """Cold-start summary built from per-domain evidence only.

    Used when the coordinator report is not available yet (a measured run takes
    ~74s, longer than a dashboard refresh may wait). The caller already holds a
    ``DomainStatus`` per domain, produced by the same deterministic rules that
    drive the overview cards, so those readings *are* independently validated
    evidence.

    What this deliberately does **not** do, because per-domain status is not
    enough to derive them:

      * It never states a city-level status or risk level. Those are the
        coordinator's conclusions, from cross-domain impact analysis, and
        asserting them here would be invention.
      * It never states a severity, trend, affected area or causal link.
      * It never turns missing data into a normal status. Domains that could
        not be assessed are named, with the explicit note that absence of data
        is not evidence of normal conditions.

    Returns ``None`` when there is no per-domain evidence at all, so the caller
    shows nothing rather than something invented.
    """
    if not domain_status:
        return None

    available: List[str] = []
    unavailable: List[str] = []

    for name in sorted(domain_status):
        ds = domain_status[name]
        dumped = ds.model_dump(mode="json") if hasattr(ds, "model_dump") else dict(ds)
        if not dumped.get("available"):
            unavailable.append(str(name))
            continue
        status = dumped.get("overall_status") or dumped.get("overall_risk")
        available.append(f"{name}: {status}" if status
                         else f"{name}: assessed, no status reported")

    if not available and not unavailable:
        return None

    parts = [
        "City assessment pending: the City Coordinator has not produced a "
        "city-level assessment yet, so no city status or risk level is claimed."
    ]
    if available:
        parts.append("Domains reporting: " + "; ".join(available) + ".")
    if unavailable:
        parts.append(
            "Could not be assessed: " + ", ".join(unavailable)
            + ". Absence of data is not evidence of normal conditions."
        )
    return " ".join(parts)


def validate_narrative(text: Optional[str], narrative_input: NarrativeInput) -> NarrativeValidation:
    """Check a candidate narrative is traceable to the supplied evidence."""
    reasons: List[str] = []
    if text is None or not text.strip():
        return NarrativeValidation(ok=False, reasons=["empty narrative"])

    narrative = text.strip()

    # 1. Length bound: the City Situation is a concise paragraph.
    words = narrative.split()
    if len(words) > 140:
        reasons.append(f"narrative too long ({len(words)} words)")

    # 2. No leaked instructions or secrets.
    lowered = narrative.lower()
    for marker in ("you are urbanos", "system:", "do not invent", "untrusted note",
                   "bearer ", "sk-", "api_key", "prompt:"):
        if marker in lowered:
            reasons.append("leaked instruction/secret marker: %r" % marker)
            break

    # 2b. Task-meta commentary is not an answer. This carries no invented
    # numbers or statuses, so it survives every other check and would otherwise
    # be shown to operators as the city situation.
    for pattern in _TASK_META_PATTERNS:
        if pattern.search(narrative):
            reasons.append("answer is task commentary, not a narrative: %r"
                           % pattern.pattern[:40])
            break

    # 3. Every number must be traceable (units always; small ordinals excepted).
    evidence = narrative_input.evidence_numbers()
    bad_numbers: List[str] = []
    for m in _NUMBER_RE.finditer(narrative):
        raw = m.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        if _traceable(value, evidence):
            continue
        is_ordinal = (
            value.is_integer() and 1 <= value <= _ORDINAL_MAX and not _has_unit(m.group(2))
        )
        if not is_ordinal:
            bad_numbers.append(m.group(0).strip())
    if bad_numbers:
        reasons.append("numbers not present in the supplied evidence: "
                       + ", ".join(sorted(set(bad_numbers))[:8]))

    # 4. Status/severity vocabulary must come from the report.
    allowed = narrative_input.allowed_status_words()
    bad_words = sorted({
        w for w in re.findall(r"\b[A-Z]{3,}\b", narrative) if w in _STATUS_WORDS and w not in allowed
    })
    if bad_words:
        reasons.append("status/severity words not present in the coordinator report: "
                       + ", ".join(bad_words))

    return NarrativeValidation(
        ok=not reasons,
        reasons=reasons,
        unsupported_numbers=sorted(set(bad_numbers)),
        unsupported_status_words=bad_words,
    )