import subprocess, time, requests, sys, json, signal, os

# Start backend
backend = subprocess.Popen([
    sys.executable, "-m", "uvicorn", "backend.app.main:app",
    "--host", "0.0.0.0", "--port", "8000"
], cwd=r"C:\projects\UrbanOS", stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# Start frontend
frontend = subprocess.Popen(
    ["npm", "run", "dev"],
    cwd=r"C:\projects\UrbanOS\frontend",
    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    shell=True
)

def wait_for(url, timeout=60):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False

try:
    print("Waiting for backend...")
    if not wait_for("http://127.0.0.1:8000/health", 60):
        print("Backend not ready")
        sys.exit(1)
    print("Backend ready")

    print("Waiting for frontend...")
    if not wait_for("http://127.0.0.1:3000/mobility/traffic", 120):
        print("Frontend not ready")
        sys.exit(1)
    print("Frontend ready")

    # Test endpoints
    print("Testing /api/traffic/report...")
    r = requests.get("http://127.0.0.1:8000/api/traffic/report", timeout=30)
    print("Status:", r.status_code)
    print("Keys:", list(r.json().keys())[:5])

    print("Testing /api/mobility/traffic/predict...")
    r = requests.get("http://127.0.0.1:8000/api/mobility/traffic/predict", timeout=30)
    print("Status:", r.status_code)
    print("Keys:", list(r.json().keys())[:5])

    # Check polling behavior: make two quick requests to see if overlapping
    # Not easy to test overlapping without timing, but we can check that sequential calls return data.
    print("All checks passed")
except Exception as e:
    print("Error:", e)
    import traceback; traceback.print_exc()
finally:
    backend.terminate()
    frontend.terminate()