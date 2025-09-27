import streamlit as st
import json
import os
import bcrypt
import logging

logger = logging.getLogger("ChatApp")

# File to store user credentials
CREDENTIALS_FILE = "users.json"

def load_users():
    if os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(CREDENTIALS_FILE, "w") as f:
        json.dump(users, f, indent=4)

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def register_user(username, password):
    users = load_users()
    if username in users:
        logger.warning(f"Registration failed: username '{username}' already exists.")
        return False, "Username already exists"
    
    users[username] = hash_password(password)
    save_users(users)
    logger.info(f"User '{username}' registered successfully.")
    return True, "Registration successful!"

def authenticate_user(username, password):
    users = load_users()
    if username not in users:
        logger.warning(f"Login attempt with non-existent user '{username}'.")
        return False
    if verify_password(password, users[username]):
        logger.info(f"User '{username}' authenticated successfully.")
        return True
    else:
        logger.warning(f"Failed login attempt for user '{username}'.")
        return False

def main():
    st.title("🔐 Login Page")
    
    tab1, tab2 = st.tabs(["Login", "Register"])
    
    with tab1:
        st.subheader("Login to Chat")
        username = st.text_input("Username", key="login_user")
        password = st.text_input("Password", type="password", key="login_pass")
        
        if st.button("Login"):
            if authenticate_user(username, password):
                st.session_state.authenticated = True
                st.session_state.username = username
                st.success("Login successful!")
                st.markdown("Navigate to **Chatbot** page to start chatting.")
            else:
                st.error("Invalid username or password")
    
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
                success, msg = register_user(new_user, new_pass)
                if success:
                    st.success(msg)
                else:
                    st.error(msg)

if __name__ == "__main__":
    main()
