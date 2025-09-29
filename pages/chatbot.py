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
WS_URL = "ws://localhost:5000/ws"  # guard-server


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
                # Fixed: removed extra space in URL
                response = requests.get("https://api.ipify.org?format=text", timeout=3)
                if response.status_code == 200:
                    return response.text.strip()
            except:
                pass
            return "127.0.0.1"
    except Exception:
        pass
    return "unknown"


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


def render_feedback_ui(idx: int):
    """Render thumbs and comment input for assistant message at index `idx`."""
    message = st.session_state.messages[idx]
    if "feedback" not in message:
        message["feedback"] = {"rating": None, "comment": ""}
    feedback = message["feedback"]

    # Thumbs feedback
    rating_key = f"rating_{idx}"
    current_rating = feedback.get("rating")
    new_rating = st.feedback("thumbs", key=rating_key)
    if new_rating != current_rating:
        st.session_state.messages[idx]["feedback"]["rating"] = new_rating
        emoji = "👍" if new_rating == 1 else "👎" if new_rating == 0 else "–"
        add_notification(f"Response rated: {emoji}", "info")
        
        # ✅ LOG FEEDBACK TO CHATBOT LOGGER
        ip_address = getattr(st.session_state, 'ip_address', 'unknown')
        logger.info(
            "User %s (%s) rated response #%d: %s (rating=%s)",
            st.session_state.username,
            ip_address,
            idx,
            emoji,
            new_rating
        )
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
        if new_comment.strip():  # Only log non-empty comments
            ip_address = getattr(st.session_state, 'ip_address', 'unknown')
            logger.info(
                "User %s (%s) added comment to response #%d: %s",
                st.session_state.username,
                ip_address,
                idx,
                new_comment
            )


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
    logger.info(f"User {st.session_state.username} with IP {st.session_state.ip_address} accessed chatbot page.")
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
            st.session_state.chat_page_loaded = False
            st.success("Logged out successfully!")
            return

        display_notifications()

    st.session_state.selected_llm = selected_llm
    st.session_state.selected_guardrail = selected_guardrail

    st.title("🤖 Advanced Chatbot Interface")
    st.caption(f"Using {selected_llm} with {selected_guardrail} guardrails")

    # ---- render all messages with feedback ----
    for idx, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if "metadata" in message:
                st.caption(message["metadata"])
            if message["role"] == "assistant":
                render_feedback_ui(idx)

    # ---- input handling ----
    if prompt := st.chat_input("Type your message here..."):
        # Display user message immediately
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        ip_address = getattr(st.session_state, 'ip_address', 'unknown')
        logger.info(f"User {st.session_state.username} with IP {ip_address} entered: {prompt}")

        # ---- WebSocket streaming (guard-server handles guardrails) ----
        try:
            if "ws_client" not in st.session_state:
                st.session_state.ws_client = WsClient(WS_URL)
                time.sleep(0.5)

            # Prepare placeholder
            placeholder_msg = {
                "role": "assistant",
                "content": "",
                "metadata": f"🧠 Generated by {st.session_state.selected_llm} (guard-server)",
                "feedback": {"rating": None, "comment": ""}
            }
            st.session_state.messages.append(placeholder_msg)
            idx = len(st.session_state.messages) - 1

            with st.chat_message("assistant"):
                placeholder = st.empty()
                full_text = ""
                st.session_state.ws_client.send_prompt(prompt)
                stream_ended_normally = True

                for token in st.session_state.ws_client.stream():
                    if isinstance(token, dict) and "error" in token:
                        # ✅ Use ONLY the error message from guard-server
                        error_msg = token["error"]
                        st.session_state.messages[idx]["content"] = error_msg
                        st.session_state.messages[idx]["metadata"] = f"🛡️ {error_msg}"
                        st.markdown(error_msg)
                        st.caption(f"🛡️ {error_msg}")
                        logger.warning(
                            "Guardrails blocked user %s (%s): %s",
                            st.session_state.username,
                            st.session_state.ip_address,
                            error_msg
                        )
                        stream_ended_normally = False
                        break
                    full_text += token
                    placeholder.markdown(full_text + "▌")

                if stream_ended_normally:
                    placeholder.markdown(full_text)
                    st.session_state.messages[idx]["content"] = full_text
                    st.caption(placeholder_msg["metadata"])
                    logger.info(
                        "LLM %s replied %d chars to user %s (%s) with response %s",
                        st.session_state.selected_llm,
                        len(full_text),
                        st.session_state.username,
                        st.session_state.ip_address,
                        st.session_state.messages[idx]["metadata"]
                    )

                # Always show feedback UI
                render_feedback_ui(idx)

        except Exception as e:
            error_content = f"Error generating response: {str(e)}"
            error_msg = {
                "role": "assistant",
                "content": error_content,
                "metadata": "❌ Error occurred",
                "feedback": {"rating": None, "comment": ""}
            }
            st.session_state.messages.append(error_msg)
            idx = len(st.session_state.messages) - 1
            with st.chat_message("assistant"):
                st.error(error_content)
                st.caption("❌ Error occurred")
                render_feedback_ui(idx)
            add_notification("Failed to generate response", "error")
            logger.error(
                "Error for user %s (%s): %s",
                st.session_state.username,
                st.session_state.ip_address,
                str(e),
                exc_info=True
            )


if __name__ == "__main__":
    main()