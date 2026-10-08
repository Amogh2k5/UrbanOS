import sys
sys.path.insert(0, r'C:\projects\UrbanOS')
from backend.app.infrastructure.water.agent import run_water_agent
report = run_water_agent()
d = report.model_dump(mode='json')
print(f'Errors: {d["errors"]}')
print(f'Warnings: {d["warnings"]}')