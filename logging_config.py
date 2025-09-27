import logging
from logging.handlers import RotatingFileHandler
import os

def setup_logging():
    """Configure application-wide logging, avoiding duplicate handlers"""
    if not os.path.exists("logs"):
        os.makedirs("logs")

    logger = logging.getLogger("ChatApp")

    # Only set up once
    if not logger.handlers:
        log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

        logger.setLevel(logging.DEBUG)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(log_format))
        logger.addHandler(console_handler)

        # File handler with rotation
        file_handler = RotatingFileHandler(
            "logs/app.log", maxBytes=5_000_000, backupCount=5
        )
        file_handler.setFormatter(logging.Formatter(log_format))
        logger.addHandler(file_handler)

        logger.debug("Logging system initialized (first setup).")
    else:
        logger.debug("Logging already initialized, skipping re-setup.")

    return logger
