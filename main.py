import streamlit as st
from logging_config import setup_logging, get_login_logger, get_chatbot_logger, get_ollama_logger, get_guardrails_logger, get_ui_response_logger

# Initialize logging
setup_logging()

# Get loggers
login_logger = get_login_logger()
chatbot_logger = get_chatbot_logger()
ollama_logger = get_ollama_logger()
guardrails_logger= get_guardrails_logger()
ui_response_logger = get_ui_response_logger()

# Initialize session state for authentication
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = ""

st.title("🔐 Welcome to Secure Chat System")

if st.session_state.authenticated:
    st.success(f"Welcome, {st.session_state.username}!")
    st.markdown("Navigate to **Chatbot** page to start chatting.")
    login_logger.info(f"User {st.session_state.username} already authenticated.")
else:
    st.info("Please navigate to **Login** page to authenticate.")
    login_logger.debug("Unauthenticated user visited main page.")
