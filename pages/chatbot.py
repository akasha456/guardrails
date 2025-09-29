import streamlit as st
import time
import queue
import asyncio
import websockets
import json
from datetime import datetime
import logging
import requests
logger = logging.getLogger("chatbot")


WS_URL = "ws://localhost:5000/ws"   # guard-server

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


def get_client_ip():
    """Get client IP: real IP when deployed, public IP of server when on localhost."""
    try:
        # Try to get real client IP (works in cloud deployments)
        ip = st.context.headers.get("X-Forwarded-For")
        if ip:
            return ip.split(",")[0].strip()
    except Exception:
        pass

    # Fallback 1: Check if Host is localhost
    try:
        host = st.context.headers.get("Host", "").split(":")[0]
        if host in ["localhost", "127.0.0.1", "::1"]:
            # You're on localhost → get YOUR public IP (for demo only)
            try:
                response = requests.get("https://api.ipify.org?format=text", timeout=3)
                if response.status_code == 200:
                    return response.text.strip()
            except:
                pass
            return "127.0.0.1"  # final fallback
    except Exception:
        pass




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


def main():

    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
        st.session_state.username = ""
    

    if not st.session_state.authenticated:
        ip_address= get_client_ip()
        st.session_state.ip_address = ip_address
        st.error("❌ Please login first!")
        st.markdown("Navigate to **Login** page to authenticate.")
        logger.warning("Unauthenticated access attempt to chat page by ip by {ip_address}.")
        return

    if 'messages' not in st.session_state:
        st.session_state.messages = []
    if 'selected_llm' not in st.session_state:
        st.session_state.selected_llm = "llama-3.2"
    if 'selected_guardrail' not in st.session_state:
        st.session_state.selected_guardrail = "moderate"

    logger.info(f"User {st.session_state.username} with ip {st.session_state.ip_address} accessed chatbot page.")
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
            logger.info(f"User {st.session_state.username} wit ip {st.session_state.ip_address} cleared chat.")
            st.rerun()

        if st.button("Logout"):
            logger.info(f"User {st.session_state.username} logged out with ip {st.session_state.ip_address}.")
            st.session_state.authenticated = False
            st.session_state.username = ""
            st.session_state.messages = []
            st.session_state.notifications = []
            st.success("Logged out successfully!")
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
        logger.info("User %s (%s): %s", st.session_state.username,
                    st.session_state.ip_address, prompt)

        # ---- WebSocket streaming (guard-server handles all guardrails) ----
        try:
            if "ws_client" not in st.session_state:
                st.session_state.ws_client = WsClient(WS_URL)
                time.sleep(0.5)  # let it connect

            with st.chat_message("assistant"):
                placeholder = st.empty()
                text = ""
                st.session_state.ws_client.send_prompt(prompt)
                for token in st.session_state.ws_client.stream():
                    if isinstance(token, dict) and "error" in token:
                        # guard-server rejected either input or output
                        st.error(token["error"])
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": "Message blocked by guardrails.",
                            "metadata": f"🛡️ {token['error']}"
                        })
                        logger.warning("Guardrails blocked user %s (%s): %s",
                                    st.session_state.username,
                                    st.session_state.ip_address,
                                    token["error"])
                        break
                    text += token
                    placeholder.markdown(text + "▌")
                else:  # normal end-of-stream
                    placeholder.markdown(text)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": text,
                        "metadata": f"🧠 Generated by {st.session_state.selected_llm} (local Ollama)"
                    })
                    logger.info("LLM %s replied %d chars to user %s (%s)",
                                st.session_state.selected_llm, len(text),
                                st.session_state.username, st.session_state.ip_address)

        except Exception as e:
            error_msg = f"Error generating response: {str(e)}"
            st.session_state.messages.append({"role": "assistant", "content": error_msg})
            add_notification("Failed to generate response", "error")
            logger.error("Error for user %s (%s): %s",
                        st.session_state.username, st.session_state.ip_address, error_msg, exc_info=True)

        st.rerun()
if __name__ == "__main__":
    main()