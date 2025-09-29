#!/usr/bin/env python3
"""
FastAPI WebSocket server that exposes Llama-3.2 (Ollama) to remote clients.
"""
import asyncio
import logging
from typing import Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from ollama import AsyncClient  # pip install ollama

HOST = "0.0.0.0"
PORT = 8765
MODEL = "llama3.2"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [F] %(message)s")
log = logging.getLogger("fastapi-ws")

app = FastAPI()
ollama = AsyncClient()

# simple connection manager
class ConnectionManager:
    def __init__(self):
        self.active: Dict[str, WebSocket] = {}

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active[ws.client.host] = ws
        log.info("Client %s connected", ws.client.host)

    def disconnect(self, ws: WebSocket):
        self.active.pop(ws.client.host, None)
        log.info("Client %s disconnected", ws.client.host)

    async def send_json(self, ws: WebSocket, data: dict):
        try:
            await ws.send_json(data)
        except Exception:
            pass  # client gone

manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            # expect {"prompt": "..."}
            msg = await ws.receive_json()
            prompt = msg.get("prompt", "")
            log.info("Prompt (%d chars) from %s", len(prompt), ws.client.host)

            try:
                async for part in await ollama.chat(
                    model=MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    stream=True,
                ):
                    delta = part["message"]["content"]
                    await manager.send_json(ws, {"token": delta})

                # end-of-stream sentinel
                await manager.send_json(ws, {"token": None})

            except Exception as exc:
                log.exception("Error while processing prompt")
                await manager.send_json(ws, {"error": str(exc)})

    except WebSocketDisconnect:
        manager.disconnect(ws)


@app.get("/")
async def health():
    return "FastAPI Llama-3.2 WebSocket server is running."


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host=HOST, port=PORT, log_level="info")