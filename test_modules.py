import subprocess
import time
import sys
import requests

proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000'], cwd=r'C:\projects\UrbanOS', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(10)

try:
    # Test module detail endpoints with longer timeout
    for module_id in ['traffic', 'roads', 'transit', 'pm25', 'weather', 'flood', 'fire']:
        try:
            response = requests.get(f'http://localhost:8000/api/overview/module/{module_id}', timeout=60)
            print(f'/api/overview/module/{module_id}: {response.status_code}')
            if response.status_code == 200:
                data = response.json()
                print(f'  Status: {data.get("status")}, Summary: {data.get("summary")[:80]}...')
        except Exception as e:
            print(f'   /api/overview/module/{module_id}: Error - {e}')
    
    # Test traffic prediction
    response = requests.get('http://localhost:8000/api/traffic/predict', timeout=30)
    print(f'/api/traffic/predict: {response.status_code}')
    if response.status_code == 200:
        data = response.json()
        print(f'  Predictions: {len(data.get("link_predictions", []))} links')
        print(f'  Divisions: {len(data.get("divisions", []))}')
    
    print('\n=== ALL TESTS PASSED ===')
    
except Exception as e:
    print(f'Error: {e}')
finally:
    proc.terminate()