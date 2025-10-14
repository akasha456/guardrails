#!/usr/bin/env python3
"""
FastAPI WebSocket server that exposes Llama-3.2 (Ollama) to remote clients.
"""
import uuid
import datetime
import asyncio
import logging
import time
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
        conn_id = f"{ws.client.host}-{time.time()}"
        self.active[conn_id] = ws
        log.warning("Client %s connected with id %s", ws.client.host, conn_id)
        return conn_id

    def disconnect(self, conn_id: str, ws: WebSocket):
        self.active.pop(conn_id, None)
        log.warning("Client %s disconnected with id %s", ws.client.host, conn_id)

    async def send_json(self, conn_id: str, data: dict):
        ws=self.active[conn_id]
        if ws:
            try:
                await ws.send_json(data)
            except Exception:
                pass


manager = ConnectionManager()

@app.websocket("/llama3.2")
async def websocket_endpoint(ws: WebSocket):
    conn_id=await manager.connect(ws)
    client_host=ws.client.host
    log.info("Client %s connected(Id: %s) into ollama endpoint for generation", ws.client.host, conn_id)
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
                    await manager.send_json(conn_id, {"token": delta})
                    all_streams+=delta  # Append each stream response to the list

                await manager.send_json(conn_id, {"token": None, "flag": True})
            else:
                # ---------- ONE-SHOT ----------
                resp = await ollama.chat(
                    model=msg.get("model", MODEL),
                    messages=[msg.get("messages")],
                    stream=False,
                )
                answer = resp["message"]["content"]
                await manager.send_json(conn_id, {"response": answer})

            latency = (datetime.datetime.now() - time_start).total_seconds() * 1000

            log.info("Prompt processed for client %s by ollama with latency %s", ws.client.host, latency)
        except Exception as exc:
            log.exception("Error while processing prompt for client %s: %s", ws.client.host, exc)
            await manager.send_json(conn_id, {"error": str(exc), "flag": "model_server"})
    except WebSocketDisconnect:
        log.warning("Client %s disconnected from ollama endpoint", ws.client.host)
        manager.disconnect(conn_id, ws)


@app.websocket('/claude2')
async def websocket_endpoint(ws: WebSocket):
    conn_id=await manager.connect(ws)
    log.info("Client %s connected(Id: %s) into ollama endpoint for generation", ws.client.host, conn_id)
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
                await manager.send_json(conn_id, {"token": char})
                await asyncio.sleep(0.01)  # Simulate network delay
            await manager.send_json(conn_id, {"token": None, "flag": True})
        
        else:
            mock_response = f"[MOCK] Claude-2 response to: {prompt}"
            await manager.send_json(conn_id, {"response": mock_response})
        log.info("Prompt processed for client by claude for ip %s", ws.client.host)
    except WebSocketDisconnect:
        log.warning("Client %s disconnected from claude2 endpoint", ws.client.host)
        manager.disconnect(conn_id,ws)
    except Exception as e:
        log.exception("Claude  error: %s", e)
        await manager.send_json(conn_id, {"error": "Mock Claude error"})



@app.websocket('/gpt4')
async def websocket_endpoint(ws: WebSocket):
    conn_id=await manager.connect(ws)
    log.info("Client %s connected(Id: %s) into ollama endpoint for generation", ws.client.host, conn_id)
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
                await manager.send_json(conn_id, {"token": char})
                await asyncio.sleep(0.01)
            await manager.send_json(conn_id, {"token": None, "flag": True})

        else:
            mock_response = f"[MOCK] GPT-4 response to: {prompt}"
            await manager.send_json(conn_id, {"response": mock_response})
        log.info("Prompt processed for client by claude for ip %s", ws.client.host)
    except WebSocketDisconnect:
        manager.disconnect(conn_id,ws)
        log.warning("Client %s disconnected from gpt4 endpoint", ws.client.host)
    except Exception as e:
        log.exception("GPT-4 mock error: %s", e)
        await manager.send_json(conn_id, {"error": "Mock GPT-4 error"})


@app.websocket('/vllm')
async def websocket_endpoint(ws: WebSocket):
    conn_id=await manager.connect(ws)
    log.info("Client %s connected(Id: %s) into ollama endpoint for generation", ws.client.host, conn_id)
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
                await manager.send_json(conn_id, {"token": char})
                await asyncio.sleep(0.01)
            await manager.send_json(conn_id, {"token": None, "flag": True})
        else:
            mock_response = f"[MOCK] GPT-4 response to: {prompt}"
            await manager.send_json(conn_id, {"response": mock_response})
        log.info("Prompt processed for client by vllm for ip %s", ws.client.host)
    except WebSocketDisconnect:
        manager.disconnect(conn_id,ws)
        log.warning("Client %s disconnected from vllm endpoint", ws.client.host)
    except Exception as e:
        log.exception("vllm mock error: %s", e)
        await manager.send_json(conn_id, {"error": "Mock GPT-4 error"})
@app.get("/")
async def health():
    return "FastAPI Llama-3.2 WebSocket server is running."


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("modelserv:app", host=HOST, port=PORT, log_level="info")