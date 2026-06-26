"""
Logging utility for ReactionBot.
Provides a centralized logger with rotating file handler.
"""
import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import LOG_LEVEL

# Ensure logs directory exists
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# Map string levels to logging constants
LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def handle_uncaught_exception(exc_type, exc_value, exc_traceback):
    """Handle uncaught exceptions and write them to the logger."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    log.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))


def handle_async_exception(loop, context):
    """Handle asyncio unhandled exceptions."""
    message = context.get("message", "Unhandled asyncio exception")
    exception = context.get("exception")
    if exception:
        log.error(f"Unhandled asyncio exception: {message}", exc_info=exception)
    else:
        log.error(f"Unhandled asyncio exception: {message}")


def setup_global_exception_handlers():
    """Install system and asyncio exception handlers."""
    sys.excepthook = handle_uncaught_exception
    try:
        loop = asyncio.get_event_loop()
        loop.set_exception_handler(handle_async_exception)
    except RuntimeError:
        pass


def get_logger(name: str = "reactionbot") -> logging.Logger:
    """
    Get or create a logger with the specified name.
    Uses LOG_LEVEL from config and writes to both console and file.
    """
    logger = logging.getLogger(name)

    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger

    level = LEVEL_MAP.get(LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(level)

    # Formatter
    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    # File handler with rotation (5 MB, 3 backups)
    file_handler = RotatingFileHandler(
        LOG_DIR / "bot.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger


# Default logger instance
log = get_logger()

# Install global exception handlers after logger is created
setup_global_exception_handlers()
