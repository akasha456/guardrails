import streamlit as st
import time
import json
import threading
import queue
import websocket
from datetime import datetime
import logging

# --------------------------------------------------------------------------- #
# Logging (kept exactly like you had it)
# --------------------------------------------------------------------------- #
logger = logging.getLogger("ChatApp")

# --------------------------------------------------------------------------- #
# WebSocket client (tiny, self-contained)
# --------------------------------------------------------------------------- #
WS_URL = "ws://localhost:8765/ws"   # the server.py endpoint

class WsClient:
    """Thread-safe WebSocket bridge to our llama-3.2 server."""
    def __init__(self, url: str):
        self.url = url
        self._q: "queue.Queue[dict]" = queue.Queue()
        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None

    # ---------- internal ----------
    def _run(self):
        def on_open(ws):
            logger.info("WebSocket connection opened to %s", self.url)

        def on_message(_ws, msg):
            self._q.put(json.loads(msg))

        def on_error(_ws, err):
            logger.error("WebSocket error: %s", err)
            self._q.put({"error": str(err)})

        def on_close(_ws, close_status_code, close_msg):
            logger.info("WebSocket closed – code=%s  msg=%s", close_status_code, close_msg)

        self._ws = websocket.WebSocketApp(
            self.url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        self._ws.run_forever()

    # ---------- public ----------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def send_prompt(self, prompt: str):
        if not self._ws or not self._ws.sock or not self._ws.sock.connected:
            st.error("Not connected to server – please refresh page")
            return
        payload = json.dumps({"prompt": prompt})
        logger.debug("Sending prompt (%d chars)", len(prompt))
        self._ws.send(payload)

    def stream(self):
        """Generator that yields tokens (str) OR error dict."""
        while True:
            item = self._q.get()
            if "token" in item:
                if item["token"] is None:   # end-of-stream sentinel
                    break
                yield item["token"]
            else:                           # error
                yield item


# --------------------------------------------------------------------------- #
# Existing guard-rail helpers (unchanged)
# --------------------------------------------------------------------------- #
def apply_guardrails(text, guardrail_model):
    if guardrail_model == "strict":
        if any(word in text.lower() for word in ["hate", "violence", "illegal"]):
            logger.warning("Strict guardrails blocked content.")
            return "Content blocked by strict guardrails", True
    elif guardrail_model == "moderate":
        if "spam" in text.lower():
            logger.warning("Moderate guardrails flagged content.")
            return "Content flagged by moderate guardrails", True
    return text, False


LLM_MODELS = ["llama-3.2"]          # we only expose the local model now
GUARDRAIL_MODELS = ["none", "moderate", "strict"]


def add_notification(message, notification_type="info"):
    if 'notifications' not in st.session_state:
        st.session_state.notifications = []
    st.session_state.notifications.append({
        "message": message,
        "type": notification_type,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    })


def display_notifications():
    if 'notifications' in st.session_state and st.session_state.notifications:
        with st.sidebar:
            st.subheader("Notifications")
            for note in st.session_state.notifications[-5:]:
                if note["type"] == "error":
                    st.error(f"{note['timestamp']}: {note['message']}")
                elif note["type"] == "success":
                    st.success(f"{note['timestamp']}: {note['message']}")
                else:
                    st.info(f"{note['timestamp']}: {note['message']}")


# --------------------------------------------------------------------------- #
# Main UI – identical to your original file
# --------------------------------------------------------------------------- #
def main():
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
        st.session_state.username = ""

    if not st.session_state.authenticated:
        st.error("❌ Please login first!")
        st.markdown("Navigate to **Login** page to authenticate.")
        logger.warning("Unauthenticated access attempt to chat page.")
        return

    if 'messages' not in st.session_state:
        st.session_state.messages = []
    if 'selected_llm' not in st.session_state:
        st.session_state.selected_llm = "llama-3.2"
    if 'selected_guardrail' not in st.session_state:
        st.session_state.selected_guardrail = "moderate"

    # ---- sidebar ----
    with st.sidebar:
        st.header(f"Welcome, {st.session_state.username}! 👋")
        selected_llm = st.selectbox("Select LLM Model", LLM_MODELS,
                                    index=LLM_MODELS.index(st.session_state.selected_llm))
        selected_guardrail = st.selectbox("Select Guardrails", GUARDRAIL_MODELS,
                                          index=GUARDRAIL_MODELS.index(st.session_state.selected_guardrail))

        if st.button("Clear Chat"):
            st.session_state.messages = []
            add_notification("Chat cleared", "success")
            logger.info(f"User {st.session_state.username} cleared chat.")
            st.rerun()

        if st.button("Logout"):
            st.session_state.authenticated = False
            st.session_state.username = ""
            st.session_state.messages = []
            st.session_state.notifications = []
            st.success("Logged out successfully!")
            logger.info("User logged out.")
            return

        display_notifications()

    st.session_state.selected_llm = selected_llm
    st.session_state.selected_guardrail = selected_guardrail

    st.title("🤖 Advanced Chatbot Interface")
    st.caption(f"Using {selected_llm} with {selected_guardrail} guardrails")

    # ---- render old messages ----
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if "metadata" in message:
                st.caption(message["metadata"])

    # ---- input ----
    if prompt := st.chat_input("Type your message here..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        logger.info(f"User {st.session_state.username} entered: {prompt}")

        guarded_input, blocked = apply_guardrails(prompt, st.session_state.selected_guardrail)
        if blocked:
            st.session_state.messages.append({
                "role": "assistant",
                "content": guarded_input,
                "metadata": f"🛡️ Blocked by {st.session_state.selected_guardrail} guardrails"
            })
            add_notification("Message blocked by guardrails", "error")
        else:
            try:
                # ---- WebSocket streaming ----
                if "ws_client" not in st.session_state:
                    st.session_state.ws_client = WsClient(WS_URL)
                    st.session_state.ws_client.start()
                    time.sleep(0.5)  # give it a moment to connect

                with st.chat_message("assistant"):
                    placeholder = st.empty()
                    text = ""
                    st.session_state.ws_client.send_prompt(guarded_input)
                    for token in st.session_state.ws_client.stream():
                        if isinstance(token, dict) and "error" in token:
                            st.error(token["error"])
                            logger.error("Server error: %s", token["error"])
                            break
                        text += token
                        placeholder.markdown(text + "▌")
                    placeholder.markdown(text)

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": text,
                    "metadata": f"🧠 Generated by {st.session_state.selected_llm} (local Ollama)"
                })
                add_notification(f"Response generated using {st.session_state.selected_llm}", "success")
                logger.info("LLM %s responded successfully (%d chars)", st.session_state.selected_llm, len(text))

            except Exception as e:
                error_msg = f"Error generating response: {str(e)}"
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
                add_notification("Failed to generate response", "error")
                logger.error(error_msg, exc_info=True)

        st.rerun()


if __name__ == "__main__":
    main()