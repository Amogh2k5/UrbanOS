import uvicorn
from backend.app.main import _build_app

if __name__ == "__main__":
    app = _build_app()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="debug", loop="asyncio")