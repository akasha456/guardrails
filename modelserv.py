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

@app.websocket("/llama3.2")
async def websocket_endpoint(ws: WebSocket):
    client=await manager.connect(ws)
    log.info("Client %s connected into ollama endpoint for generation", ws.client.host)
    time_start=datetime.datetime.now()
    try:
        all_streams = ""  # Create a list to store all the stream responses
        msg = await ws.receive_json()
        stream= msg.get("stream", True)
        try:
            if stream:
                # ---------- STREAMING: SEND TOKENS ONE BY ONE ----------
                async for part in await ollama.chat(
                    model=msg.get("model", MODEL),
                    messages=msg.get("messages"),
                    stream=stream,
                ):
                    delta = part["message"]["content"]
                    # delta is a string (e.g., "Hello", " world", "!")
                    await manager.send_json(ws, {"token": delta})
                    all_streams+=delta  # Append each stream response to the list

                await manager.send_json(ws, {"done": True})
            else:
                # ---------- ONE-SHOT ----------
                resp = await ollama.chat(
                    model=msg.get("model", MODEL),
                    messages=[msg.get("messages")],
                    stream=False,
                )
                answer = resp["message"]["content"]
                await manager.send_json(ws, {"response": answer})

            latency = (datetime.datetime.now() - time_start).total_seconds() * 1000

            log.info("Prompt processed for client %s by ollama with latency %s", ws.client.host, latency)
        except Exception as exc:
            log.exception("Error while processing prompt for client %s: %s", ws.client.host, exc)
            await manager.send_json(ws, {"error": str(exc)})
    except WebSocketDisconnect:
        log.warning("Client %s disconnected from ollama endpoint", ws.client.host)
        manager.disconnect(ws)


@app.websocket('/claude2')
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    log.info("Client %s connected into claude2 endpoint for generation", ws.client.host)
    try:
        msg = await ws.receive_json()
        messages=msg.get("messages")
        prompt = messages[-1]["content"] if messages else "Hello!"
        stream = msg.get("stream", True) 
        if stream:
            # Mock streaming response (simulate Claude's style)
            mock_response = (
               f"You asked: '{prompt[:30]}...'.\n\n"
                "⚠️ This is a **mocked claude2 response** (no  key configured).\n"
                 "We will be establishing it shortly.\n"
            )
            for char in mock_response:
                await manager.send_json(ws, {"token": char})
                await asyncio.sleep(0.01)  # Simulate network delay
            await manager.send_json(ws, {"token": None})
        
        else:
            mock_response = f"[MOCK] Claude-2 response to: {prompt}"
            await manager.send_json(ws, {"response": mock_response})
        log.info("Prompt processed for client by claude for ip %s", ws.client.host)
    except WebSocketDisconnect:
        log.warning("Client %s disconnected from claude2 endpoint", ws.client.host)
        manager.disconnect(ws)
    except Exception as e:
        log.exception("Claude  error: %s", e)
        await manager.send_json(ws, {"error": "Mock Claude error"})



@app.websocket('/gpt4')
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    log.info("Client %s connected into gpt4 endpoint for generation", ws.client.host)
    try:
        msg = await ws.receive_json()
        stream = msg.get("stream", True)
        messages = msg.get("messages", [])
        prompt = messages[-1]["content"] if messages else "Hello!"

        if stream:
            # Mock GPT-4 style response
            mock_response = (
               f"You asked: '{prompt[:30]}...'.\n\n"
                "⚠️ This is a **mocked gpt4 response** (no key configured).\n"
                "We will be establishing it shortly.\n"
            )
            for char in mock_response:
                await manager.send_json(ws, {"token": char})
                await asyncio.sleep(0.01)
            await manager.send_json(ws, {"token": None})

        else:
            mock_response = f"[MOCK] GPT-4 response to: {prompt}"
            await manager.send_json(ws, {"response": mock_response})
        log.info("Prompt processed for client by claude for ip %s", ws.client.host)
    except WebSocketDisconnect:
        manager.disconnect(ws)
        log.warning("Client %s disconnected from gpt4 endpoint", ws.client.host)
    except Exception as e:
        log.exception("GPT-4 mock error: %s", e)
        await manager.send_json(ws, {"error": "Mock GPT-4 error"})


@app.websocket('/vllm')
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    log.info("Client %s connected into vllm endpoint for generation", ws.client.host)
    try:
        msg = await ws.receive_json()
        stream = msg.get("stream", True)
        messages = msg.get("messages", [])
        prompt = messages[-1]["content"] if messages else "Hello!"

        if stream:
            # Mock GPT-4 style response
            mock_response = (
                f"You asked: '{prompt[:30]}...'.\n\n"
                "⚠️ This is a **mocked VLLM response** (no  key configured).\n"
                "We will be establishing it shortly.\n"
            )
            for char in mock_response:
                await manager.send_json(ws, {"token": char})
                await asyncio.sleep(0.01)
            await manager.send_json(ws, {"token": None})
        else:
            mock_response = f"[MOCK] GPT-4 response to: {prompt}"
            await manager.send_json(ws, {"response": mock_response})
        log.info("Prompt processed for client by vllm for ip %s", ws.client.host)
    except WebSocketDisconnect:
        manager.disconnect(ws)
        log.warning("Client %s disconnected from vllm endpoint", ws.client.host)
    except Exception as e:
        log.exception("vllm mock error: %s", e)
        await manager.send_json(ws, {"error": "Mock GPT-4 error"})
@app.get("/")
async def health():
    return "FastAPI Llama-3.2 WebSocket server is running."


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("modelserv:app", host=HOST, port=PORT, log_level="info")