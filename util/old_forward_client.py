import asyncio
import os
import re
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime

from pyrogram import Client
from pyrogram.types import (
    Message,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
    InputMediaAudio,
)
from pyrogram.enums import ChatType
from pyrogram.errors import (
    FloodWait,
    ChatWriteForbidden,
    ChatAdminRequired,
    MessageIdInvalid,
    ChatForwardsRestricted,
    ChannelPrivate,
)

from config import API_ID, API_HASH, PYROBOT_WORKERS
from util.logging import log
from util.sessions import get_old_forwarding_session
from util.watermark_thumb import add_watermark
from util.forward_queue import UploadRateLimiter
from util.uploader_bot import (
    upload_media,
    ptb_copy_message,
    ptb_copy_messages,
    send_fwd_sticker,
)
from util.shared_helpers import (
    clean_caption,
    get_message_type,
    download_media,
    download_thumbnail,
    generate_thumb,
    cleanup_files,
)

_old_client: Optional[Client] = None
_is_initialized = False
_joined_chats: Dict[int, Dict] = {}

TEMP_DIR = Path(__file__).parent.parent / "data" / "temp" / "old_forward"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

_job_lock = asyncio.Lock()
_current_job: Optional[str] = None

_PUBLIC_LINK_PATTERN = re.compile(r't\.me/([^/]+)/(\d+)')
_PRIVATE_LINK_PATTERN = re.compile(r't\.me/c/(\d+)/(\d+)')


async def init_old_forward_client() -> bool:
    """Initialize the old forwarding userbot client."""
    global _old_client, _is_initialized, _joined_chats

    session_string = get_old_forwarding_session()
    if not session_string:
        log.warning("[OldForward] OLDFORWARDING_STRING not configured. Old forwarding disabled.")
        return False

    try:
        workers = PYROBOT_WORKERS if PYROBOT_WORKERS and PYROBOT_WORKERS > 0 else 4
        _old_client = Client(
            name="old_forward_userbot",
            api_id=API_ID,
            api_hash=API_HASH,
            session_string=session_string,
            workdir=str(TEMP_DIR),
            workers=workers,
            no_updates=True,  # No need for live updates
        )

        await _old_client.start()
        me = await _old_client.get_me()
        log.info(f"[OldForward] Started as {me.first_name} (@{me.username or 'N/A'})")

        await refresh_joined_chats()
        _is_initialized = True
        return True

    except Exception as e:
        log.error(f"[OldForward] Failed to start: {e}")
        _old_client = None
        return False


async def stop_old_forward_client() -> None:
    """Stop the old forwarding client."""
    global _old_client, _is_initialized, _joined_chats

    if _old_client:
        try:
            await _old_client.stop()
            log.info("[OldForward] Stopped.")
        except Exception as e:
            log.error(f"[OldForward] Error stopping: {e}")
        _old_client = None

    _is_initialized = False
    _joined_chats.clear()


def is_old_forward_ready() -> bool:
    """Check if old forward client is ready."""
    return _is_initialized and _old_client and _old_client.is_connected


def get_old_client() -> Optional[Client]:
    """Get the old forward client instance."""
    return _old_client


async def refresh_joined_chats() -> int:
    """Refresh cache of joined chats. Returns count."""
    global _joined_chats

    if not _old_client:
        return 0

    _joined_chats.clear()
    count = 0

    try:
        # Use iter_dialogs for better compatibility
        async for dialog in _old_client.get_dialogs():
            chat = dialog.chat
            # Compare with ChatType enum values
            if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL):
                _joined_chats[chat.id] = {
                    "title": chat.title or f"Chat {chat.id}",
                    "type": chat.type.name.lower(),
                    "username": chat.username,
                }
                count += 1
        log.info(f"[OldForward] Cached {count} joined chats")
    except Exception as e:
        log.error(f"[OldForward] Failed to cache chats: {e}")
        import traceback
        log.error(traceback.format_exc())

    return count


def get_joined_chats() -> Dict[int, Dict]:
    """Get cached joined chats."""
    return _joined_chats.copy()


def get_joined_chats_list() -> List[Dict]:
    """Get joined chats as sorted list."""
    return [
        {"id": chat_id, **info}
        for chat_id, info in sorted(_joined_chats.items(), key=lambda x: x[1]["title"].lower())
    ]


def parse_telegram_link(link: str) -> Optional[Dict]:
    """
    Parse Telegram post link to extract chat_id and message_id.
    Returns: {chat_id, message_id, is_private, username_or_id} or None
    """
    link = link.strip()

    match = _PRIVATE_LINK_PATTERN.search(link)
    if match:
        raw_id = int(match.group(1))
        msg_id = int(match.group(2))
        chat_id = int(f"-100{raw_id}")
        return {
            "chat_id": chat_id,
            "message_id": msg_id,
            "is_private": True,
            "identifier": str(raw_id),
        }

    match = _PUBLIC_LINK_PATTERN.search(link)
    if match:
        username = match.group(1)
        msg_id = int(match.group(2))
        if username == 'c':
            return None
        return {
            "chat_id": None, 
            "message_id": msg_id,
            "is_private": False,
            "identifier": username,
        }

    return None


async def resolve_chat_from_link(parsed: Dict) -> Optional[Dict]:
    """
    Resolve full chat info from parsed link.
    Returns: {chat_id, chat_name, message_id} or None
    """
    if not _old_client:
        return None

    try:
        if parsed["is_private"]:
            chat = await _old_client.get_chat(parsed["chat_id"])
        else:
            chat = await _old_client.get_chat(parsed["identifier"])

        return {
            "chat_id": chat.id,
            "chat_name": chat.title or chat.first_name or f"Chat {chat.id}",
            "message_id": parsed["message_id"],
        }
    except ChannelPrivate:
        log.warning(f"[OldForward] Cannot access private chat: {parsed['identifier']}")
        return None
    except Exception as e:
        log.error(f"[OldForward] Failed to resolve chat: {e}")
        return None


async def acquire_job_lock(job_id: str) -> bool:
    """Try to acquire job lock. Returns True if acquired."""
    global _current_job

    if _job_lock.locked():
        return False

    await _job_lock.acquire()
    _current_job = job_id
    return True


def release_job_lock() -> None:
    """Release the job lock."""
    global _current_job

    if _job_lock.locked():
        _current_job = None
        _job_lock.release()


def is_job_running() -> bool:
    """Check if a job is currently running."""
    return _job_lock.locked()


def get_current_job_id() -> Optional[str]:
    """Get current running job ID."""
    return _current_job


async def forward_single_message(
    origin_chat_id: int,
    target_chat_id: int,
    message_id: int,
    forward_messages: bool = True,
    forward_album: bool = True,
) -> tuple[bool, str, Optional[str]]:
    """
    Forward a single message. Returns (success, error_or_empty, media_group_id_or_None).
    Decision tree:
      - Source NOT restricted → PTB copy_message (hides sender)
      - Source restricted     → userbot download → PTB upload
    FloodWait: sleep then retry once instead of permanently failing.
    """
    if not _old_client:
        return False, "Client not initialized", None

    try:
        msg = await _old_client.get_messages(origin_chat_id, message_id)
        if not msg or msg.empty:
            return False, "Message not found or deleted", None

        if forward_album and msg.media_group_id:
            return False, "ALBUM_MEMBER", msg.media_group_id

        caption = clean_caption(msg.caption or msg.text)

        if not msg.media:
            return False, "SKIPPED", None

        # Stickers always send custom FWD_STICKER — never copy the original
        if msg.sticker:
            await send_fwd_sticker(target_chat_id)
            return True, "", None

        is_restricted = getattr(msg.chat, 'has_protected_content', False)

        if not is_restricted:
            try:
                await ptb_copy_message(target_chat_id, origin_chat_id, message_id, caption)
                return True, "", None
            except Exception as e:
                if "CHAT_FORWARDS_RESTRICTED" in str(e) or isinstance(e, ChatForwardsRestricted):
                    is_restricted = True  # treat as restricted and fall through
                else:
                    raise

        # Restricted path: download → PTB upload
        await UploadRateLimiter.wait()
        success, error = await _reupload_with_uploader_bot(msg, target_chat_id, caption)
        return success, error, None

    except FloodWait as e:
        UploadRateLimiter.update_min_interval(e.value + 1)
        await asyncio.sleep(e.value)
        # Retry once
        try:
            msg = await _old_client.get_messages(origin_chat_id, message_id)
            if msg and not msg.empty and msg.media:
                caption = clean_caption(msg.caption or msg.text)
                is_restricted = getattr(msg.chat, 'has_protected_content', False)
                if not is_restricted:
                    await ptb_copy_message(target_chat_id, origin_chat_id, message_id, caption)
                else:
                    await UploadRateLimiter.wait()
                    await _reupload_with_uploader_bot(msg, target_chat_id, caption)
                return True, "", None
        except Exception:
            pass
        return False, f"FloodWait:{e.value}", None
    except ChatWriteForbidden:
        return False, "CHAT_WRITE_FORBIDDEN", None
    except ChatAdminRequired:
        return False, "CHAT_ADMIN_REQUIRED", None
    except MessageIdInvalid:
        return False, "MessageIdInvalid", None
    except Exception as e:
        if "CHAT_ADMIN_REQUIRED" in str(e):
            return False, "CHAT_ADMIN_REQUIRED", None
        log.debug(f"[OldForward] Forward error: {e}")
        return False, str(e)[:100], None


async def forward_album_group(
    origin_chat_id: int,
    target_chat_id: int,
    message_ids: List[int],
) -> tuple[int, int]:
    """
    Forward a list of messages as an album group.
    Decision tree:
      - Source NOT restricted → PTB copy_messages (preserves album grouping)
      - Source restricted     → userbot download all → send_media_group
    Returns (success_count, failed_count).
    """
    if not _old_client or not message_ids:
        return 0, len(message_ids)

    try:
        msgs = await _old_client.get_messages(origin_chat_id, message_ids)
        if not msgs:
            return 0, len(message_ids)

        is_restricted = getattr(msgs[0].chat, 'has_protected_content', False)

        if not is_restricted:
            try:
                await ptb_copy_messages(target_chat_id, origin_chat_id, message_ids)
                return len(message_ids), 0
            except Exception as e:
                if "CHAT_FORWARDS_RESTRICTED" not in str(e) and not isinstance(e, ChatForwardsRestricted):
                    log.debug(f"[OldForward] PTB copy_messages failed: {e}, falling back")
                is_restricted = True  # fall through to userbot path

        # Restricted: download all → userbot send_media_group
        downloaded: List[tuple] = []
        media_list = []
        sticker_count = 0
        try:
            for i, msg in enumerate(msgs):
                if not msg or msg.empty or not msg.media:
                    continue
                if msg.sticker:
                    if await send_fwd_sticker(target_chat_id):
                        sticker_count += 1
                    continue

                media_path = await download_media(msg, TEMP_DIR)
                if not media_path:
                    continue

                thumb_path = await download_thumbnail(_old_client, msg, TEMP_DIR)
                if thumb_path:
                    thumb_path = add_watermark(thumb_path)
                downloaded.append((media_path, thumb_path))

                caption = clean_caption(msg.caption) if i == len(msgs) - 1 else None

                if msg.photo:
                    media_list.append(InputMediaPhoto(media_path, caption=caption))
                elif msg.video:
                    media_list.append(InputMediaVideo(
                        media_path, caption=caption,
                        duration=getattr(msg.video, 'duration', None),
                        width=getattr(msg.video, 'width', None),
                        height=getattr(msg.video, 'height', None),
                        supports_streaming=True,
                        thumb=thumb_path if thumb_path and os.path.exists(thumb_path) else None,
                    ))
                elif msg.audio:
                    media_list.append(InputMediaAudio(media_path, caption=caption))
                else:
                    media_list.append(InputMediaDocument(media_path, caption=caption))

            if media_list:
                await _old_client.send_media_group(chat_id=target_chat_id, media=media_list)
                log.debug(f"[OldForward] Album re-uploaded via userbot ({len(media_list)} items) to {target_chat_id}")
                return len(media_list) + sticker_count, len(message_ids) - len(media_list) - sticker_count
            return sticker_count, len(message_ids) - sticker_count

        finally:
            for mp, tp in downloaded:
                cleanup_files(mp, tp)

    except FloodWait as e:
        UploadRateLimiter.update_min_interval(e.value + 1)
        await asyncio.sleep(e.value)
        return 0, len(message_ids)
    except Exception as e:
        log.debug(f"[OldForward] Album forward error: {e}")
        return 0, len(message_ids)



async def _reupload_with_uploader_bot(
    msg: Message,
    target_chat_id: int,
    caption: Optional[str],
) -> tuple[bool, str]:
    """Download and re-upload a single message using PTB uploader bot."""
    if msg.sticker:
        success = await send_fwd_sticker(target_chat_id)
        return (True, "") if success else (False, "Uploader bot not ready for sticker")

    media_path = await download_media(msg, TEMP_DIR)
    if not media_path:
        return False, "Download failed"

    thumb_path = await download_thumbnail(_old_client, msg, TEMP_DIR)
    if thumb_path:
        thumb_path = add_watermark(thumb_path)
    if not thumb_path and (msg.video or (msg.document
            and getattr(msg.document, 'mime_type', '').startswith('video/'))):
        thumb_path = await generate_thumb(media_path)
        if thumb_path:
            thumb_path = add_watermark(thumb_path)

    try:
        success = await upload_media(
            target_chat_id=target_chat_id,
            media_path=media_path,
            caption=caption,
            message_type=get_message_type(msg),
            duration=getattr(msg.video, 'duration', None) if msg.video else None,
            width=getattr(msg.video, 'width', None) if msg.video else None,
            height=getattr(msg.video, 'height', None) if msg.video else None,
            performer=getattr(msg.audio, 'performer', None) if msg.audio else None,
            title=getattr(msg.audio, 'title', None) if msg.audio else None,
            thumb_path=thumb_path,
            file_name=msg.document.file_name if msg.document else None,
        )
        return (True, "") if success else (False, "Upload failed")
    except Exception as e:
        log.debug(f"[OldForward] Re-upload error: {e}")
        return False, str(e)[:100]
    finally:
        cleanup_files(media_path, thumb_path)