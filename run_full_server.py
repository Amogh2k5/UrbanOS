import uvicorn
from backend.app.main import _build_app

app = _build_app()
uvicorn.run(app, host="127.0.0.1", port=8000, log_level="debug", loop="asyncio")