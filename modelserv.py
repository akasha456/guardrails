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
from openai import OpenAI
from dotenv import load_dotenv
import os
from openai import AsyncOpenAI  # Use AsyncOpenAI for async endpoints
load_dotenv()


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is missing in .env")

# Correct client for GPT-4 (via OpenAI, not OpenRouter, unless intended)
openai_client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    base_url="https://api.openai.com/v1"  # Default; can omit
)

# KIMI_API_KEY = os.getenv("MOONSHOT_API_KEY")
# if not KIMI_API_KEY:
#     raise ValueError("MOONSHOT_API_KEY is missing in .env")

# kimi_client = OpenAI(
#     api_key=KIMI_API_KEY,
#     base_url="https://openrouter.ai/api/v1",  # ✅ Correct base URL (note: moonshot.cn, not .ai)
# )


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
            else:
                # ---------- ONE-SHOT ----------
                resp = await ollama.chat(
                    model=msg.get("model", MODEL),
                    messages=[msg.get("messages")],
                    stream=False,
                )
                answer = resp["message"]["content"]
                await manager.send_json(ws, {"response": answer})
            await manager.send_json(ws, {"token": None, "flag": True})
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
            await manager.send_json(ws, {"token": None, "flag": True})
        
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



# @app.websocket('/gpt4')
# async def websocket_endpoint(ws: WebSocket):
#     await manager.connect(ws)
#     log.info("Client %s connected into gpt4 endpoint for generation", ws.client.host)
#     try:
#         msg = await ws.receive_json()
#         stream = msg.get("stream", True)
#         messages = msg.get("messages", [])
#         prompt = messages[-1]["content"] if messages else "Hello!"

#         if stream:
#             # Mock GPT-4 style response
#             mock_response = (
#                f"You asked: '{prompt[:30]}...'.\n\n"
#                 "⚠️ This is a **mocked gpt4 response** (no key configured).\n"
#                 "We will be establishing it shortly.\n"
#             )
#             for char in mock_response:
#                 await manager.send_json(ws, {"token": char})
#                 await asyncio.sleep(0.01)
#             await manager.send_json(ws, {"token": None, "flag": True})

#         else:
#             mock_response = f"[MOCK] GPT-4 response to: {prompt}"
#             await manager.send_json(ws, {"response": mock_response})
#         log.info("Prompt processed for client by claude for ip %s", ws.client.host)
#     except WebSocketDisconnect:
#         manager.disconnect(ws)
#         log.warning("Client %s disconnected from gpt4 endpoint", ws.client.host)
#     except Exception as e:
#         log.exception("GPT-4 mock error: %s", e)
#         await manager.send_json(ws, {"error": "Mock GPT-4 error"})

@app.websocket("/gpt4")
async def websocket_endpoint_gpt4(ws: WebSocket):
    conn_id = await manager.connect(ws)
    client_host = ws.client.host
    log.info("Client %s connected (Id: %s) to GPT-4 endpoint", client_host, conn_id)
    time_start = datetime.datetime.now()
    
    try:
        msg = await ws.receive_json()
        model = msg.get("model", "gpt-4-turbo")  # or "gpt-4", "gpt-4o", etc.
        messages = msg.get("messages")
        stream = msg.get("stream", True)

        if not messages:
            await manager.send_json(conn_id, {"error": "Missing 'messages' in payload"})
            return

        if stream:
            try:
                # Use async streaming with OpenAI
                stream_response = await openai_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    stream=True,
                    temperature=0.7
                )

                async for chunk in stream_response:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        await manager.send_json(conn_id, {"token": delta.content})

                await manager.send_json(conn_id, {"token": None, "flag": True})

            except Exception as e:
                log.exception("GPT-4 streaming error for client %s: %s", client_host, e)
                await manager.send_json(conn_id, {"error": f"GPT-4 streaming failed: {str(e)}"})

        else:
            try:
                response = await openai_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    stream=False,
                    temperature=0.7
                )
                answer = response.choices[0].message.content
                await manager.send_json(conn_id, {"response": answer})

            except Exception as e:
                log.exception("GPT-4 non-streaming error for client %s: %s", client_host, e)
                await manager.send_json(conn_id, {"error": f"GPT-4 request failed: {str(e)}"})

        latency = (datetime.datetime.now() - time_start).total_seconds() * 1000
        log.info("Prompt processed for client %s by GPT-4 with latency %.2f ms", client_host, latency)

    except WebSocketDisconnect:
        log.warning("Client %s disconnected from GPT-4 endpoint", client_host)
    except Exception as exc:
        log.exception("Unexpected error in GPT-4 WebSocket handler for %s: %s", client_host, exc)
        try:
            await manager.send_json(conn_id, {"error": f"Server error: {str(exc)}"})
        except:
            pass
    finally:
        manager.disconnect(conn_id, ws)
        log.info("Client %s disconnected from GPT-4 endpoint", client_host)



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
            await manager.send_json(ws, {"token": None, "flag": True})
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
# @app.websocket("/kimi")
# async def websocket_endpoint_kimi(ws: WebSocket):
#     conn_id = await manager.connect(ws)
#     client_host = ws.client.host
#     log.info("Client %s connected (Id: %s) into kimi endpoint for generation", client_host, conn_id)
#     time_start = datetime.datetime.now()
#     try:
#         msg = await ws.receive_json()
#         model = msg.get("model", "kimi-k2-0905-preview")  # Default Kimi model
#         messages = msg.get("messages")
#         stream = msg.get("stream", True)

#         if not messages:
#             await manager.send_json(conn_id, {"error": "Missing 'messages' in payload"})
#             return

#         if stream:
#             # ---------- STREAMING MODE ----------
#             try:
#                 response = kimi_client.chat.completions.create(
#                     model=model,
#                     messages=messages,
#                     stream=True,
#                     temperature=0.7
#                 )

#                 async def stream_generator():
#                     for chunk in response:
#                         delta = chunk.choices[0].delta
#                         if delta.content:
#                             yield delta.content

#                 # Stream tokens one by one
#                 async for token in stream_generator():
#                     await manager.send_json(conn_id, {"token": token})

#                 await manager.send_json(conn_id, {"token": None, "flag": True})
                
#             except Exception as e:
#                 log.exception("Kimi streaming error for client %s: %s", client_host, e)
#                 await manager.send_json(conn_id, {"error": f"Kimi streaming failed: {str(e)}"})

#         else:
#             # ---------- NON-STREAMING (ONE-SHOT) MODE ----------
#             try:
#                 response = kimi_client.chat.completions.create(
#                     model=model,
#                     messages=messages,
#                     stream=False,
#                     temperature=0.7
#                 )
#                 answer = response.choices[0].message.content
#                 await manager.send_json(conn_id, {"response": answer})

#             except Exception as e:
#                 log.exception("Kimi non-streaming error for client %s: %s", client_host, e)
#                 await manager.send_json(conn_id, {"error": f"Kimi request failed: {str(e)}"})

#         latency = (datetime.datetime.now() - time_start).total_seconds() * 1000
#         log.info("Prompt processed for client %s by kimi with latency %.2f ms", client_host, latency)
#         manager.disconnect(conn_id,ws)
#         log.warning("Client %s disconnected from ollama endpoint after generation", ws.client.host)
#     except WebSocketDisconnect:
#         log.warning("Client %s disconnected from kimi endpoint", client_host)
#         manager.disconnect(conn_id, ws)
#     except Exception as exc:
#         log.exception("Unexpected error in kimi WebSocket handler for %s: %s", client_host, exc)
#         try:
#             await manager.send_json(conn_id, {"error": f"Server error: {str(exc)}"})
#         except:
#             pass
@app.get("/")
async def health():
    return "FastAPI Llama-3.2 WebSocket server is running."


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("modelserv:app", host=HOST, port=PORT, log_level="info")