"""
Session string validation helpers.
"""
from config import REACTION_STRING, FORWARDING_STRING, OLDFORWARDING_STRING
from util.logging import log

# Placeholder patterns that indicate session is not configured
_PLACEHOLDERS = (
    "pyrogram_session_string",
    "session_string_here",
    "your_session_string",
    "PASTE_SESSION_HERE",
    "",
)


def is_valid_session(session: str | None) -> bool:
    """
    Check if a session string is valid (not empty or placeholder).
    """
    if not session:
        return False
    session = session.strip()
    if len(session) < 50:  # Valid session strings are long
        return False
    for placeholder in _PLACEHOLDERS:
        if placeholder and placeholder.lower() in session.lower():
            return False
    return True


def get_reaction_session() -> str | None:
    """
    Get REACTION_STRING if valid, else None.
    """
    if is_valid_session(REACTION_STRING):
        return REACTION_STRING
    log.warning("REACTION_STRING not configured or is placeholder. Reaction userbot disabled.")
    return None


def get_forwarding_session() -> str | None:
    """
    Get FORWARDING_STRING if valid, else None.
    """
    if is_valid_session(FORWARDING_STRING):
        return FORWARDING_STRING
    log.warning("FORWARDING_STRING not configured or is placeholder. Forwarding userbot disabled.")
    return None


def get_old_forwarding_session() -> str | None:
    """
    Get OLDFORWARDING_STRING if valid, else None.
    """
    if is_valid_session(OLDFORWARDING_STRING):
        return OLDFORWARDING_STRING
    log.warning("OLDFORWARDING_STRING not configured or is placeholder. Old Forwarding userbot disabled.")
    return None
