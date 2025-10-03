import asyncio
import json
import logging
import time
import threading
import queue
import websockets as ws_client  # for connecting to model server
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from guardrails import Guard, OnFailAction
from guardrails.hub import ToxicLanguage, ProfanityFree, DetectPII
import nltk
import spacy

# ====== SETUP NLTK ======
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    print("📥 Downloading NLTK 'punkt' tokenizer...")
    nltk.download('punkt', quiet=True)

nlp = spacy.load("en_core_web_sm")

# ====== LOGGING ======
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(threadName)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    filename="cli.log",
    filemode="a"
)
log = logging.getLogger("pipeline")

# ====== GUARDS ======
guard_input = (
    Guard()
    .use(ToxicLanguage, threshold=0.5, validation_method="sentence", on_fail=OnFailAction.EXCEPTION)
    .use(DetectPII, entities=["EMAIL_ADDRESS", "PHONE_NUMBER"], on_fail="exception")
    .use(ProfanityFree, on_fail="exception")
)

guard_output = (
    Guard()
    .use(ToxicLanguage, threshold=0.5, validation_method="sentence", on_fail=OnFailAction.EXCEPTION)
    .use(ProfanityFree, on_fail="exception")
)

# ====== CONFIG ======
MODEL_WS_URL = "ws://localhost:8765/ws"
MAX_BUFFER_CHARS = 200
MAX_WAIT_SECONDS = 3

# Thread pool for validation
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="Validator")

# ====== SENTENCE EXTRACTION ======

def extract_complete_sentences_spacy(raw_text: str):
    doc = nlp(raw_text)
    sentences = list(doc.sents)
    if len(sentences) <= 1:
        return "", raw_text

    # Find last sentence that ends with terminal punctuation
    complete_end = 0
    for sent in sentences:
        if sent.text.rstrip()[-1] in '.!?':
            complete_end = sent.end_char
        else:
            break

    if complete_end:
        return raw_text[:complete_end], raw_text[complete_end:]
    return "", raw_text

# ====== COMPONENTS (will be instantiated per connection) ======

async def assemble_sentences(raw_token_queue, chunk_queue):
    raw_buffer = ""
    last_flush = time.time()
    chunk_seq = 0

    while True:
        try:
            token = await asyncio.wait_for(raw_token_queue.get(), timeout=2.0)
            if token is None:
                if raw_buffer.strip():
                    await chunk_queue.put((chunk_seq, raw_buffer, time.time()))
                    chunk_seq += 1
                await chunk_queue.put(None)
                return

            raw_buffer += token
            now = time.time()

            complete, remaining = extract_complete_sentences(raw_buffer)
            if complete:
                await chunk_queue.put((chunk_seq, complete, now))
                chunk_seq += 1
                raw_buffer = remaining
                last_flush = now
            elif len(raw_buffer) >= MAX_BUFFER_CHARS or (now - last_flush) >= MAX_WAIT_SECONDS:
                await chunk_queue.put((chunk_seq, raw_buffer, now))
                chunk_seq += 1
                raw_buffer = ""
                last_flush = now

        except asyncio.TimeoutError:
            if raw_buffer.strip():
                await chunk_queue.put((chunk_seq, raw_buffer, time.time()))
                chunk_seq += 1
                raw_buffer = ""
            # Continue loop to wait for more tokens or None

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

        seq, text, recv_time = item
        task = loop.run_in_executor(executor, validate_chunk_sync, seq, text, recv_time, write_queue)
        pending.add(task)
        if len(pending) > 4:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)

def validate_chunk_sync(seq: int, text: str, recv_time: float, write_queue: queue.Queue):
    thread_name = threading.current_thread().name
    start = time.time()
    log.info(f"[VALIDATION START] Seq={seq} | Chunk: {repr(text[:50])}...")

    try:
        guard_output.validate(text, on="output")
        duration = time.time() - start
        log.info(f"[VALIDATION PASS] Seq={seq} ({duration:.3f}s) by {thread_name}")
        write_queue.put(("valid", seq, text, recv_time))
        return True
    except Exception as e:
        duration = time.time() - start
        log.error(f"[VALIDATION FAIL] Seq={seq} ({duration:.3f}s) by {thread_name} → {e}")
        write_queue.put(("fail", seq, text, recv_time))
        return False

def websocket_writer(write_queue: queue.Queue, ws: WebSocket, main_loop):
    """Thread-safe writer that sends to WebSocket using the main asyncio loop."""
    expected_seq = 0
    pending = {}

    def safe_send(data):
        # Schedule coroutine in the main event loop
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
            # Drain queue
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

async def stream_producer(prompt: str, raw_token_queue: asyncio.Queue):
    log.info("🚀 Connecting to model server...")
    try:
        async with ws_client.connect(MODEL_WS_URL) as model_ws:
            await model_ws.send(json.dumps({"prompt": prompt, "stream": True}))
            log.info("📤 Prompt sent")

            async for msg in model_ws:
                data = json.loads(msg)
                if "token" in data:
                    token = data["token"]
                    if token is None:
                        await raw_token_queue.put(None)
                        log.info("🔚 End of stream signal received from model")
                        return
                    await raw_token_queue.put(token)
                elif "error" in data:
                    log.error(f"💥 Model error: {data['error']}")
                    await raw_token_queue.put(None)  # Signal end on error
                    return
            # If the model WS closes without sending None, still signal end
            await raw_token_queue.put(None)
            log.info("🔚 Model WebSocket closed — stream ended")
    except Exception as e:
        log.exception(f"🔥 Stream error: {e}")
        await raw_token_queue.put(None)  # Always signal end on exception

# ====== FASTAPI APP ======
app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    client = ws.client.host
    log.info("Client %s connected", client)

    try:
        # Receive prompt
        data = await ws.receive_json()
        prompt = data.get("prompt", "").strip()
        if not prompt:
            await ws.send_json({"error": "Prompt is required"})
            return

        log.info(f"📥 Prompt from {client}: {repr(prompt)}")
        guard_input.validate(prompt, on="input")
        log.info("✅ Input guard passed")

        # Create per-connection queues
        raw_token_queue = asyncio.Queue()
        chunk_queue = asyncio.Queue()
        write_queue = queue.Queue()

        # Get the main event loop
        main_loop = asyncio.get_running_loop()

        # Start writer thread
        writer_thread = threading.Thread(
            target=websocket_writer,
            args=(write_queue, ws, main_loop),
            name="WebSocketWriter",
            daemon=True
        )
        writer_thread.start()

        # Start pipeline tasks
        assembler_task = asyncio.create_task(assemble_sentences(raw_token_queue, chunk_queue))
        dispatcher_task = asyncio.create_task(dispatch_validations(chunk_queue, write_queue))

        # Stream from model — this will eventually put None into raw_token_queue
        await stream_producer(prompt, raw_token_queue)

        # Wait for the entire pipeline to drain
        await assembler_task      # Puts None into chunk_queue when done
        await dispatcher_task     # Puts None into write_queue when done

        # Wait for writer to finish (it receives None from dispatcher)
        writer_thread.join(timeout=5)
        if writer_thread.is_alive():
            log.warning("⚠️ Writer thread did not terminate cleanly for client %s", client)
        else:
            log.info("✅ Streaming completed and writer terminated for client %s", client)

    except WebSocketDisconnect:
        log.info("Client %s disconnected", client)
    except Exception as exc:
        log.exception("Error in WebSocket handler for %s: %s", client, exc)
        try:
            await ws.send_json({"error": f"Server error: {str(exc)}"})
        except:
            pass

@app.get("/")
def health():
    return {"status": "Guardrails streaming server is running"}

# ====== RUN ======
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("temp:app", host="0.0.0.0", port=5000, log_level="info")