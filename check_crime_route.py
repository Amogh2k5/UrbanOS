import sys
sys.path.insert(0, r'C:\projects\UrbanOS')
from backend.app.main import app

for route in app.routes:
    if hasattr(route, 'path') and 'crime' in route.path:
        print(f'Route: {route.path}, methods: {getattr(route, "methods", "N/A")}')