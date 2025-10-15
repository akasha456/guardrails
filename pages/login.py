import streamlit as st
import json
import os
import bcrypt
import logging
import requests
from datetime import datetime

logger = logging.getLogger("login")

# Files
CREDENTIALS_FILE = "users.json"
LOGIN_LOG_FILE = "login_logs.json"  # New: store login attempts

def load_users():
    if os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(CREDENTIALS_FILE, "w") as f:
        json.dump(users, f, indent=4)

import requests

def get_client_ip():
    if hasattr(st.context, 'ip_address'):
        return st.context.ip_address
    else:
        return "localhost"

def log_login_attempt(username, success, ip_address):
    """Log login attempts to a JSON file."""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "username": username,
        "ip_address": ip_address,
        "success": success
    }
    logger.info(f"Login attempt by user with ip {ip_address}: {log_entry}")
    logs = []
    if os.path.exists(LOGIN_LOG_FILE):
        with open(LOGIN_LOG_FILE, "r") as f:
            logs = json.load(f)
    
    logs.append(log_entry)
    
    with open(LOGIN_LOG_FILE, "w") as f:
        json.dump(logs, f, indent=4)

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def register_user(username, password, ip_address):
    users = load_users()
    if username in users:
        logger.warning(f"Registration failed for {ip_address}: username '{username}' already exists.")
        return False, "Username already exists"
    
    users[username] = hash_password(password)
    save_users(users)
    logger.info(f"User '{username}' registered successfully with password: {password} with ip as {ip_address}.")
    return True, "Registration successful!"

def authenticate_user(username, password, ip_address):
    users = load_users()
    if username not in users:
        logger.warning(f"Login attempt with non-existent user '{username} with ip {ip_address}' .")
        return False
    if verify_password(password, users[username]):
        logger.info(f"User '{username}' authenticated successfully with ip {ip_address}.")
        return True
    else:
        logger.warning(f"Failed login attempt for user '{username}'.")
        return False

def main():
    st.title("🔐 Login Page")
    tab1, tab2 = st.tabs(["Login", "Register"])
    ip_address = get_client_ip()
    logger.info(f"Accessed login page with ip {ip_address} by user.")
    st.session_state.ip_address = ip_address
    with tab1:
        st.subheader("Login to Chat")
        username = st.text_input("Username", key="login_user")
        password = st.text_input("Password", type="password", key="login_pass")
        
        if st.button("Login"):
            if authenticate_user(username, password, ip_address):
                st.session_state.authenticated = True
                st.session_state.username = username
                st.session_state.login_time = datetime.now().isoformat()
                st.success("Login successful!")
                log_login_attempt(username, success=True, ip_address=ip_address)
                st.markdown("Navigate to **Chatbot** page to start chatting.")
                st.switch_page("pages/chatbot.py") 
            else:
                st.error("Invalid username or password")
                log_login_attempt(username, success=False, ip_address=ip_address)
                logger.warning(f"Failed login attempt for user '{username}' with ip {ip_address}.")
    
    with tab2:
        st.subheader("Create Account")
        new_user = st.text_input("New Username", key="reg_user")
        new_pass = st.text_input("New Password", type="password", key="reg_pass")
        confirm_pass = st.text_input("Confirm Password", type="password", key="reg_confirm")
        
        if st.button("Register"):
            if not new_user or not new_pass:
                st.error("Please fill all fields")
            elif new_pass != confirm_pass:
                st.error("Passwords do not match")
            elif len(new_pass) < 6:
                st.error("Password must be at least 6 characters")
            else:
                success, msg = register_user(new_user, new_pass, ip_address)
                if success:
                    st.success(msg)
                else:
                    st.error(msg)

if __name__ == "__main__":
    main()