import sys
sys.path.insert(0, r'C:\projects\UrbanOS')

# 1. Safety contains exactly Crime + Fire
import os
safety_dir = r'C:\projects\UrbanOS\backend\app\safety'
safety_modules = [d for d in os.listdir(safety_dir) if os.path.isdir(os.path.join(safety_dir, d))]
print(f"1. Safety modules: {safety_modules}")
assert set(safety_modules) == {"crime", "fire"}, f"Expected {{'crime', 'fire'}}, got {set(safety_modules)}"

# 2. No old Safety "Incidents" module registered
from backend.app.main import app
incidents_routes = [r for r in app.routes if hasattr(r, 'path') and 'incident' in r.path.lower() and 'safety' in r.path]
print(f"2. Safety incidents routes: {[r.path for r in incidents_routes]}")
safety_incident_routes = [r for r in app.routes if hasattr(r, 'path') and r.path.startswith('/api/safety/incidents')]
print(f"   /api/safety/incidents routes: {[r.path for r in safety_incident_routes]}")
assert len(safety_incident_routes) == 0, "Old Incidents module still registered"

# 3. Frontend Safety navigation uses Crime
with open(r'C:\projects\UrbanOS\frontend\src\components\common\TopNav.tsx', 'r', encoding='utf-8') as f:
    topnav = f.read()
has_incidents = 'incidents' in topnav and '/safety/incidents' in topnav
has_crime = '/safety/crime' in topnav
print(f"3. TopNav: has '/safety/incidents'={has_incidents}, has '/safety/crime'={has_crime}")
assert not has_incidents, "TopNav still has incidents"
assert has_crime, "TopNav missing crime"

# 4. City Coordinator/module registration uses Crime
with open(r'C:\projects\UrbanOS\backend\app\overview\api.py', 'r') as f:
    overview = f.read()
has_crime_module = '"crime"' in overview
print(f"4. Overview API has crime module: {has_crime_module}")
assert has_crime_module, "Crime module not in overview API"

# 5. /api/crime/report works (GET)
from fastapi.testclient import TestClient
client = TestClient(app)
response = client.get('/api/crime/report')
print(f"5. /api/crime/report status: {response.status_code}")
assert response.status_code == 200, f"Expected 200, got {response.status_code}"
data = response.json()
assert 'generated_at' in data, "Missing generated_at in response"

# 6. Crime appears correctly in Overview
response = client.get('/api/overview/city')
data = response.json()
crime_module = next((m for m in data.get('modules', []) if m['id'] == 'crime'), None)
print(f"6. Crime in overview: {crime_module}")
assert crime_module is not None, "Crime module not in overview"
assert crime_module['detail_route'] == '/safety/crime', f"Wrong detail_route: {crime_module.get('detail_route')}"

# 7. Fire remains unchanged
fire_module = next((m for m in data.get('modules', []) if m['id'] == 'fire'), None)
print(f"7. Fire in overview: {fire_module}")
assert fire_module is not None, "Fire module not in overview"

# 8. Run Crime tests
print("8. Running crime tests...")
import subprocess
result = subprocess.run([sys.executable, "-m", "pytest", "tests/crime/", "-v"], 
                       cwd=r'C:\projects\UrbanOS', capture_output=True, text=True, timeout=60)
print(f"   Exit code: {result.returncode}")
print(f"   Stdout: {result.stdout[-1000:]}")
if result.returncode != 0:
    print(f"   Stderr: {result.stderr[-1000:]}")

# Frontend build
print("   Building frontend...")
result = subprocess.run(["npm", "run", "build"], 
                       cwd=r'C:\projects\UrbanOS\frontend', capture_output=True, text=True, timeout=120)
print(f"   Frontend build exit code: {result.returncode}")
if result.returncode != 0:
    print(f"   Stdout: {result.stdout[-1000:]}")
    print(f"   Stderr: {result.stderr[-1000:]}")

print("\n=== VERIFICATION COMPLETE ===")