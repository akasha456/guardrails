import streamlit as st
import time
import queue
import asyncio
import websockets
import json
from datetime import datetime
import logging
import requests
import threading

logger = logging.getLogger("chatbot")
ui_logger = logging.getLogger("ui_response")
WS_URL = "ws://localhost:5000/guard"  # guard-server


# ------------------------------------------------------------------
# WebSocket client (unchanged logic, only doc-string clarified)
# ------------------------------------------------------------------
class WsClient:
    """Thread-safe WebSocket client that streams tokens in real time."""
    def __init__(self, url: str):
        self.url = url
        self._q = queue.Queue()
        self._active = False

    # ---------- public entry ----------
    def send_prompt(self, prompt: str, meta: dict | None = None):
        if self._active:
            while not self._q.empty():
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    break
        self._active = True
        thread = threading.Thread(
            target=self._run_websocket, args=(prompt, meta or {}), daemon=True
        )
        thread.start()

    # ---------- background ----------
    def _run_websocket(self, prompt: str, meta: dict):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._async_send(prompt, meta))
        except Exception as e:
            self._q.put({"error": str(e)})
        finally:
            loop.close()
            self._q.put({"token": None})  # EOS marker

    async def _async_send(self, prompt: str, meta: dict):
        try:
            async with websockets.connect(self.url) as ws:
                payload = {"prompt": prompt, **meta}  # <-- inject meta
                await ws.send(json.dumps(payload))
                async for msg in ws:
                    data = json.loads(msg)
                    self._q.put(data)
                    if data.get("token") is None or "error" in data:
                        break
        except Exception as e:
            self._q.put({"error": str(e)})

    # ---------- consumer ----------
    def stream(self):
        while True:
            try:
                item = self._q.get(timeout=10)
            except queue.Empty:
                break
            if isinstance(item, dict):
                if "token" in item:
                    if item["token"] is None:
                        break
                    yield item["token"]
                else:
                    yield item
                    if "error" in item:
                        break
            else:
                yield str(item)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def get_client_ip():
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


LLM_MODELS = ["llama-3.2", "claude-2", "gpt-4", "VLLM"]
GUARDRAIL_MODELS = ["none", "moderate", "strict"]


def add_notification(message, notification_type="info"):
    if 'notifications' not in st.session_state:
        st.session_state.notifications = []
    st.session_state.notifications.append({
        "message": message,
        "type": notification_type,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    })
# ------------------------------------------------------------------
# File attachment helper
# ------------------------------------------------------------------
def attach_text_file():
    """Return the content of the uploaded text file (or None)."""
    uploaded = st.sidebar.file_uploader(
        "Attach a text file",
        type=["txt", "md", "py", "json", "yaml", "yml", "csv", "log"],
        help="The file’s content will be appended to your prompt."
    )
    logger.info(f"User '{st.session_state.username}' uploaded a file with ip {st.session_state.ip_address} with file name '{uploaded}'.")
    if uploaded is not None:
        string_data = uploaded.read().decode("utf-8", errors="replace")
        return string_data
    return None

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
    message = st.session_state.messages[idx]
    if "feedback" not in message:
        message["feedback"] = {"rating": None, "comment": ""}
    feedback = message["feedback"]

    rating_key = f"rating_{idx}"
    current_rating = feedback.get("rating")
    new_rating = st.feedback("thumbs", key=rating_key)
    if new_rating != current_rating:
        st.session_state.messages[idx]["feedback"]["rating"] = new_rating
        emoji = "👍" if new_rating == 1 else "👎" if new_rating == 0 else "–"
        add_notification(f"Response rated: {emoji}", "info")
        ip_address = getattr(st.session_state, 'ip_address', 'unknown')
        ui_logger.info(
            "User %s (%s) rated response #%d: %s (rating=%s)",
            st.session_state.username, ip_address, idx, emoji, new_rating
        )

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
        if new_comment.strip():
            ip_address = getattr(st.session_state, 'ip_address', 'unknown')
            ui_logger.info(
                "User %s (%s) added comment to response #%d: %s",
                st.session_state.username, ip_address, idx, new_comment
            )


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
def main():
    # ---------- auth ----------
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
        st.session_state.username = ""

    if not st.session_state.authenticated:
        ip_address = get_client_ip()
        st.session_state.ip_address = ip_address
        st.error("❌ Please login first!")
        st.markdown("Navigate to **Login** page to authenticate.")
        logger.warning("Unauthenticated access attempt to chat page by IP redirecting to login: %s.", ip_address)
        return

    # ---------- session init ----------
    if 'messages' not in st.session_state:
        st.session_state.messages = []
    if 'selected_llm' not in st.session_state:
        st.session_state.selected_llm = "llama-3.2"
    if 'selected_guardrail' not in st.session_state:
        st.session_state.selected_guardrail = "moderate"
    if "gen_id" not in st.session_state:
        st.session_state.gen_id = 0

    ip_address = getattr(st.session_state, 'ip_address', 'unknown')
    if "chat_page_loaded" not in st.session_state:
        logger.info(f"User {st.session_state.username} with IP {ip_address} accessed chatbot page.")
        st.session_state.chat_page_loaded = True

    # ---------- sidebar ----------
    with st.sidebar:
        st.header(f"Welcome, {st.session_state.username}! 👋")
        selected_llm = st.selectbox("Select LLM Model", LLM_MODELS,
                                    index=LLM_MODELS.index(st.session_state.selected_llm))
        selected_guardrail = st.selectbox("Select Guardrails", GUARDRAIL_MODELS,
                                          index=GUARDRAIL_MODELS.index(st.session_state.selected_guardrail))
        attached_text = attach_text_file()
        if attached_text:
            st.sidebar.success("File attached ✅")
        if st.button("Clear Chat"):
            st.session_state.messages = []
            add_notification("Chat cleared", "success")
            st.rerun()

        if st.button("Logout"):
            logger.info(f"User {st.session_state.username} logged out with IP {ip_address}.")
            for key in ['authenticated', 'username', 'messages', 'notifications', 'chat_page_loaded']:
                st.session_state.pop(key, None)
            st.success("Logged out successfully!")
            return

        display_notifications()

    st.session_state.selected_llm = selected_llm
    st.session_state.selected_guardrail = selected_guardrail

    # ---------- header ----------
    st.title("🤖 Advanced Chatbot Interface")
    st.caption(f"Using {selected_llm} with {selected_guardrail} guardrails")

    # ---------- message container (prevents full re-render) ----------
    msg_container = st.container()
    with msg_container:
        for idx, message in enumerate(st.session_state.messages):
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
                if "metadata" in message:
                    st.caption(message["metadata"])
                if message["role"] == "assistant":
                    render_feedback_ui(idx)


    # ---------- input ----------
    prompt_box = st.chat_input("Type your message here...")
    if prompt_box is not None:
        prompt = prompt_box
        if attached_text:                       # <-- NEW
                prompt = f"{prompt}\n\n---\n{attached_text}"  # simple 
        # user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with msg_container:
            with st.chat_message("user"):
                st.markdown(prompt)
        
        meta = {
            "username": st.session_state.username,
            "ip": ip_address,
            "model": st.session_state.selected_llm,
            "guard": st.session_state.selected_guardrail,
        }
        logger.info(
            "User %s (%s) → model=%s guard=%s prompt=%s",
            meta["username"], meta["ip"], meta["model"], meta["guard"], prompt
        )

        # assistant placeholder
        placeholder_msg = {
            "role": "assistant",
            "content": "",
            "metadata": f"🧠 Generated by {st.session_state.selected_llm} (guard-server)",
            "feedback": {"rating": None, "comment": ""}
        }
        st.session_state.messages.append(placeholder_msg)
        idx = len(st.session_state.messages) - 1

        # ---------- streaming ----------
        try:
            if "ws_client" not in st.session_state:
                st.session_state.ws_client = WsClient(WS_URL)
                time.sleep(0.5)

            st.session_state.gen_id += 1
            current_gen = st.session_state.gen_id

            with msg_container:
                with st.chat_message("assistant"):
                    placeholder = st.empty()
                    thinking = st.empty()
                    thinking.markdown("🤔 *Thinking…*")

                    full_text = ""
                    st.session_state.ws_client.send_prompt(prompt, meta)
                    logger.info("Prompt sent to guard-server for user %s (%s): %s", meta["username"], meta["ip"], prompt)
                    stream_ok = True

                    for payload in st.session_state.ws_client.stream():
                        if current_gen != st.session_state.gen_id:
                            break

                        if isinstance(payload, dict):
                            if "error" in payload:
                                thinking.empty()
                                error_ui = "Validation error has occurred. Sorry, try your response again."
                                placeholder.error(error_ui)
                                st.session_state.messages[idx]["content"]  = error_ui
                                st.session_state.messages[idx]["metadata"] = f"🛡️ guard-server rejected"
                                st.session_state.messages[idx]["feedback"] = {"rating": None, "comment": ""}
                                logger.info(
                                    "Assistant reply to user %s (%s) model=%s guard=%s : %s",
                                    meta["username"], meta["ip"], meta["model"], meta["guard"], error_ui
                                )
                                st.rerun()  
                                stream_ok = False
                                break
                            elif "response" in payload:
                                thinking.empty()
                                # ---- simulated typing ----
                                for ch in payload["response"]:
                                    full_text += ch
                                    placeholder.markdown(full_text + "▌")
                                    time.sleep(0.015)   # <-- controls speed
                                break
                        else:
                            thinking.empty()
                            # ---- simulated typing ----
                            for ch in payload:
                                full_text += ch
                                placeholder.markdown(full_text + "▌")
                                time.sleep(0.015)       # <-- controls speed

                    if stream_ok and current_gen == st.session_state.gen_id:
                        placeholder.markdown(full_text)  # final text without cursor
                        st.session_state.messages[idx]["content"] = full_text
                        logger.info(
                            "Recieved reply to user %s (%s) model=%s guard=%s : %s",
                            meta["username"], meta["ip"], meta["model"], meta["guard"], len(full_text))
                        st.rerun()   
        except Exception as e:
            error_content = f"Error generating response: {str(e)}"
            st.session_state.messages.append({
                "role": "assistant",
                "content": error_content,
                "metadata": "❌ Error occurred",
                "feedback": {"rating": None, "comment": ""}
            })
            add_notification("Failed to generate response", "error")
            logger.error(
                "Error for user %s (%s): %s",
                st.session_state.username, ip_address, str(e), exc_info=True
            )
        
if __name__ == "__main__":
    main()