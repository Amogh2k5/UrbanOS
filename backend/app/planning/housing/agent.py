"""HousingAgent: source-backed deterministic analytics, no invented claims."""
from .data import fetch_housing_snapshot
from .processing import build_housing_report

class HousingAgent:
    def __init__(self, fetcher=fetch_housing_snapshot):
        self.fetcher = fetcher

    def run(self):
        return build_housing_report(self.fetcher())

def run_housing_agent():
    return HousingAgent().run()
