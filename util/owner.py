"""
Owner-only decorator and helpers.
"""
from functools import wraps
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes

from config import OWNER_IDS
from util.logging import log


def owner_only(func: Callable):
    """
    Decorator to restrict a handler to the bot owner only.
    Non-owners receive no response (silent ignore).
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if user is None or user.id not in OWNER_IDS:
            log.debug(f"Unauthorized access attempt by {user.id if user else 'unknown'}")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


def is_owner(user_id: int) -> bool:
    """Check if the given user_id is an owner."""
    return user_id in OWNER_IDS
