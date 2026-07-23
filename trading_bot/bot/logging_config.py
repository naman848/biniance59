"""
Centralized logging configuration.

Logs go to both the console (INFO+) and a rotating file (DEBUG+) so that
every API request, response and error is traceable after the fact,
without flooding the terminal during normal use.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
LOG_FILE = os.path.join(LOG_DIR, "trading_bot.log")


def setup_logging(log_file: str = LOG_FILE, console_level: int = logging.INFO) -> logging.Logger:
    """Configure and return the root 'trading_bot' logger.

    - File handler: DEBUG level, captures full request/response detail.
    - Console handler: INFO level, keeps stdout readable for the user.
    """
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    logger = logging.getLogger("trading_bot")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Avoid duplicate handlers if setup_logging() is called more than once
    if logger.handlers:
        return logger

    file_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    console_formatter = logging.Formatter("%(levelname)-8s | %(message)s")

    file_handler = RotatingFileHandler(
        log_file, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(console_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger
