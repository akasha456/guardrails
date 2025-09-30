#!/usr/bin/env python3
"""
Guard-server – FastAPI WebSocket (port 5000)
Receives  {"prompt": "..."}  →  guard  →  forward to model-server
Replies   {"token": "..."}  or  {"error": "..."}
"""
import asyncio, json, logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from guardrails import Guard, OnFailAction
from guardrails.hub import ToxicLanguage, ProfanityFree, GuardrailsPII
import websockets   # only used as client to model server
from logging_config import setup_logging, get_guardrails_logger
setup_logging()

guardrails_logger= get_guardrails_logger()
log=logging.getLogger("guardrails")

# ------------------ FastAPI app ------------------
app = FastAPI()

# ------------------ guardrails ------------------
guard = (
    Guard()
    .use(ToxicLanguage, threshold=0.5, validation_method="sentence", on_fail=OnFailAction.EXCEPTION)
    .use(GuardrailsPII(entities=["EMAIL_ADDRESS", "PHONE_NUMBER"], on_fail=OnFailAction.EXCEPTION))
    .use(ProfanityFree, on_fail="exception")
)

MODEL_WS_URL = "ws://localhost:8765/ws"   # model-server

# ---------- helper: stream from model ----------
# ---------- helper: GUARDED stream ----------
async def guarded_stream(prompt: str, ui_ws: WebSocket) -> str | None:
    """
    Stream tokens from model-server → validate *incremental* text
    (output guard).  On first failure send {"error": ...} and abort.
    Returns the final text or None if aborted.
    """
    full_text = ""
    async with websockets.connect(MODEL_WS_URL) as model_ws:
        await model_ws.send(json.dumps({"prompt": prompt}))

        async for msg in model_ws:
            data = json.loads(msg)

            if "token" in data:
                log.info("Received token from model-server: %s for prompt %s ", data["token"], prompt[:40])
                token = data["token"]
                if token is None:               # EOS sentinel
                    await ui_ws.send_json({"token": None})
                    return full_text

                candidate = full_text + token

                # ----- output guard on incremental text -----
                try:
                    guard.validate(candidate, on="output")
                    log.info("Output guard passed for candidate %s", candidate[:40])
                except Exception as guard_exc:
                    log.error("Output guard failed: %s for candidate %s", guard_exc, candidate[:40])
                    await ui_ws.send_json({"error": f"Output guard: {guard_exc}"})
                    return None          # abort

                # guard passed → forward token & commit
                full_text = candidate
                log.info("Forwarding token to client: %s", token)
                await ui_ws.send_json({"token": token})

            elif "error" in data:
                log.error("Error from model-server: %s", data["error"])
                raise RuntimeError(data["error"])
# ---------- WebSocket endpoint ----------
# ---------- WebSocket endpoint ----------
# ----------  inside your guardrails server  ----------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    client = ws.client.host
    log.info("Client %s connected into guardrails server", client)
    try:
        data = await ws.receive_json()
        prompt = data.get("prompt", "")
        log.info("Prompt (%d chars) from %s as prompt %s", len(prompt), client, prompt[:40])

        # 1. input guard
        guard.validate(prompt, on="input")
        log.info("Input guard passed for client %s with prompt %s", client, prompt[:40])

        # 2. guarded *full* response (no streaming)
        await guarded_full_response(prompt, ws)          # <-- changed

    except WebSocketDisconnect:
        log.info("Client %s disconnected", client)
    except Exception as exc:
        log.exception("Guard error for client %s: %s for prompt %s", client, exc, prompt[:40])
        await ws.send_json({"error": str(exc)})


async def guarded_full_response(prompt: str, ws: WebSocket) -> None:
    """
    Ask model-server for the *entire* answer (no streaming),
    validate it, then ship it in one WebSocket message.
    """
    # 1. fetch complete reply from model-server
    async with websockets.connect(MODEL_WS_URL) as model_ws:
        await model_ws.send(json.dumps({"prompt": prompt, "stream": False}))
        msg = await model_ws.recv()
        data = json.loads(msg)

    if "error" in data:                       # model-server reported failure
        raise RuntimeError(data["error"])

    answer = data["response"]                 # whole string in one key

    # 2. output guard
    guard.validate(answer, on="output")

    # 3. one-shot delivery to UI
    await ws.send_json({"response": answer})
# ---------- health ----------
@app.get("/")
def health():
    return "Guard-server is running"

# ---------- run ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("guardserver:app", host="0.0.0.0", port=5000, log_level="info")