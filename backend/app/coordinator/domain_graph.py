"""Shared invocation contract for independent UrbanOS domain workflows."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
import time

from backend.app.intelligence.contracts import DomainStatus


@dataclass
class DomainGraphResult:
    domain: str
    status: DomainStatus
    graph_state: Any
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    execution_time_ms: float = 0.0


class BaseDomainGraph:
    """Adapter that gives a compiled LangGraph a consistent public interface.

    Every call creates a fresh input mapping. Compiled graph definitions can be
    reused, while run state is never shared between coordinator executions.
    """

    def __init__(self, domain_name: str, graph: Any, state_schema: Any = None,
                 run_fn: Optional[Callable[..., Any]] = None):
        self.domain_name = domain_name
        # A few legacy agents expose their StateGraph builder result while the
        # rest expose a compiled graph. Normalize that boundary once.
        self.graph = graph if callable(getattr(graph, "invoke", None)) else graph.compile()
        self.state_schema = state_schema
        self.run_fn = run_fn

    def get_capabilities(self) -> Dict[str, Any]:
        nodes = getattr(self.graph, "nodes", {})
        if not nodes:
            get_graph = getattr(self.graph, "get_graph", None)
            if callable(get_graph):
                try:
                    nodes = getattr(get_graph(), "nodes", {})
                except Exception:
                    nodes = {}
        return {"domain": self.domain_name, "graph_nodes": list(nodes),
                "uses_ml": False, "standard_questions": []}

    def invoke(self, initial_state: Any = None, config: Optional[Dict[str, Any]] = None,
               timeout_seconds: Optional[float] = None) -> DomainGraphResult:
        started = time.monotonic()
        raw_state = dict(initial_state or {}) if isinstance(initial_state, (dict, type(None))) else initial_state
        try:
            if self.run_fn is not None:
                if isinstance(raw_state, dict) and "t0" in raw_state:
                    try:
                        report = self.run_fn(prediction_timestamp=raw_state["t0"])
                    except TypeError as exc:
                        # Keep the legacy no-argument runner contract supported.
                        if "prediction_timestamp" not in str(exc):
                            raise
                        report = self.run_fn()
                else:
                    report = self.run_fn()
                result = {"report": report}
            else:
                result = self.graph.invoke(raw_state, config=config)
            report = result.get("report") if isinstance(result, dict) else None
            if report is None:
                status = self._unavailable("Domain graph did not produce a report")
                errors = ["Domain graph did not produce a report"]
            else:
                try:
                    from backend.app.intelligence.normalize import normalize_domain_report
                    if isinstance(report, dict):
                        dump = dict(report)
                    else:
                        serializer = getattr(report, "model_dump", None) or getattr(report, "to_dict", None)
                        if not callable(serializer):
                            raise TypeError("domain report has no supported serializer")
                        try:
                            dump = serializer(mode="json")
                        except TypeError:
                            dump = serializer()
                    if not isinstance(dump, dict):
                        raise TypeError("domain report must serialize to a mapping")
                    if dump.get("available") is False and not dump.get("error"):
                        dump["error"] = "Domain report explicitly marked unavailable"
                    status = normalize_domain_report(self.domain_name, dump)
                    if not status.available:
                        errors = [status.error or f"{self.domain_name} assessment unavailable"]
                    else:
                        errors = []
                except Exception as exc:
                    message = f"Domain report could not be normalized: {exc}"
                    status = self._unavailable(message)
                    errors = [message]
            state_errors = result.get("errors", []) if isinstance(result, dict) else []
            state_warnings = result.get("warnings", []) if isinstance(result, dict) else []
            return DomainGraphResult(self.domain_name, status, result, list(errors) + list(state_errors or []),
                                     list(state_warnings or []), (time.monotonic() - started) * 1000)
        except Exception as exc:
            message = f"Graph execution failed: {exc}"
            return DomainGraphResult(self.domain_name, self._unavailable(message), {}, [message], [],
                                     (time.monotonic() - started) * 1000)

    def _unavailable(self, message: str) -> DomainStatus:
        return DomainStatus(domain=self.domain_name, available=False, overall_status=None,
            overall_risk=None, risk_level=None, key_metrics={}, active_alert_count=None,
            affected_zones=[], primary_risk_factors=[], confidence="low",
            limitations=[message], warnings=[], errors=[message], is_ml_prediction=False,
            generated_at=datetime.now().astimezone().isoformat())


class DomainGraphRegistry:
    _graphs: Dict[str, BaseDomainGraph] = {}
    _capabilities_cache: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def register(cls, graph: BaseDomainGraph) -> None:
        cls._graphs[graph.domain_name] = graph
        cls._capabilities_cache[graph.domain_name] = graph.get_capabilities()

    @classmethod
    def get(cls, domain_name: str) -> Optional[BaseDomainGraph]:
        return cls._graphs.get(domain_name)

    @classmethod
    def get_all(cls) -> List[BaseDomainGraph]:
        return list(cls._graphs.values())

    @classmethod
    def get_all_domains(cls) -> List[str]:
        return list(cls._graphs)

    @classmethod
    def get_capabilities(cls, domain_name: str) -> Optional[Dict[str, Any]]:
        return cls._capabilities_cache.get(domain_name)

    @classmethod
    def get_all_capabilities(cls) -> Dict[str, Dict[str, Any]]:
        return dict(cls._capabilities_cache)

    @classmethod
    def clear(cls) -> None:
        cls._graphs.clear()
        cls._capabilities_cache.clear()
