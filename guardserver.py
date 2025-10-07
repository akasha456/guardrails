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
from guardrails import Guard, OnFailAction
from guardrails.hub import ToxicLanguage, ProfanityFree, DetectPII
import spacy
from logging_config import setup_logging, get_guardrails_logger
from router_agent import router

# ---------- Email Configuration ----------
ADMIN_EMAIL = "akashpr715@gmail.com"     # where alerts go
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USERNAME = "akashanil456@gmail.com"       # sender Gmail address
SMTP_PASSWORD = "llmfsasvixvilqct"     # app password, not normal Gmail password

# ---------- Email Helper ----------
def send_violation_email(subject: str, body: str, recipient: str = ADMIN_EMAIL):
    msg = MIMEMultipart()
    msg["From"] = SMTP_USERNAME
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"📧 Email sent to {recipient}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")


# ---------- NLP + Guard Setup ----------
nlp = spacy.load("en_core_web_sm")

setup_logging()
log = get_guardrails_logger()

guard_output_complete = (
    Guard()
    .use(ToxicLanguage, threshold=0.5, validation_method="sentence", on_fail=OnFailAction.EXCEPTION)
    .use(ProfanityFree, on_fail="exception")
)

guard_input = (
    Guard()
    .use(ToxicLanguage, threshold=0.5, validation_method="sentence", on_fail=OnFailAction.EXCEPTION)
    .use(DetectPII, entities=["EMAIL_ADDRESS", "PHONE_NUMBER"], on_fail="exception")
    .use(ProfanityFree, on_fail="exception")
)

MAX_BUFFER_CHARS = 200
MAX_WAIT_SECONDS = 3
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="Validator")


# ---------- Sentence Assembly ----------
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
    log.info(f"[VALIDATION START] Seq={seq} | Complete={is_complete} | Chunk: {repr(text[:50])}...")
    try:
        if is_complete:
            guard_output_complete.validate(text, on="output")
        duration = time.time() - start
        log.info(f"[VALIDATION PASS] Seq={seq} ({duration:.3f}s) by {thread_name}")
        write_queue.put(("valid", seq, text, recv_time))
        return True
    except Exception as e:
        duration = time.time() - start
        log.error(f"[VALIDATION FAIL] Seq={seq} ({duration:.3f}s) by {thread_name} → {str(e)}")

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
        if item is None:
            safe_send({"token": None})
            break
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


async def stream_producer(payload: dict, url: str, raw_token_queue: asyncio.Queue):
    log.info("🚀 Connecting to model server...")
    try:
        async with ws_client.connect(url) as model_ws:
            await model_ws.send(json.dumps(payload))
            log.info("📤 Prompt sent")
            async for msg in model_ws:
                data = json.loads(msg)
                if "token" in data:
                    token = data["token"]
                    if token is None:
                        await raw_token_queue.put(None)
                        log.info("🔚 End of stream")
                        return
                    await raw_token_queue.put(token)
                elif "error" in data:
                    log.error(f"💥 Model error: {data['error']}")
                    await raw_token_queue.put(None)
                    return
            await raw_token_queue.put(None)
    except Exception as e:
        log.exception(f"🔥 Stream error: {str(e)}")
        await raw_token_queue.put(None)


# ---------- FASTAPI APP ----------
app = FastAPI()

@app.websocket("/guard")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    client = ws.client.host
    log.info("Client %s connected into guardserver endpoint for generation.", client)
    try:
        data = await ws.receive_json()
        prompt = data.get("prompt", "")
        username = data.get("username", "")
        model = data.get("model", "")
        guard_type = data.get("guard", "")
        meta = {
            "username": username,
            "model": model,
            "guard": guard_type,
            "prompt": prompt,
            "ip": client,
            "timestamp": time.time(),
        }

        if not prompt:
            await ws.send_json({"error": "Prompt is required"})
            log.error("❌ Missing prompt for %s (%s)", username, client)
            return

        log.info(f"📥 Prompt from {username}({client}): {repr(prompt)}")

        # Input Guard
        try:
            guard_input.validate(prompt, on="input")
            log.info("✅ Input guard passed")
        except Exception as e:
            log.error(f"❌ Input validation failed: {str(e)}")
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
            await ws.send_json({"error": "Input validation failed"})
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
        await stream_producer(model_payload, url, raw_token_queue)

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
            await ws.send_json({"error": f"Server error: {str(exc)}"})
        except:
            pass


@app.get("/")
async def health():
    return "WebSocket Guardrails Server is running 🚀"


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("temp:app", host="0.0.0.0", port=5000, log_level="info")
