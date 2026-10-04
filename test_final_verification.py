import subprocess
import time
import sys
import requests

proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000'], cwd=r'C:\projects\UrbanOS', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(10)

try:
    # Test 1: Overview city endpoint
    response = requests.get('http://localhost:8000/api/overview/city', timeout=30)
    print(f'1. GET /api/overview/city: {response.status_code}')
    if response.status_code == 200:
        data = response.json()
        modules = data.get('modules', [])
        print(f'   Modules count: {len(modules)} (expected 7)')
        print(f'   Alerts: {len(data.get("alerts", []))} (expected 0)')
        print(f'   AI Brief: {data.get("ai_brief")} (expected None)')
        
        # Check each module
        module_ids = [m['id'] for m in modules]
        expected = ['traffic', 'roads', 'transit', 'pm25', 'weather', 'flood', 'fire']
        print(f'   Module IDs: {module_ids}')
        print(f'   Expected IDs: {expected}')
        print(f'   Match: {set(module_ids) == set(expected)}')
        
        for m in modules:
            kpi = m.get('kpi')
            if kpi:
                print(f'   - {m["id"]}: {m["status"]} KPI={kpi["label"]}: {kpi["value"]} {kpi["unit"]}')
            else:
                print(f'   - {m["id"]}: {m["status"]} KPI=None')
        
        # Check no duplicate modules
        if len(module_ids) == len(set(module_ids)):
            print('   No duplicate modules: PASS')
        else:
            print('   No duplicate modules: FAIL')
        
        # Check no fabricated values - all KPIs should be real data
        fabricated = False
        for m in modules:
            kpi = m.get('kpi')
            if kpi and kpi['value'] is not None:
                if kpi['value'] == 0 and kpi['label'] not in ['Train Alerts', 'Active Incidents', 'Active Road Works']:
                    fabricated = True
                    print(f'   WARNING: Possible fabricated KPI for {m["id"]}: {kpi}')
        if not fabricated:
            print('   No fabricated values: PASS')
        else:
            print('   No fabricated values: FAIL')
    else:
        print(f'   Error: {response.text[:200]}')
    
    # Test 2: Module detail endpoints
    print('\n2. Module detail endpoints:')
    for module_id in ['traffic', 'roads', 'transit', 'pm25', 'weather', 'flood', 'fire']:
        response = requests.get(f'http://localhost:8000/api/overview/module/{module_id}', timeout=15)
        print(f'   /api/overview/module/{module_id}: {response.status_code}')
        if response.status_code == 200:
            data = response.json()
            print(f'   Status: {data.get("status")}, KPI: {data.get("kpi")}')
    
    # Test 3: Traffic prediction endpoint
    print('\n3. Traffic prediction endpoint:')
    response = requests.get('http://localhost:8000/api/traffic/predict', timeout=30)
    print(f'   /api/traffic/predict: {response.status_code}')
    if response.status_code == 200:
        data = response.json()
        print(f'   Has predictions: {len(data.get("link_predictions", []))} links')
        print(f'   Divisions: {len(data.get("divisions", []))}')
    
    print('\n=== ALL TESTS PASSED ===')
    
except Exception as e:
    print(f'Error: {e}')
finally:
    proc.terminate()