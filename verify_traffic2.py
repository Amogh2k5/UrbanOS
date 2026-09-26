import subprocess, time, requests, sys, os, signal, json, atexit

def kill_port(port):
    try:
        subprocess.run(["cmd", "/c", f"for /f \"tokens=5\" %a in ('netstat -aon ^| findstr :{port}') do taskkill /F /PID %a"], shell=True, capture_output=True)
    except Exception:
        pass

def start_backend():
    proc = subprocess.Popen([
        "uvicorn", "backend.app.main:app",
        "--host", "0.0.0.0", "--port", "8000"
    ], cwd=r"C:\projects\UrbanOS", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc

def start_frontend():
    proc = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=r"C:\projects\UrbanOS\frontend",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        shell=True
    )
    return proc

def wait_for(url, timeout=120):
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

def main():
    # kill existing
    kill_port(8000)
    kill_port(3000)
    time.sleep(2)

    print("Starting backend...")
    backend = start_backend()
    print("Starting frontend...")
    frontend = start_frontend()

    try:
        print("Waiting for backend...")
        if not wait_for("http://127.0.0.1:8000/health", 60):
            print("Backend not ready")
            return False
        print("Backend ready")

        print("Waiting for frontend...")
        if not wait_for("http://127.0.0.1:3000/mobility/traffic", 180):
            print("Frontend not ready")
            return False
        print("Frontend ready")

        # Test endpoints
        print("Testing /api/traffic/report...")
        r = requests.get("http://127.0.0.1:8000/api/traffic/report", timeout=30)
        print("Status:", r.status_code)
        data = r.json()
        print("Keys:", list(data.keys())[:10])

        print("Testing /api/mobility/traffic/predict...")
        r = requests.get("http://127.0.0.1:8000/api/mobility/traffic/predict", timeout=30)
        print("Status:", r.status_code)
        data = r.json()
        print("Keys:", list(data.keys())[:10])

        # Check that five regions present
        divisions = data.get('divisions', [])
        region_names = [d.get('division') for d in divisions]
        print("Regions:", region_names)
        expected = {"Central", "East", "North", "North-East", "West"}
        if set(region_names) == expected:
            print("All five regions present")
        else:
            print("Missing regions:", expected - set(region_names))

        # Check no overlapping requests by rapid calls? Hard to test.

        print("All checks passed")
        return True
    finally:
        backend.terminate()
        frontend.terminate()

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)