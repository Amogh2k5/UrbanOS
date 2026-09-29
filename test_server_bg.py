import asyncio
from fastapi import FastAPI
import uvicorn

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

config = uvicorn.Config(app, host="127.0.0.1", port=8004, log_level="debug", loop="asyncio")
server = uvicorn.Server(config)
print("Starting server...")
asyncio.run(server.serve())
print("Server stopped")