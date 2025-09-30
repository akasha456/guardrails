import asyncio
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from guardrails import Guard, OnFailAction
from guardrails.hub import ToxicLanguage, ProfanityFree, GuardrailsPII
import websockets  # only used as client to model server
from logging_config import setup_logging, get_guardrails_logger

setup_logging()
guardrails_logger = get_guardrails_logger()
log = logging.getLogger("guardrails")

app = FastAPI()

guard = (
    Guard()
    .use(ToxicLanguage, threshold=0.5, validation_method="sentence", on_fail=OnFailAction.EXCEPTION)
    .use(GuardrailsPII(entities=["EMAIL_ADDRESS", "PHONE_NUMBER"], on_fail=OnFailAction.EXCEPTION))
    .use(ProfanityFree, on_fail="exception")
)


executor = ThreadPoolExecutor(max_workers=4)
MODEL_WS_URL = "ws://localhost:8765/ws"
CHUNK_WORD_COUNT = 6

def _sync_validate_output(text: str):
    """Synchronous guard validation — runs in thread pool."""
    guard.validate(text, on="output")


async def validate_and_send_chunk(text: str, ui_ws: WebSocket) -> bool:
    """Validate a text chunk in a thread and send to UI if valid."""
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(executor, _sync_validate_output, text)
        await ui_ws.send_json({"token": text})
        return True
    except Exception as guard_exc:
        error_msg = f"Output guard: {guard_exc}"
        log.error("Output guard failed on chunk: %s → %s", text[:50], error_msg)
        await ui_ws.send_json({"error": error_msg})
        return False
    
async def guarded_stream(prompt: str, ui_ws: WebSocket) -> str | None:
    full_text = ""
    raw_buffer = ""  # ← Accumulates EXACT tokens (with spaces, punct, etc.)
    try:
        async with websockets.connect(MODEL_WS_URL) as model_ws:
            await model_ws.send(json.dumps({"prompt": prompt, "stream": True}))
            log.info("Connected to model server for streaming for client %s", ui_ws.client.host)

            async for msg in model_ws:
                data = json.loads(msg)
                if "token" in data:
                    token = data["token"]
                    if token is None:
                        # End of stream: flush remaining raw_buffer
                        if raw_buffer.strip():
                            if not await validate_and_send_chunk(raw_buffer, ui_ws):
                                return None
                        await ui_ws.send_json({"token": None})
                        return full_text

                    # Append EXACT token to both full_text and raw_buffer
                    full_text += token
                    raw_buffer += token

                    # Count words in raw_buffer (ignoring non-word chars)
                    words = re.findall(r'\b\w+\b', raw_buffer)
                    word_count = len(words)

                    if word_count >= CHUNK_WORD_COUNT:
                        match_iter = re.finditer(r'\b\w+\b', raw_buffer)
                        end_pos = 0
                        word_index = 0
                        for match in match_iter:
                            word_index += 1
                            if word_index == CHUNK_WORD_COUNT:
                                end_pos = match.end()  # End of Nth word
                                break

                        if end_pos > 0:
                            chunk_to_validate = raw_buffer[:end_pos]
                            remaining = raw_buffer[end_pos:]

                            # Validate and send the EXACT chunk
                            if not await validate_and_send_chunk(chunk_to_validate, ui_ws):
                                log.info("Aborting stream due to guard failure on chunk for user %s", ui_ws.client.host)
                                return None
                            raw_buffer = remaining
                        else:
                            pass
                elif "error" in data:
                    log.error("Error from model-server: %s for user %s", data["error"], ui_ws.client.host)
                    await ui_ws.send_json({"error": f"Model error: {data['error']}"})
                    return None
    except Exception as e:
        log.exception("Exception in guarded_stream for user %s", ui_ws.client.host)
        await ui_ws.send_json({"error": "Internal error in guard server"})
        return None
    return full_text

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    client = ws.client.host
    log.info("Client %s connected into guardrails server", client)
    try:
        data = await ws.receive_json()
        prompt = data.get("prompt", "")

        log.info("Prompt (%d chars) from %s as prompt %s", len(prompt), client, prompt[:40])
        
        guard.validate(prompt, on="input")
        log.info("Input guard passed for client %s with prompt %s", client, prompt[:40])

        await guarded_stream(prompt, ws)
        log.info("Output and Input Guard processed for client %s with prompt %s", client, prompt[:40])
    except WebSocketDisconnect:
        log.info("Client %s disconnected from guardrails server", client)
    except Exception as exc:
        log.exception("Guard error for client %s: %s for prompt %s", client, exc, prompt[:40])
        await ws.send_json({"error": str(exc)})

async def guarded_full_response(prompt: str, ws: WebSocket) -> None:
    """
    Legacy one-shot mode (kept for compatibility).
    Fetch full response, validate once, send.
    """
    async with websockets.connect(MODEL_WS_URL) as model_ws:
        await model_ws.send(json.dumps({"prompt": prompt, "stream": False}))
        msg = await model_ws.recv()
        data = json.loads(msg)

    if "error" in data:
        raise RuntimeError(data["error"])

    answer = data["response"]
    guard.validate(answer, on="output")
    await ws.send_json({"response": answer})
@app.get("/")
def health():
    return "Guard-server is running"


# ---------- run ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("guardserver:app", host="0.0.0.0", port=5000, log_level="info")