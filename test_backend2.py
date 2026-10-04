import subprocess
import time
import requests
import sys

proc = subprocess.Popen([sys.executable, '-m', 'backend.app.main'], cwd=r'C:\projects\UrbanOS', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(15)

try:
    # Check if process is still alive
    if proc.poll() is not None:
        stdout, stderr = proc.communicate()
        print(f'Process exited with code {proc.returncode}')
        print(f'STDOUT: {stdout.decode()[-2000:]}')
        print(f'STDERR: {stderr.decode()[-2000:]}')
    else:
        print('Process still running')
        response = requests.get('http://localhost:8000/health', timeout=5)
        print(f'Health: {response.status_code} - {response.json()}')
except Exception as e:
    print(f'Error: {e}')
    try:
        stdout, stderr = proc.communicate(timeout=2)
        print(f'STDOUT: {stdout.decode()[-2000:]}')
        print(f'STDERR: {stderr.decode()[-2000:]}')
    except:
        pass
finally:
    proc.terminate()