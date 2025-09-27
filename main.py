import streamlit as st
from logging_config import setup_logging

# Initialize logging
logger = setup_logging()

# Initialize session state for authentication
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = ""

st.title("🔐 Welcome to Secure Chat System")

if st.session_state.authenticated:
    st.success(f"Welcome, {st.session_state.username}!")
    st.markdown("Navigate to **Chatbot** page to start chatting.")
    logger.info(f"User {st.session_state.username} already authenticated.")
else:
    st.info("Please navigate to **Login** page to authenticate.")
    logger.debug("Unauthenticated user visited main page.")
