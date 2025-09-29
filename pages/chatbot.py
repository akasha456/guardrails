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

WS_URL = "ws://localhost:8765/ws"


class WsClient:
    """Thin async→sync bridge for FastAPI WebSocket."""
    def __init__(self, url: str):
        self.url = url
        self._q = queue.Queue()

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
        ip = st.context.headers.get("X-Forwarded-For")
        if ip:
            return ip.split(",")[0].strip()
    except Exception:
        pass

    try:
        host = st.context.headers.get("Host", "").split(":")[0]
        if host in ["localhost", "127.0.0.1", "::1"]:
            try:
                response = requests.get("https://api.ipify.org?format=text", timeout=3)
                if response.status_code == 200:
                    return response.text.strip()
            except:
                pass
            return "127.0.0.1"
    except Exception:
        pass
    return "unknown"


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


def main():
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
        st.session_state.username = ""

    if not st.session_state.authenticated:
        ip_address = get_client_ip()
        st.session_state.ip_address = ip_address
        st.error("❌ Please login first!")
        st.markdown("Navigate to **Login** page to authenticate.")
        logger.warning("Unauthenticated access attempt to chat page by IP: %s.", ip_address)
        return

    if 'messages' not in st.session_state:
        st.session_state.messages = []
    if 'selected_llm' not in st.session_state:
        st.session_state.selected_llm = "llama-3.2"
    if 'selected_guardrail' not in st.session_state:
        st.session_state.selected_guardrail = "moderate"

    ip_address = getattr(st.session_state, 'ip_address', 'unknown')

    if "chat_page_loaded" not in st.session_state:
        logger.info(f"User {st.session_state.username} with IP {ip_address} accessed chatbot page.")
        st.session_state.chat_page_loaded = True

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
            logger.info(f"User {st.session_state.username} with IP {ip_address} cleared chat.")
            st.rerun()

        if st.button("Logout"):
            logger.info(f"User {st.session_state.username} logged out with IP {ip_address}.")
            st.session_state.authenticated = False
            st.session_state.username = ""
            st.session_state.messages = []
            st.session_state.notifications = []
            st.session_state.chat_page_loaded = False  # reset for next login
            st.success("Logged out successfully!")
            return

        display_notifications()

    st.session_state.selected_llm = selected_llm
    st.session_state.selected_guardrail = selected_guardrail

    st.title("🤖 Advanced Chatbot Interface")
    st.caption(f"Using {selected_llm} with {selected_guardrail} guardrails")

    # ---- render old messages with feedback UI ----
    for idx, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if "metadata" in message:
                st.caption(message["metadata"])

            # Only show feedback for assistant messages
            if message["role"] == "assistant":
                # Ensure feedback structure exists
                if "feedback" not in message:
                    message["feedback"] = {"rating": None, "comment": ""}
                feedback = message["feedback"]

                # Thumbs feedback (0 = 👎, 1 = 👍)
                rating_key = f"rating_{idx}"
                current_rating = feedback.get("rating")
                new_rating = st.feedback("thumbs", key=rating_key)
                if new_rating != current_rating:
                    st.session_state.messages[idx]["feedback"]["rating"] = new_rating
                    emoji = "👍" if new_rating == 1 else "👎" if new_rating == 0 else "–"
                    add_notification(f"Response rated: {emoji}", "info")
                    st.rerun()

                # Comment input
                comment_key = f"comment_{idx}"
                current_comment = feedback.get("comment", "")
                new_comment = st.text_input(
                    "Add a comment (optional):",
                    value=current_comment,
                    key=comment_key,
                    placeholder="e.g., Helpful, inaccurate, too long..."
                )
                if new_comment != current_comment:
                    st.session_state.messages[idx]["feedback"]["comment"] = new_comment


    if prompt := st.chat_input("Type your message here..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        ip_address = getattr(st.session_state, 'ip_address', 'unknown')
        logger.info(f"User {st.session_state.username} with IP {ip_address} entered: {prompt}")

        guarded_input, blocked = apply_guardrails(prompt, st.session_state.selected_guardrail)
        if blocked:
            st.session_state.messages.append({
                "role": "assistant",
                "content": guarded_input,
                "metadata": f"🛡️ Blocked by {st.session_state.selected_guardrail} guardrails",
                "feedback": {"rating": None, "comment": ""}
            })
            logger.warning(
                "Message blocked by guardrails for user %s with IP %s. Prompt: %s",
                st.session_state.username, ip_address, prompt
            )
            add_notification("Message blocked by guardrails", "error")
        else:
            try:
                if "ws_client" not in st.session_state:
                    st.session_state.ws_client = WsClient(WS_URL)
                    time.sleep(0.5)

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
                    "metadata": f"🧠 Generated by {st.session_state.selected_llm} (local Ollama)",
                    "feedback": {"rating": None, "comment": ""}
                })
                add_notification(f"Response generated using {st.session_state.selected_llm}", "success")
                logger.info(
                    "LLM %s responded successfully (%d chars) for user %s with IP %s. Response: %s",
                    st.session_state.selected_llm, len(text), st.session_state.username, ip_address, text
                )

            except Exception as e:
                error_msg = f"Error generating response: {str(e)} for user {st.session_state.username} with IP {ip_address}."
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": error_msg,
                    "feedback": {"rating": None, "comment": ""}
                })
                add_notification("Failed to generate response", "error")
                logger.error(error_msg, exc_info=True)



if __name__ == "__main__":
    main()