import subprocess
import time
import sys
import requests

proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8000'], cwd=r'C:\projects\UrbanOS', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(10)

try:
    response = requests.get('http://localhost:8000/api/overview/city', timeout=30)
    print(f'Status: {response.status_code}')
    if response.status_code == 200:
        data = response.json()
        print(f'Modules: {len(data.get("modules", []))}')
        print(f'Alerts count: {len(data.get("alerts", []))}')
        print(f'AI Brief: {data.get("ai_brief")}')
        
        alerts = data.get('alerts', [])
        if alerts:
            print('\nAlerts returned:')
            for alert in alerts:
                print(f'  - Domain: {alert.get("domain")}, Severity: {alert.get("severity")}, Title: {alert.get("title")[:60]}')
        else:
            print('\nNo alerts returned')
    else:
        print(f'Error: {response.text[:200]}')
except Exception as e:
    print(f'Error: {e}')
finally:
    proc.terminate()
    try:
        stdout, stderr = proc.communicate(timeout=5)
        print('\n=== SERVER STDOUT ===')
        print(stdout.decode()[-5000:])
        print('=== SERVER STDERR ===')
        print(stderr.decode()[-5000:])
    except:
        pass