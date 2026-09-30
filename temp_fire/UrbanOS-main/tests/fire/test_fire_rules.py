
from backend.app.safety.fire.rules import classify_severity, classify_status, classify_type, infer_region


def test_status_active_and_resolved():
    assert classify_status("Firefighting operations are still ongoing.") == "ACTIVE"
    assert classify_status("The fire was fully extinguished.") == "RESOLVED"


def test_severity_is_evidence_based():
    assert classify_severity("Two bodies were found at the scene.") == "CRITICAL"
    assert classify_severity("A small fire was extinguished.") == "UNKNOWN"


def test_type_and_region():
    assert classify_type("Fire Incident at a factory", "Industrial plant") == "Industrial / factory fire"
    assert infer_region("No. 6 Hougang St 92", None, None) == "East"
