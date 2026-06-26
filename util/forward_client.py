"""
Forward Client - Pyrogram userbot for live forwarding.
Handles: listener registration, message forwarding, content re-upload.
"""
import asyncio
import os
from pathlib import Path
from typing import Optional, List, Dict, Set

from pyrogram import Client, filters
from pyrogram.types import Message, InputMediaPhoto, InputMediaVideo, InputMediaAudio, InputMediaDocument
from pyrogram.errors import FloodWait, ChatWriteForbidden, ChatForwardsRestricted, MessageIdInvalid
from pyrogram.handlers import MessageHandler

from config import API_ID, API_HASH, PYROBOT_WORKERS, UPLOADER_BOT_TOKEN
from util.logging import log
from util.sessions import get_forwarding_session
from util.watermark_thumb import add_watermark
from util.forward_queue import (
    get_active_forwarders,
    update_last_forwarded,
    wait_for_rate_limit,
    buffer_album_message,
    add_to_queue,
    mark_completed,
    mark_failed,
    mark_processing,
)
from util.uploader_bot import (
    init_uploader_bot,
    stop_uploader_bot,
    is_uploader_bot_ready,
    upload_media,
    ptb_copy_message,
    ptb_copy_messages,
    send_fwd_sticker,
    UPLOAD_DELAY,
)
from util.shared_helpers import (
    clean_caption,
    get_message_type,
    download_media,
    download_thumbnail,
    generate_thumb,
    cleanup_files,
)

# Global state
_forward_client: Optional[Client] = None
_forward_client_task: Optional[asyncio.Task] = None
_is_initialized = False
_registered_chats: Set[int] = set()  # Origin chats with registered handlers
_origin_to_targets: Dict[int, List[Dict]] = {}  # origin_chat_id -> list of forwarder configs
_handler_group = 10  # Handler group for forward listeners
_pyrobot_workers = PYROBOT_WORKERS if PYROBOT_WORKERS and PYROBOT_WORKERS > 0 else 4

# Temp directory for downloads
TEMP_DIR = Path(__file__).parent.parent / "data" / "temp" / "forward"
TEMP_DIR.mkdir(parents=True, exist_ok=True)


async def init_forward_client() -> bool:
    """Initialize the forwarding userbot client and uploader bot."""
    global _forward_client, _forward_client_task, _is_initialized
    
    session_string = get_forwarding_session()
    if not session_string:
        log.warning("[ForwardClient] FORWARDING_STRING not configured. Live forwarding disabled.")
        return False
    
    try:
        _forward_client = Client(
            name="forward_userbot",
            api_id=API_ID,
            api_hash=API_HASH,
            session_string=session_string,
            workdir=str(TEMP_DIR),
            workers=_pyrobot_workers,
            no_updates=False,  # We need updates for message listening
        )
        
        await _forward_client.start()
        me = await _forward_client.get_me()
        log.info(f"[ForwardClient] Started as {me.first_name} (@{me.username or 'N/A'})")
        
        # Initialize uploader bot if token is configured
        if UPLOADER_BOT_TOKEN:
            await init_uploader_bot()
        
        await refresh_forwarder_cache()
        _is_initialized = True
        return True
        
    except Exception as e:
        log.error(f"[ForwardClient] Failed to start: {e}")
        _forward_client = None
        return False


async def stop_forward_client() -> None:
    """Stop the forwarding client and uploader bot gracefully."""
    global _forward_client, _forward_client_task, _is_initialized
    
    if _forward_client_task:
        _forward_client_task.cancel()
        try:
            await _forward_client_task
        except asyncio.CancelledError:
            pass
        _forward_client_task = None
    
    if _forward_client:
        try:
            await _forward_client.stop()
            log.info("[ForwardClient] Stopped.")
        except Exception as e:
            log.error(f"[ForwardClient] Error stopping: {e}")
        _forward_client = None
    
    # Stop uploader bot
    await stop_uploader_bot()
    
    _is_initialized = False
    _registered_chats.clear()
    _origin_to_targets.clear()


def is_forward_client_ready() -> bool:
    """Check if forward client is initialized and connected."""
    return _is_initialized and _forward_client and _forward_client.is_connected


def get_forward_client() -> Optional[Client]:
    """Get the forward client instance."""
    return _forward_client

async def refresh_forwarder_cache() -> None:
    """Refresh the in-memory cache of active forwarders."""
    global _origin_to_targets, _registered_chats
    
    if not _forward_client:
        return
    forwarders = await get_active_forwarders()
    new_mapping: Dict[int, List[Dict]] = {}
    for fw in forwarders:
        origin_id = fw["origin_chat_id"]
        if origin_id not in new_mapping:
            new_mapping[origin_id] = []
        new_mapping[origin_id].append(fw)

    new_origins = set(new_mapping.keys()) - _registered_chats
    removed_origins = _registered_chats - set(new_mapping.keys())
    
    for origin_id in new_origins:
        await _register_listener(origin_id)
    
    
    _origin_to_targets = new_mapping
    _registered_chats = set(new_mapping.keys())
    
    log.debug(f"[ForwardClient] Cache refreshed: {len(_origin_to_targets)} origins, {sum(len(v) for v in _origin_to_targets.values())} forwarders")


async def add_forwarder_to_cache(forwarder: Dict) -> None:
    """Add a forwarder to the cache and register listener if needed."""
    global _origin_to_targets, _registered_chats
    
    origin_id = forwarder["origin_chat_id"]
    
    if origin_id not in _origin_to_targets:
        _origin_to_targets[origin_id] = []
    
    _origin_to_targets[origin_id].append(forwarder)
    
    if origin_id not in _registered_chats:
        await _register_listener(origin_id)
        _registered_chats.add(origin_id)
    
    log.debug(f"[ForwardClient] Added forwarder to cache for origin {origin_id}")


async def remove_forwarder_from_cache(forwarder_id: str) -> None:
    """Remove a forwarder from the cache."""
    global _origin_to_targets
    
    for origin_id, forwarders in list(_origin_to_targets.items()):
        _origin_to_targets[origin_id] = [
            fw for fw in forwarders if str(fw["_id"]) != forwarder_id
        ]
        if not _origin_to_targets[origin_id]:
            del _origin_to_targets[origin_id]
    
    log.debug(f"[ForwardClient] Removed forwarder {forwarder_id} from cache")

async def _register_listener(origin_chat_id: int) -> None:
    """Register a message handler for the given origin chat."""
    if not _forward_client:
        return
    
    try:
        chat_filter = filters.chat(origin_chat_id)
        
        _forward_client.add_handler(
            MessageHandler(_on_new_message, chat_filter),
            group=_handler_group
        )
        
        log.debug(f"[ForwardClient] Registered listener for chat {origin_chat_id}")
        
    except Exception as e:
        log.error(f"[ForwardClient] Failed to register listener for {origin_chat_id}: {e}")


async def _on_new_message(client: Client, message: Message) -> None:
    """Handle new messages in origin chats with ordered processing."""
    try:
        origin_id = message.chat.id
        forwarders = _origin_to_targets.get(origin_id, [])
        if not forwarders:
            return  # No active forwarders

        log.debug(f"[ForwardClient] New message {message.id} in {origin_id}")

        for fw in forwarders:
            # Double-check is_active (cache should only have active, but safety check)
            if not fw.get("is_active", False):
                continue
            forwarder_id = str(fw["_id"])
            target_id = fw["target_chat_id"]

            # Per-forwarder settings (default True for backwards compatibility)
            fwd_messages = fw.get("forward_messages", True)
            fwd_album = fw.get("forward_album", True)

            # Skip text-only messages when forward_messages is disabled
            if not message.media and not fwd_messages:
                continue

            if message.media_group_id:
                if fwd_album:
                    # Buffer and forward as an album
                    await buffer_album_message(
                        media_group_id=message.media_group_id,
                        forwarder_id=forwarder_id,
                        origin_chat_id=origin_id,
                        target_chat_id=target_id,
                        message_id=message.id,
                        callback=_process_album,
                    )
                else:
                    # Album disabled — forward each member individually
                    queue_id = await add_to_queue(
                        forwarder_id=forwarder_id,
                        origin_chat_id=origin_id,
                        target_chat_id=target_id,
                        message_id=message.id,
                    )
                    # Process sequentially - wait for previous to complete
                    await _process_single_message(queue_id, fw, message, fwd_messages)
            else:
                queue_id = await add_to_queue(
                    forwarder_id=forwarder_id,
                    origin_chat_id=origin_id,
                    target_chat_id=target_id,
                    message_id=message.id,
                )
                # Process sequentially - wait for previous to complete
                await _process_single_message(queue_id, fw, message, fwd_messages)

    except Exception as e:
        log.error(f"[ForwardClient] Error handling message: {e}")


async def _process_single_message(
    queue_id: str, forwarder: Dict, message: Message, forward_messages: bool = True
) -> None:
    """Process a single message forward with FloodWait retry."""
    if not _forward_client:
        return

    forwarder_id = str(forwarder["_id"])
    target_id = forwarder["target_chat_id"]

    try:
        if not await mark_processing(queue_id):
            return  # Already processed

        await wait_for_rate_limit(target_id)

        for attempt in range(2):
            try:
                await forward_message(_forward_client, message, target_id, forward_messages)
                break
            except FloodWait as e:
                if attempt == 0:
                    await asyncio.sleep(e.value)
                else:
                    raise

        await mark_completed(queue_id)
        await update_last_forwarded(forwarder_id)

    except FloodWait as e:
        await mark_failed(queue_id, f"FloodWait:{e.value}")
        await asyncio.sleep(e.value)
    except ChatWriteForbidden:
        await mark_failed(queue_id, "ChatWriteForbidden")
        from util.forward_queue import update_forwarder_status
        await update_forwarder_status(forwarder_id, False)
    except MessageIdInvalid:
        await mark_failed(queue_id, "MessageIdInvalid")
    except Exception as e:
        await mark_failed(queue_id, str(e)[:200])


async def _process_album(
    forwarder_id: str,
    origin_chat_id: int,
    target_chat_id: int,
    message_ids: List[int],
) -> None:
    """
    Process an album (media group) forward.
    - Not restricted: PTB copy_messages (hides sender, preserves album grouping)
    - Restricted: userbot download all → send_media_group
    """
    if not _forward_client:
        return

    try:
        await wait_for_rate_limit(target_chat_id)
        messages = await _forward_client.get_messages(origin_chat_id, message_ids)
        if not messages:
            return

        is_restricted = getattr(messages[0].chat, 'has_protected_content', False)

        if not is_restricted and is_uploader_bot_ready():
            try:
                await ptb_copy_messages(target_chat_id, origin_chat_id, message_ids)
                log.debug(f"[ForwardClient] Album copied via PTB to {target_chat_id}")
                await update_last_forwarded(forwarder_id)
                return
            except Exception as e:
                log.debug(f"[ForwardClient] PTB copy_messages failed ({e}), falling back")

        # Restricted source: download all → userbot send_media_group
        await _reupload_album_userbot(_forward_client, messages, target_chat_id)
        await update_last_forwarded(forwarder_id)

    except FloodWait as e:
        await asyncio.sleep(e.value)
    except Exception as e:
        log.debug(f"[ForwardClient] Album forward error: {e}")

async def forward_message(
    client: Client, message: Message, target_id: int, forward_messages: bool = True
) -> None:
    """
    Forward a message to target.
    Decision tree:
      - Source NOT restricted → PTB copy_message (hides sender)
      - Source restricted + single → userbot download → PTB upload
    When forward_messages=False, text-only messages are silently skipped.
    """
    caption = clean_caption(message.caption or message.text)

    # Skip text-only messages - only forward media
    if not message.media:
        return

    # Stickers always send custom FWD_STICKER — never copy the original
    if message.sticker:
        await send_fwd_sticker(target_id)
        return

    is_restricted = getattr(message.chat, 'has_protected_content', False)

    if not is_restricted and is_uploader_bot_ready():
        try:
            await ptb_copy_message(target_id, message.chat.id, message.id, caption)
            log.debug(f"[ForwardClient] Copied msg {message.id} via PTB to {target_id}")
            return
        except Exception as e:
            log.debug(f"[ForwardClient] PTB copy failed ({e}), falling back to re-upload")

    # Restricted or PTB unavailable: download + PTB upload
    await _reupload_single(client, message, target_id, caption)


async def _reupload_single(client: Client, message: Message, target_id: int, caption: Optional[str]) -> None:
    """Download and re-upload a single media message using PTB uploader bot."""
    if message.sticker:
        await send_fwd_sticker(target_id)
        return

    media_path = await download_media(message, TEMP_DIR)
    if not media_path:
        return

    thumb_path = await download_thumbnail(client, message, TEMP_DIR)
    if thumb_path:
        thumb_path = add_watermark(thumb_path)
    if not thumb_path and (message.video or (message.document
            and getattr(message.document, 'mime_type', '').startswith('video/'))):
        thumb_path = await generate_thumb(media_path)
        if thumb_path:
            thumb_path = add_watermark(thumb_path)

    try:
        await upload_media(
            target_chat_id=target_id,
            media_path=media_path,
            caption=caption,
            message_type=get_message_type(message),
            duration=getattr(message.video, 'duration', None) if message.video else None,
            width=getattr(message.video, 'width', None) if message.video else None,
            height=getattr(message.video, 'height', None) if message.video else None,
            performer=getattr(message.audio, 'performer', None) if message.audio else None,
            title=getattr(message.audio, 'title', None) if message.audio else None,
            thumb_path=thumb_path,
            file_name=message.document.file_name if message.document else None,
        )
    finally:
        cleanup_files(media_path, thumb_path)


async def _reupload_album_userbot(client: Client, messages: List[Message], target_id: int) -> None:
    """
    Download all album messages then send as a real media group via userbot.
    Used when source is restricted (has_protected_content).
    """
    downloaded: List[tuple] = []  # (media_path, thumb_path)
    media_list = []

    try:
        for i, msg in enumerate(messages):
            if not msg or not msg.media:
                continue
            if msg.sticker:
                await send_fwd_sticker(target_id)
                continue

            media_path = await download_media(msg, TEMP_DIR)
            if not media_path:
                continue

            thumb_path = await download_thumbnail(client, msg, TEMP_DIR)
            if thumb_path:
                thumb_path = add_watermark(thumb_path)
            downloaded.append((media_path, thumb_path))

            # Caption on last item only
            caption = clean_caption(msg.caption) if i == len(messages) - 1 else None

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
            await client.send_media_group(chat_id=target_id, media=media_list)
            log.debug(f"[ForwardClient] Album re-uploaded via userbot ({len(media_list)} items) to {target_id}")

    finally:
        for mp, tp in downloaded:
            cleanup_files(mp, tp)


async def get_chat_info(chat_id: int) -> Optional[Dict]:
    """Get chat info (name, type) for a chat ID."""
    if not _forward_client:
        return None
    
    try:
        chat = await _forward_client.get_chat(chat_id)
        return {
            "id": chat.id,
            "title": chat.title or chat.first_name or f"Chat {chat.id}",
            "type": str(chat.type),
            "username": chat.username,
        }
    except Exception as e:
        log.error(f"[ForwardClient] Failed to get chat info for {chat_id}: {e}")
        return None


async def validate_chat_access(chat_id: int) -> tuple[bool, Optional[str]]:
    """
    Validate that the userbot can access the chat.
    Returns (success, error_message).
    """
    if not _forward_client:
        return False, "Forward client not initialized"
    
    try:
        chat = await _forward_client.get_chat(chat_id)
        return True, None
    except Exception as e:
        return False, str(e)