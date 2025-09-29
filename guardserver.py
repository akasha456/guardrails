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

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("guardserver")

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
                token = data["token"]
                if token is None:               # EOS sentinel
                    await ui_ws.send_json({"token": None})
                    return full_text

                candidate = full_text + token

                # ----- output guard on incremental text -----
                try:
                    guard.validate(candidate, on="output")
                except Exception as guard_exc:
                    await ui_ws.send_json({"error": f"Output guard: {guard_exc}"})
                    return None          # abort

                # guard passed → forward token & commit
                full_text = candidate
                await ui_ws.send_json({"token": token})

            elif "error" in data:
                raise RuntimeError(data["error"])
# ---------- WebSocket endpoint ----------
# ---------- WebSocket endpoint ----------
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    client = ws.client.host
    log.info("Client %s connected", client)
    try:
        data = await ws.receive_json()
        prompt = data.get("prompt", "")
        log.info("Prompt (%d chars) from %s", len(prompt), client)

        # 1. input guard
        guard.validate(prompt, on="input")

        # 2. guarded streaming (aborts on first output failure)
        await guarded_stream(prompt, ws)     # <-- changed

    except WebSocketDisconnect:
        log.info("Client %s disconnected", client)
    except Exception as exc:
        log.exception("Guard error")
        await ws.send_json({"error": str(exc)})
# ---------- health ----------
@app.get("/")
def health():
    return "Guard-server is running"

# ---------- run ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("guardserver:app", host="0.0.0.0", port=5000, log_level="info")