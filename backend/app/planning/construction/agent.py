"""ConstructionAgent: source-backed deterministic analytics, no invented claims."""
from .data import fetch_construction_snapshot
from .processing import build_construction_report

class ConstructionAgent:
    def __init__(self, fetcher=fetch_construction_snapshot):
        self.fetcher = fetcher

    def run(self):
        return build_construction_report(self.fetcher())

def run_construction_agent():
    return ConstructionAgent().run()