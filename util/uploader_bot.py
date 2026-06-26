"""
Uploader Bot — PTB-based bot for re-uploading media and copying messages
without forwarding attribution ("hide sender").
"""
import asyncio
import os
from pathlib import Path
from typing import Optional, List
from telegram import Bot
from telegram.error import TelegramError, RetryAfter
from config import UPLOADER_BOT_TOKEN, MAX_FILE_SIZE, USE_LOCAL_API, LOCAL_TGAPI_SERVER, UPLOAD_TIMEOUT, FWD_STICKER
from util.logging import log

TEMP_DIR = Path(__file__).parent.parent / "data" / "temp" / "forward"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

_uploader_bot: Optional[Bot] = None
_is_initialized = False

UPLOAD_DELAY = 1.0  # kept for callers that reference it
ALBUM_SEPARATOR = "━━━━━━━━━━━━"  # kept for backward compat


# ─── Lifecycle ───────────────────────────────────────────────────────────────

async def init_uploader_bot() -> bool:
    """Initialize the uploader bot."""
    global _uploader_bot, _is_initialized

    if not UPLOADER_BOT_TOKEN:
        log.warning("[UploaderBot] DEBUG: UPLOADER_BOT_TOKEN not set — uploader disabled.")
        return False

    try:
        if USE_LOCAL_API:
            from telegram.request import HTTPXRequest
            req = HTTPXRequest(
                connect_timeout=30.0,
                read_timeout=float(UPLOAD_TIMEOUT),
                write_timeout=float(UPLOAD_TIMEOUT),
                pool_timeout=30.0,
            )
            _uploader_bot = Bot(
                token=UPLOADER_BOT_TOKEN,
                base_url=f"{LOCAL_TGAPI_SERVER}/bot",
                base_file_url=f"{LOCAL_TGAPI_SERVER}/file/bot",
                request=req,
            )
            log.info(f"[UploaderBot] DEBUG: Using Local API Server -> {LOCAL_TGAPI_SERVER}")
        else:
            _uploader_bot = Bot(token=UPLOADER_BOT_TOKEN)
            log.info("[UploaderBot] DEBUG: Using Official Telegram API Server")
            
        await _uploader_bot.get_me()
        _is_initialized = True
        log.info("[UploaderBot] Initialized Successfully.")
        return True
    except Exception as e:
        log.error(f"[UploaderBot] CRITICAL: Init failed. Check token/network. Error: {e}", exc_info=True)
        _uploader_bot = None
        return False


async def stop_uploader_bot() -> None:
    global _uploader_bot, _is_initialized
    if _uploader_bot:
        try:
            await _uploader_bot.shutdown()
        except Exception:
            pass
        _uploader_bot = None
    _is_initialized = False


def is_uploader_bot_ready() -> bool:
    return _is_initialized and _uploader_bot is not None


def get_uploader_bot() -> Optional[Bot]:
    return _uploader_bot


# ─── Internal retry wrapper ──────────────────────────────────────────────────

async def _call_with_retry(coro_factory, max_retries: int = 3):
    """Retry on RetryAfter. coro_factory() must return a fresh coroutine each call."""
    for attempt in range(max_retries):
        try:
            return await coro_factory()
        except RetryAfter as e:
            log.warning(f"[UploaderBot] FLOODWAIT: Telegram restricted us. Attempt {attempt + 1}/{max_retries}. Must sleep for {e.retry_after}s.")
            if attempt < max_retries - 1:
                await asyncio.sleep(e.retry_after + 1)
            else:
                log.error(f"[UploaderBot] FLOODWAIT EXCEEDED: Max retries ({max_retries}) reached. Dropping request.")
                raise
        except TelegramError as te:
            log.error(f"[UploaderBot] TELEGRAM ERROR in wrapper (Attempt {attempt + 1}): {te}")
            raise


# ─── PTB copy helpers (hide sender — no "Forwarded from") ────────────────────

async def ptb_copy_message(
    target_chat_id: int,
    from_chat_id: int,
    message_id: int,
    caption: Optional[str] = None,
) -> bool:
    """Copy a single message via PTB (hides sender). Returns True on success."""
    if not _uploader_bot or not _is_initialized:
        log.error("[UploaderBot] COPY FAILED: Bot not initialized or token missing.")
        return False
    try:
        await _call_with_retry(
            lambda: _uploader_bot.copy_message(
                chat_id=target_chat_id,
                from_chat_id=from_chat_id,
                message_id=message_id,
                caption=caption,
                parse_mode="HTML" if caption else None,
            )
        )
        return True
    except Exception as e:
        log.error(f"[UploaderBot] COPY FAILED: MSG ID {message_id} from {from_chat_id} to {target_chat_id}. Error: {e}")
        return False


async def ptb_copy_messages(
    target_chat_id: int,
    from_chat_id: int,
    message_ids: List[int],
) -> bool:
    """Bulk-copy multiple messages via PTB (preserves album grouping). Returns True on success."""
    if not _uploader_bot or not _is_initialized:
        log.error("[UploaderBot] BULK COPY FAILED: Bot not initialized.")
        return False
    try:
        await _call_with_retry(
            lambda: _uploader_bot.copy_messages(
                chat_id=target_chat_id,
                from_chat_id=from_chat_id,
                message_ids=message_ids,
            )
        )
        return True
    except Exception as e:
        log.error(f"[UploaderBot] BULK COPY FAILED: Album {message_ids} from {from_chat_id} to {target_chat_id}. Error: {e}")
        return False


async def send_fwd_sticker(target_chat_id: int) -> bool:
    """Send the custom FWD_STICKER to target. Never copies the original sticker."""
    if not _uploader_bot or not _is_initialized:
        return False
    try:
        await _call_with_retry(
            lambda: _uploader_bot.send_sticker(chat_id=target_chat_id, sticker=FWD_STICKER)
        )
        return True
    except Exception as e:
        log.error(f"[UploaderBot] STICKER SEND FAILED to {target_chat_id}. Error: {e}")
        return False


# ─── PTB upload (restricted source — file already downloaded locally) ────────

async def upload_media(
    target_chat_id: int,
    media_path: str,
    caption: Optional[str] = None,
    message_type: str = "document",
    duration: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    performer: Optional[str] = None,
    title: Optional[str] = None,
    thumb_path: Optional[str] = None,
    file_name: Optional[str] = None,
) -> bool:
    """
    Upload a locally-downloaded file using the PTB bot.
    File handles are properly closed; RetryAfter is retried automatically.
    Returns True on success.
    """
    if not _uploader_bot or not _is_initialized:
        log.error(f"[UploaderBot] UPLOAD CRITICAL: Cannot upload {message_type}. Bot status: Initialized={_is_initialized}, BotObject={_uploader_bot is not None}")
        return False

    # 1. Path Verification Debug
    if not os.path.exists(media_path):
        log.error(f"[UploaderBot] UPLOAD FAILED: Local file NOT FOUND at path: {media_path}. Userbot download might have failed!")
        return False

    # 2. File Size Guard Debug
    file_size = os.path.getsize(media_path)
    if file_size > MAX_FILE_SIZE:
        log.error(f"[UploaderBot] UPLOAD SKIPPED: File is too large! Size: {file_size / (1024*1024):.2f}MB, Allowed MAX_FILE_SIZE: {MAX_FILE_SIZE / (1024*1024):.2f}MB. Path: {media_path}")
        return False

    log.info(f"[UploaderBot] STARTING UPLOAD: Type='{message_type}', Size={file_size / (1024*1024):.2f}MB, Path='{media_path}'")

    valid_thumb = thumb_path if (thumb_path and os.path.exists(thumb_path)) else None
    if thumb_path and not valid_thumb:
        log.warning(f"[UploaderBot] WARNING: Thumbnail path was provided but file not found: {thumb_path}. Proceeding without thumb.")

    pm = "HTML" if caption else None

    async def _send():
        with open(media_path, 'rb') as mf:
            tf = open(valid_thumb, 'rb') if valid_thumb else None
            try:
                if message_type == "photo":
                    await _uploader_bot.send_photo(chat_id=target_chat_id, photo=mf,
                                                    caption=caption, parse_mode=pm)
                elif message_type == "video":
                    await _uploader_bot.send_video(chat_id=target_chat_id, video=mf,
                                                    caption=caption, parse_mode=pm,
                                                    duration=duration, width=width, height=height,
                                                    supports_streaming=True, thumbnail=tf)
                elif message_type == "audio":
                    await _uploader_bot.send_audio(chat_id=target_chat_id, audio=mf,
                                                    caption=caption, parse_mode=pm,
                                                    duration=duration, performer=performer,
                                                    title=title, thumbnail=tf)
                elif message_type == "voice":
                    await _uploader_bot.send_voice(chat_id=target_chat_id, voice=mf,
                                                    caption=caption, parse_mode=pm)
                elif message_type == "animation":
                    await _uploader_bot.send_animation(chat_id=target_chat_id, animation=mf,
                                                        caption=caption, parse_mode=pm,
                                                        thumbnail=tf)
                elif message_type == "video_note":
                    await _uploader_bot.send_video_note(chat_id=target_chat_id,
                                                         video_note=mf, thumbnail=tf)
                elif message_type == "sticker":
                    await _uploader_bot.send_sticker(chat_id=target_chat_id, sticker=mf)
                else:  # document
                    await _uploader_bot.send_document(chat_id=target_chat_id, document=mf,
                                                       caption=caption, parse_mode=pm,
                                                       filename=file_name, thumbnail=tf)
            except TelegramError as e:
                log.error(f"[UploaderBot] TELEGRAM API ERROR during send execution: {e}")
                raise
            finally:
                if tf:
                    tf.close()

    try:
        await _call_with_retry(_send)
        log.info(f"[UploaderBot] SUCCESS: Successfully uploaded {message_type} to Chat: {target_chat_id}")
        return True
    except Exception as e:
        log.error(f"[UploaderBot] EXCEPTION OCCURRED: Upload failed permanently for {message_type}. Path: {media_path}. Error Detail: {e}", exc_info=True)
        return False
