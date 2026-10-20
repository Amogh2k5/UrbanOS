
"""Energy Agent: evidence-grounded report generation."""
from .data import fetch_snapshot
from .processing import build_report
from .models import EnergyReport

def run_energy_agent() -> EnergyReport:
    """Acquire official datasets and produce a deterministic EnergyReport."""
    return build_report(fetch_snapshot())
