#!/usr/bin/env python3
"""
FastAPI WebSocket server that exposes Llama-3.2 (Ollama) to remote clients.
"""
import datetime
import asyncio
import logging
from typing import Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from ollama import AsyncClient  # pip install ollama
from logging_config import setup_logging, get_ollama_logger

HOST = "0.0.0.0"
PORT = 8765
MODEL = "llama3.2"

setup_logging()
log = get_ollama_logger()

app = FastAPI()
ollama = AsyncClient()


class ConnectionManager:
    def __init__(self):
        self.active: Dict[str, WebSocket] = {}

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active[ws.client.host] = ws
        log.warning("Client %s connected", ws.client.host)

    def disconnect(self, ws: WebSocket):
        self.active.pop(ws.client.host, None)
        log.warning("Client %s disconnected", ws.client.host)

    async def send_json(self, ws: WebSocket, data: dict):
        try:
            await ws.send_json(data)
        except Exception:
            pass


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    time_start=datetime.datetime.now()
    try:
        while True:
            msg = await ws.receive_json()
            prompt = msg.get("prompt", "")
            stream = msg.get("stream", True)
            log.info("Prompt (%d chars) from %s  stream=%s", len(prompt), ws.client.host, stream)

            try:
                if stream:
                    # ---------- STREAMING: SEND TOKENS ONE BY ONE ----------
                    async for part in await ollama.chat(
                        model=MODEL,
                        messages=[{"role": "user", "content": prompt}],
                        stream=True,
                    ):
                        delta = part["message"]["content"]
                        # delta is a string (e.g., "Hello", " world", "!")
                        await manager.send_json(ws, {"token": delta})

                    # End-of-stream marker
                    await manager.send_json(ws, {"token": None})
                else:
                    # ---------- ONE-SHOT ----------
                    resp = await ollama.chat(
                        model=MODEL,
                        messages=[{"role": "user", "content": prompt}],
                        stream=False,
                    )
                    answer = resp["message"]["content"]
                    await manager.send_json(ws, {"response": answer})
                latency = (datetime.datetime.now() - time_start).total_seconds() * 1000
                log.info("Prompt processed for client %s with latency %s", ws.client.host, latency)
            except Exception as exc:
                log.exception("Error while processing prompt for client %s: %s", ws.client.host, exc)
                await manager.send_json(ws, {"error": str(exc)})
    except WebSocketDisconnect:
        log.warning("Client %s disconnected", ws.client.host)
        manager.disconnect(ws)


@app.get("/")
async def health():
    return "FastAPI Llama-3.2 WebSocket server is running."


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("modelserver:app", host=HOST, port=PORT, log_level="info")