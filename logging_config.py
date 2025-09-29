import logging
from logging.handlers import RotatingFileHandler
import os

def setup_logging():
    """Configure application-wide logging, avoiding duplicate handlers"""
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_format="%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"
    formatter = logging.Formatter(log_format) 

    login_loger=logging.getLogger("login")
    login_loger.setLevel(logging.INFO)

    if not login_loger.handlers:
        login_handler = RotatingFileHandler(
            os.path.join(log_dir, "login.log"), 
            maxBytes=5*1024*1024, 
            backupCount=2
        )
        login_handler.setFormatter(formatter)
        login_loger.addHandler(login_handler)
    
    chatbot_logger = logging.getLogger("chatbot")
    chatbot_logger.setLevel(logging.INFO)
    if not chatbot_logger.handlers:
        chatbot_handler = RotatingFileHandler(
            os.path.join(log_dir, "chatbot.log"), 
            maxBytes=5*1024*1024, 
            backupCount=2
        )
        chatbot_handler.setFormatter(formatter)
        chatbot_logger.addHandler(chatbot_handler)

    ollama_logger = logging.getLogger("ollama")
    ollama_logger.setLevel(logging.INFO)
    if not ollama_logger.handlers:
        ollama_handler = RotatingFileHandler(
            os.path.join(log_dir, "ollama.log"), 
            maxBytes=5*1024*1024, 
            backupCount=2
        )
        ollama_handler.setFormatter(formatter)
        ollama_logger.addHandler(ollama_handler)
    
    guardrails_logger = logging.getLogger("guardrails")
    guardrails_logger.setLevel(logging.INFO)
    if not guardrails_logger.handlers:
        guardrails_handler = RotatingFileHandler(
            os.path.join(log_dir, "guardrails.log"), 
            maxBytes=5*1024*1024, 
            backupCount=2
        )
        guardrails_handler.setFormatter(formatter)
        guardrails_logger.addHandler(guardrails_handler)

    ui_respomse_logger= logging.getLogger("ui_response")
    ui_respomse_logger.setLevel(logging.INFO)
    if not ui_respomse_logger.handlers:
        ui_response_handler= RotatingFileHandler(
            os.path.join(log_dir, "ui_response.log"),
            maxBytes=5*1024*1024,
            backupCount=2
        )
        ui_response_handler.setFormatter(formatter)
        ui_respomse_logger.addHandler(ui_response_handler)
    
    console_handler= logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    for logger in [login_loger, chatbot_logger, ollama_logger, guardrails_logger, ui_respomse_logger]:
        logger.addHandler(console_handler)

def get_login_logger():
    return logging.getLogger("login")
def get_chatbot_logger():
    return logging.getLogger("chatbot")
def get_ollama_logger():
    return logging.getLogger("ollama")
def get_guardrails_logger():
    return logging.getLogger("guardrails")
def get_ui_response_logger():
    return logging.getLogger("ui_response")
    
