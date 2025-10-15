import asyncio
import json
import logging
import time
import threading
import queue
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import websockets as ws_client
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import spacy
import aiohttp
from logging_config import setup_logging, get_guardrails_logger
from router_agent import router
from dotenv import load_dotenv
import os
import requests
load_dotenv()
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL")
# ---------- Email Helper (SendGrid API) ----------
def send_violation_email(subject: str, body: str, recipient: str = ADMIN_EMAIL):
    url = "https://api.sendgrid.com/v3/mail/send"
    headers = {
        "Authorization": f"Bearer {SENDGRID_API_KEY}",  # ← SPACE after 'Bearer'
        "Content-Type": "application/json"
    }
    data = {
        "personalizations": [{"to": [{"email": recipient}]}],
        "from": {"email": SENDGRID_FROM_EMAIL},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body.strip()}]
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        log.info(f"📤 SendGrid API request sent. Status: {response.status_code}")
        if response.status_code == 202:
            log.info(f"✅ Email accepted by SendGrid for {recipient}")
        else:
            log.error(f"❌ SendGrid API error {response.status_code}: {response.text}")
            # Log full request for debugging (temporarily)
            log.debug(f"Request payload: {json.dumps(data, indent=2)}")
    except requests.exceptions.Timeout:
        log.error("❌ SendGrid request timed out")
    except requests.exceptions.RequestException as e:
        log.exception(f"❌ Network error sending email: {e}")
    except Exception as e:
        log.exception(f"❌ Unexpected error in send_violation_email: {e}")


OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama-guard3"
 
class LlamaGuardException(Exception):
    pass
 
async def _ask_llamaguard(text: str, role: str) -> None:
    prompt = f"<|start_header_id|>{role}<|end_header_id|>\n\n{text}<|eot_id|>"
    payload = {"model": MODEL, "prompt": prompt, "stream": False, "options": {"temperature": 0}}
    async with aiohttp.ClientSession() as session:
        async with session.post(OLLAMA_URL, json=payload) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Ollama HTTP {resp.status}")
            body = await resp.json()
            answer: str = body["response"].strip().lower()
    if answer.startswith("unsafe"):
        category = answer.replace("unsafe", "").strip(" ,.")
        raise LlamaGuardException(f"Llama-Guard-3 flagged {role} content: {category}")
    if not answer.startswith("safe"):
        raise LlamaGuardException(f"Unparsable Llama-Guard-3 answer: {body['response']}")
 
async def validate_input(text: str) -> None:
    await _ask_llamaguard(text, "User")
 
async def validate_output(text: str) -> None:
    await _ask_llamaguard(text, "Agent")
 
 
# ---------- NLP + Guard Setup ----------
nlp = spacy.load("en_core_web_sm")
 
setup_logging()
log = get_guardrails_logger()
MAX_BUFFER_CHARS = 200
MAX_WAIT_SECONDS = 3
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="Validator")
 
 
 
def extract_complete_sentences_spacy(raw_text: str):
    if not raw_text.strip():
        return "", raw_text
    doc = nlp(raw_text)
    sentences = list(doc.sents)
    if not sentences:
        return "", raw_text
    complete_end = 0
    for sent in sentences:
        stripped = sent.text.rstrip()
        if stripped and stripped[-1] in ".!?":
            complete_end = sent.end_char
        else:
            break
    if complete_end > 0:
        return raw_text[:complete_end], raw_text[complete_end:]
    return "", raw_text
 
 
async def assemble_sentences(raw_token_queue, chunk_queue):
    raw_buffer = ""
    last_token_time = time.time()
    chunk_seq = 0
    while True:
        try:
            token = await asyncio.wait_for(raw_token_queue.get(), timeout=2.0)
            if token is None:
                if raw_buffer.strip():
                    await chunk_queue.put((chunk_seq, raw_buffer, time.time(), False))
                    chunk_seq += 1
                await chunk_queue.put(None)
                return
            raw_buffer += token
            last_token_time = time.time()
            complete, remaining = extract_complete_sentences_spacy(raw_buffer)
            if complete:
                await chunk_queue.put((chunk_seq, complete, time.time(), True))
                chunk_seq += 1
                raw_buffer = remaining
            else:
                now = time.time()
                should_flush = (
                    (now - last_token_time >= MAX_WAIT_SECONDS)
                    or (len(raw_buffer) >= MAX_BUFFER_CHARS)
                )
                if should_flush and raw_buffer.strip():
                    await chunk_queue.put((chunk_seq, raw_buffer, now, False))
                    chunk_seq += 1
                    raw_buffer = ""
                    last_token_time = now
        except asyncio.TimeoutError:
            if raw_buffer.strip():
                await chunk_queue.put((chunk_seq, raw_buffer, time.time(), False))
                chunk_seq += 1
                raw_buffer = ""
 
 
async def dispatch_validations(chunk_queue, write_queue):
    loop = asyncio.get_event_loop()
    pending = set()
    while True:
        item = await chunk_queue.get()
        if item is None:
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            write_queue.put(None)
            break
        seq, text, recv_time, is_complete = item
        task = loop.run_in_executor(
            executor, validate_chunk_sync, seq, text, recv_time, is_complete, write_queue
        )
        pending.add(task)
        if len(pending) > 4:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
 
 
def validate_chunk_sync(seq: int, text: str, recv_time: float, is_complete: bool, write_queue: queue.Queue):
    thread_name = threading.current_thread().name
    start = time.time()
    try:
        if is_complete:
            pass
        duration = time.time() - start
        write_queue.put(("valid", seq, text, recv_time))
        return True
    except Exception as e:
        duration = time.time() - start
 
        # 🚨 Send Email Alert
        subject = "🚨 Guardrails Output Violation Detected"
        body = f"""
        Violation detected in OUTPUT guard:
        Sequence: {seq}
        Thread: {thread_name}
        Text: {text[:200]}...
        Error: {str(e)}
        Timestamp: {time.ctime()}
        """
        send_violation_email(subject, body)
 
        write_queue.put(("fail", seq, text, recv_time))
        return False
 
 
def websocket_writer(write_queue: queue.Queue, ws: WebSocket, main_loop):
    expected_seq = 0
    pending = {}
 
    def safe_send(data):
        asyncio.run_coroutine_threadsafe(ws.send_json(data), main_loop)
 
    while True:
        item = write_queue.get()
        if "token" in item:
            if item.get("token", False) is None:
                if "flag" in item:
                    if item.get("flag", False) is True:
                        safe_send(item)
                        break
                safe_send({"token": item["token"]})
                expected_seq += 1
        status, seq, text, ts = item
        if status == "fail":
            log.error("❌ Validation failed → aborting stream")
            safe_send({"error": "Guard validation failed on output"})
            while not write_queue.empty():
                try:
                    write_queue.get_nowait()
                except queue.Empty:
                    pass
            break
        if seq == expected_seq:
            safe_send({"token": text})
            expected_seq += 1
            while expected_seq in pending:
                txt, _ = pending.pop(expected_seq)
                safe_send({"token": txt})
                expected_seq += 1
        else:
            pending[seq] = (text, ts)
        write_queue.task_done()
 
 
async def stream_producer(payload: dict, url: str, raw_token_queue: asyncio.Queue, write_queue: asyncio.Queue):
    log.info("🚀 Connecting to model server...")
    try:
        async with ws_client.connect(url) as model_ws:
            await model_ws.send(json.dumps(payload))
            log.info("📤 Prompt sent")
            async for msg in model_ws:
                data = json.loads(msg)
                if "token" in data:
                    if data["token"] is None and data.get("flag", False):
                        write_queue.put(data)
                        log.info("🔚 End of stream")
                        return
                    token = data["token"]
                    await raw_token_queue.put(token)
                elif "error" in data:
                    log.error(f"💥 Model error: {data['error']}")
                    write_queue.put(data)
                    return
            await raw_token_queue.put(None)
    except Exception as e:
        log.exception(f"🔥 Stream error: {str(e)}")
        data={"error": str(e),
              "flag": "stream error flag"}
        write_queue.put(data)
 
 
# ---------- FASTAPI APP ----------
app = FastAPI()
 
@app.websocket("/guard")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        data = await ws.receive_json()
        prompt = data.get("prompt", "")
        username = data.get("username", "")
        model = data.get("model", "")
        guard_type = data.get("guard", "")
        client = data.get("ip", ws.client.host)
        meta = {
            "username": username,
            "model": model,
            "guard": guard_type,
            "prompt": prompt,
            "ip": client,
            "timestamp": time.time(),
        }
        log.info("Client %s connected into guardserver endpoint for generation.", client)
        if not prompt:
            await ws.send_json({"error": "Prompt is required"})
            log.error("❌ Missing prompt for %s (%s)", username, client)
            return
 
        log.info(f"📥 Prompt from {username}({client}): {repr(prompt)}")
 
        # Input Guard
        try:
            await validate_input(prompt)
            log.info("✅ Input guard passed for prompt from %s (%s)", username, client)
        except Exception as e:
            log.error(f"❌ Input validation failed for client {username}({client}) for prompt {prompt}: {str(e)}")
            subject = "🚨 Guardrails Input Violation Detected"
            body = f"""
            Violation detected in INPUT guard:
            Username: {username}
            IP: {client}
            Model: {model}
            Guard Type: {guard_type}
            Prompt: {prompt}
            Error: {str(e)}
            Timestamp: {time.ctime()}
            """

            send_violation_email(subject, body)
            
            await ws.send_json({"error": "Validation Failed",
                                "flag": "input"})
            return
 
        # Start Routing
        url, model_payload = router(meta)
        raw_token_queue = asyncio.Queue()
        chunk_queue = asyncio.Queue()
        write_queue = queue.Queue()
        main_loop = asyncio.get_running_loop()
 
        writer_thread = threading.Thread(
            target=websocket_writer,
            args=(write_queue, ws, main_loop),
            name="WebSocketWriter",
            daemon=True,
        )
        writer_thread.start()
 
        assembler_task = asyncio.create_task(assemble_sentences(raw_token_queue, chunk_queue))
        dispatcher_task = asyncio.create_task(dispatch_validations(chunk_queue, write_queue))
        await stream_producer(model_payload, url, raw_token_queue, write_queue)
 
        await assembler_task
        await dispatcher_task
        writer_thread.join(timeout=5)
        if writer_thread.is_alive():
            log.warning("⚠️ Writer thread did not terminate cleanly for client %s", client)
        else:
            log.info("✅ Streaming completed for client %s", client)
 
    except WebSocketDisconnect:
        log.info("Client %s disconnected", client)
    except Exception as exc:
        log.exception("Error in WebSocket handler for %s: %s", client, str(exc))
        try:
            await ws.send_json({"error": f"Server error: {str(exc)}",
                                "flag": "server"})
        except:
            pass
@app.get("/")
async def health():
    return "WebSocket Guardrails Server is running 🚀"
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("guardserver:app", host="0.0.0.0", port=5000, log_level="info")