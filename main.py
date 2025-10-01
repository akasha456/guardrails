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

if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = ""

if not st.session_state.authenticated:
    st.switch_page("pages/login.py")      # ⚡ Instant redirect
else:
    st.switch_page("pages/chatbot.py")    # ⚡ Instant redirect