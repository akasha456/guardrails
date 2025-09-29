import streamlit as st
import time
import queue
import asyncio
import websockets
import json
from datetime import datetime
import logging

# --------------------------------------------------------------------------- #
# Logging (unchanged)
# --------------------------------------------------------------------------- #
logger = logging.getLogger("ChatApp")

# --------------------------------------------------------------------------- #
# FastAPI WebSocket client (tiny, self-contained)
# --------------------------------------------------------------------------- #
WS_URL = "ws://localhost:8765/ws"

class WsClient:
    """Thin async→sync bridge for FastAPI WebSocket."""
    def __init__(self, url: str):
        self.url = url
        self._q = queue.Queue()

    # ---------- public ----------
    def send_prompt(self, prompt: str):
        asyncio.run(self._async_send(prompt))

    def stream(self):
        """Generator that yields tokens (str) OR error dict."""
        while True:
            item = self._q.get()
            if "token" in item:
                if item["token"] is None:
                    break
                yield item["token"]
            else:
                yield item

    # ---------- internal ----------
    async def _async_send(self, prompt: str):
        try:
            async with websockets.connect(self.url) as ws:
                await ws.send(json.dumps({"prompt": prompt}))
                async for msg in ws:
                    data = json.loads(msg)
                    self._q.put(data)
                    if data.get("token") is None or "error" in data:
                        break
        except Exception as e:
            self._q.put({"error": str(e)})


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


LLM_MODELS = ["llama-3.2"]
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