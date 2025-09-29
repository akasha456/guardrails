#!/usr/bin/env python3
"""
WebSocket server that exposes Llama-3.2 (Ollama) to remote clients.
pip install aiohttp ollama
"""

import asyncio
import json
import logging
from aiohttp import web, WSMsgType
from ollama import AsyncClient

HOST = "0.0.0.0"
PORT = 8765
MODEL  = "llama3.2"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [S] %(message)s")
log = logging.getLogger("ws-server")

# --------------------------------------------------------------------------- #
# Application-wide Ollama client (single instance)
# --------------------------------------------------------------------------- #
ollama = AsyncClient()

# --------------------------------------------------------------------------- #
# WebSocket handler
# --------------------------------------------------------------------------- #
async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    peer = request.transport.get_extra_info('peername')  # (ip, port)
    client = f"{request.remote}:{peer[1]}"
    log.info("Client %s connected", client)

    async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
                prompt = data["prompt"]
                log.info("Prompt (%d chars) from %s", len(prompt), client)

                # Stream tokens from Ollama
                async for part in await ollama.chat(
                    model=MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    stream=True
                ):
                    delta = part["message"]["content"]
                    await ws.send_str(json.dumps({"token": delta}))

                # End-of-stream sentinel
                await ws.send_str(json.dumps({"token": None}))

            except Exception as exc:
                log.exception("Error while processing prompt")
                await ws.send_str(json.dumps({"error": str(exc)}))

        elif msg.type == WSMsgType.ERROR:
            log.error("WS error %s", ws.exception())

    log.info("Client %s disconnected", client)
    return ws


# --------------------------------------------------------------------------- #
# Build & run
# --------------------------------------------------------------------------- #
def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/ws", websocket_handler)
    return app


if __name__ == "__main__":
    web.run_app(build_app(), host=HOST, port=PORT)