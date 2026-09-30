
from datetime import datetime, timezone

from backend.app.safety.fire.agent import FireAgentState, analyze_fire
from backend.app.safety.fire.models import FireHistoryPoint, FireIncident


def test_fire_agent_does_not_turn_missing_feed_into_zero():
    state = FireAgentState(
        incidents=[],
        historical=[FireHistoryPoint(year=2025, fires=2050, source="test")],
        source_status="historical_only",
    )
    result = analyze_fire(state)
    assert result.report is not None
    assert result.report.active_incident_count is None
    assert result.report.critical_incident_count is None


def test_fire_agent_counts_published_active_incidents():
    state = FireAgentState(
        incidents=[
            FireIncident(
                id="1",
                title="Test fire",
                source="test",
                status="ACTIVE",
                severity="HIGH",
            ),
            FireIncident(
                id="2",
                title="Resolved fire",
                source="test",
                status="RESOLVED",
                severity="UNKNOWN",
            ),
        ],
        source_status="published_incidents",
    )
    result = analyze_fire(state)
    assert result.report.active_incident_count == 1
    assert result.report.resolved_recent_count == 1
