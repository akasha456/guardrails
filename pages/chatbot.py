import streamlit as st
import time
from datetime import datetime
import logging

logger = logging.getLogger("ChatApp")

# Mock LLM and Guardrails
def mock_llm_response(prompt, model):
    time.sleep(1)
    responses = {
        "gpt-4": f"GPT-4 response to: {prompt}",
        "claude-3": f"Claude-3 response to: {prompt}",
        "llama-3": f"Llama-3 response to: {prompt}"
    }
    logger.debug(f"LLM '{model}' generating response for prompt: {prompt}")
    return responses.get(model, f"Response from {model} to: {prompt}")

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

LLM_MODELS = ["gpt-4", "claude-3", "llama-3", "gemini-pro"]
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
        st.error("❌ Please login first!")
        st.markdown("Navigate to **Login** page to authenticate.")
        logger.warning("Unauthenticated access attempt to chat page.")
        return
    
    if 'messages' not in st.session_state:
        st.session_state.messages = []
    if 'selected_llm' not in st.session_state:
        st.session_state.selected_llm = "gpt-4"
    if 'selected_guardrail' not in st.session_state:
        st.session_state.selected_guardrail = "moderate"
    
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
    
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if "metadata" in message:
                st.caption(message["metadata"])
    
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
                response = mock_llm_response(guarded_input, st.session_state.selected_llm)
                final_response, response_blocked = apply_guardrails(response, st.session_state.selected_guardrail)
                
                if response_blocked:
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": final_response,
                        "metadata": f"🛡️ Response blocked by {st.session_state.selected_guardrail} guardrails"
                    })
                    add_notification("Response blocked by guardrails", "error")
                else:
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": final_response,
                        "metadata": f"🧠 Generated by {st.session_state.selected_llm}"
                    })
                    add_notification(f"Response generated using {st.session_state.selected_llm}", "success")
                    logger.info(f"LLM {st.session_state.selected_llm} responded successfully.")
            except Exception as e:
                error_msg = f"Error generating response: {str(e)}"
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
                add_notification("Failed to generate response", "error")
                logger.error(error_msg, exc_info=True)
        
        st.rerun()

if __name__ == "__main__":
    main()
