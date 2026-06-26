import asyncio
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from config import OWNER_IDS
from util.logging import log
from util.owner import owner_only, is_owner
from util.db import get_db
from util.old_forward_client import (
    is_old_forward_ready,
    parse_telegram_link,
    resolve_chat_from_link,
    get_joined_chats_list,
    acquire_job_lock,
    release_job_lock,
    is_job_running,
    forward_single_message,
    forward_album_group,
    refresh_joined_chats,
)
from util.responses import (
    OLDFWD_NOT_READY,
    OLDFWD_JOB_RUNNING,
    OLDFWD_HELP,
    OLDFWD_CHAT_ACCESS_ERROR,
    OLDFWD_START_DETECTED,
    OLDFWD_WRONG_CHAT,
    OLDFWD_RANGE_CONFIRMED,
    OLDFWD_PAGE_INFO,
    OLDFWD_CANCELLED,
    OLDFWD_SESSION_EXPIRED,
    OLDFWD_CLIENT_NOT_READY,
    OLDFWD_ANOTHER_JOB,
    OLDFWD_PROGRESS,
    OLDFWD_COMPLETE,
    OLDFWD_STOPPED,
    OLDFWD_FAILED,
    OLDFWD_NO_PERMISSION,
    OLDFWD_OPTIONS,
)

WAITING_END_LINK = 2
WAITING_TARGET = 3
WAITING_OPTIONS = 4
CHATS_PER_PAGE = 5

# ─────────────────────────────────────────────────────────────────────────────
# Stop-request registry
# Running jobs check this set each iteration; stop callbacks write to it.
# ─────────────────────────────────────────────────────────────────────────────
_stop_requests: set[str] = set()

def request_stop(job_id: str) -> None:
    _stop_requests.add(job_id)

def is_stop_requested(job_id: str) -> bool:
    return job_id in _stop_requests

def clear_stop_request(job_id: str) -> None:
    _stop_requests.discard(job_id)

def _build_stop_keyboard(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 Stop Forwarding", callback_data=f"oldfwd_stop:{job_id}")]
    ])

def old_forward_jobs_col():
    """Get old_forward_jobs collection."""
    return get_db().old_forward_jobs

async def create_job(data: dict) -> str:
    """Create a new old forward job."""
    doc = {
        "owner_id": data["owner_id"],
        "origin_chat_id": data["origin_chat_id"],
        "origin_chat_name": data["origin_chat_name"],
        "target_chat_id": data["target_chat_id"],
        "target_chat_name": data["target_chat_name"],
        "start_msg_id": data["start_msg_id"],
        "end_msg_id": data["end_msg_id"],
        "total_messages": data["end_msg_id"] - data["start_msg_id"] + 1,
        "forwarded_count": 0,
        "failed_count": 0,
        "status": "running",
        "created_at": datetime.utcnow(),
        "started_at": datetime.utcnow(),
        "completed_at": None,
        "error": None,
    }
    result = await old_forward_jobs_col().insert_one(doc)
    return str(result.inserted_id)


async def update_job_progress(job_id: str, forwarded: int, failed: int) -> None:
    """Update job progress counters."""
    from bson import ObjectId
    await old_forward_jobs_col().update_one(
        {"_id": ObjectId(job_id)},
        {"$set": {"forwarded_count": forwarded, "failed_count": failed}}
    )


async def complete_job(job_id: str, status: str = "completed", error: str = None) -> None:
    """Mark job as completed."""
    from bson import ObjectId
    await old_forward_jobs_col().update_one(
        {"_id": ObjectId(job_id)},
        {"$set": {
            "status": status,
            "completed_at": datetime.utcnow(),
            "error": error,
        }}
    )


def build_progress_bar(current: int, total: int, width: int = 12) -> str:
    """Build a text progress bar."""
    if total == 0:
        return "□" * width
    progress = min(current / total, 1.0)
    filled = int(width * progress)
    return "■" * filled + "□" * (width - filled)


def format_duration(seconds: float) -> str:
    """Format seconds to human readable duration."""
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"


def build_target_keyboard(chats: list, page: int = 0, range_info: dict = None) -> tuple[str, InlineKeyboardMarkup]:
    """Build target selection message and keyboard.
    
    Args:
        chats: List of joined chats
        page: Current page number
        range_info: Optional dict with start_id, end_id, total for header display
    """
    total_pages = max(1, (len(chats) + CHATS_PER_PAGE - 1) // CHATS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))

    # Build header with range info if provided
    if range_info:
        text = OLDFWD_RANGE_CONFIRMED.format(
            start_id=range_info["start_id"],
            end_id=range_info["end_id"],
            total=range_info["total"],
        ) + "\n\n"
    else:
        text = "📋 <b>Select Target</b>\n\n"

    keyboard = []
    keyboard.append([InlineKeyboardButton("💾 Saved Messages", callback_data="oldfwd_target:saved")])

    start_idx = page * CHATS_PER_PAGE
    end_idx = start_idx + CHATS_PER_PAGE
    page_chats = chats[start_idx:end_idx]

    for chat in page_chats:
        title = chat["title"][:25] + "..." if len(chat["title"]) > 25 else chat["title"]
        keyboard.append([
            InlineKeyboardButton(f"📋 {title}", callback_data=f"oldfwd_target:{chat['id']}")
        ])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(f"◀️ Prev {page}/{total_pages}", callback_data=f"oldfwd_page:{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(f"{page + 2}/{total_pages} Next ▶️", callback_data=f"oldfwd_page:{page + 1}"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([
        InlineKeyboardButton("🔄 Refresh", callback_data="oldfwd_refresh"),
        InlineKeyboardButton("❌ Cancel", callback_data="oldfwd_cancel"),
    ])

    text += OLDFWD_PAGE_INFO.format(current=page + 1, total=total_pages, count=len(chats))

    return text, InlineKeyboardMarkup(keyboard)


@owner_only
async def oldforward_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /oldforward - show status and help."""
    if not is_old_forward_ready():
        await update.message.reply_text(OLDFWD_NOT_READY, parse_mode="HTML")
        return

    if is_job_running():
        await update.message.reply_text(OLDFWD_JOB_RUNNING, parse_mode="HTML")
        return

    await update.message.reply_text(OLDFWD_HELP, parse_mode="HTML")


async def handle_link_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle incoming Telegram links from owners."""
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END

    if not is_old_forward_ready():
        await update.message.reply_text(OLDFWD_NOT_READY, parse_mode="HTML")
        return ConversationHandler.END

    text = update.message.text.strip()
    parsed = parse_telegram_link(text)

    if not parsed:
        return ConversationHandler.END  # Not a valid link, ignore

    if is_job_running():
        await update.message.reply_text(OLDFWD_JOB_RUNNING, parse_mode="HTML")
        return ConversationHandler.END

    resolved = await resolve_chat_from_link(parsed)
    if not resolved:
        await update.message.reply_text(OLDFWD_CHAT_ACCESS_ERROR, parse_mode="HTML")
        return ConversationHandler.END

    if "oldfwd_origin" not in context.user_data:
        context.user_data["oldfwd_origin"] = resolved["chat_id"]
        context.user_data["oldfwd_origin_name"] = resolved["chat_name"]
        context.user_data["oldfwd_start_id"] = resolved["message_id"]

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="oldfwd_cancel")]
        ])

        await update.message.reply_text(
            OLDFWD_START_DETECTED.format(
                chat_name=resolved['chat_name'],
                chat_id=resolved['chat_id'],
                msg_id=resolved['message_id'],
            ),
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return WAITING_END_LINK

    else:
        origin_id = context.user_data.get("oldfwd_origin")
        if resolved["chat_id"] != origin_id:
            await update.message.reply_text(
                OLDFWD_WRONG_CHAT.format(expected=origin_id, got=resolved['chat_id']),
                parse_mode="HTML",
            )
            return WAITING_END_LINK

        start_id = context.user_data.get("oldfwd_start_id")
        end_id = resolved["message_id"]

        if end_id < start_id:
            start_id, end_id = end_id, start_id
            context.user_data["oldfwd_start_id"] = start_id

        context.user_data["oldfwd_end_id"] = end_id
        total = end_id - start_id + 1

        # Refresh chats before showing target selection
        await refresh_joined_chats()
        chats = get_joined_chats_list()
        context.user_data["oldfwd_chats"] = chats  # Store for pagination
        
        # Store range info for pagination
        range_info = {"start_id": start_id, "end_id": end_id, "total": total}
        context.user_data["oldfwd_range_info"] = range_info
        
        # Single message with range confirmed + target selection
        text, keyboard = build_target_keyboard(chats, 0, range_info)
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
        return WAITING_TARGET


async def callback_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle pagination."""
    query = update.callback_query
    await query.answer()

    _, page_str = query.data.split(":")
    page = int(page_str)

    # Use cached chats from context
    chats = context.user_data.get("oldfwd_chats", [])
    if not chats:
        chats = get_joined_chats_list()
        context.user_data["oldfwd_chats"] = chats

    range_info = context.user_data.get("oldfwd_range_info")
    text, keyboard = build_target_keyboard(chats, page, range_info)
    
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass  # Ignore "message not modified" error
    return WAITING_TARGET


async def callback_target_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle target selection — store target and show forwarding options."""
    query = update.callback_query
    await query.answer()

    _, target = query.data.split(":", 1)

    if target == "saved":
        from util.old_forward_client import get_old_client
        client = get_old_client()
        if client:
            me = await client.get_me()
            target_id = me.id
            target_name = "Saved Messages"
        else:
            await query.edit_message_text(OLDFWD_CLIENT_NOT_READY, parse_mode="HTML")
            _clear_context(context)
            return ConversationHandler.END
    else:
        target_id = int(target)
        chats = context.user_data.get("oldfwd_chats", get_joined_chats_list())
        chat = next((c for c in chats if c["id"] == target_id), None)
        target_name = chat["title"] if chat else f"Chat {target_id}"

    origin_id = context.user_data.get("oldfwd_origin")
    start_id = context.user_data.get("oldfwd_start_id")
    end_id = context.user_data.get("oldfwd_end_id")

    if not all([origin_id, start_id, end_id]):
        await query.edit_message_text(OLDFWD_SESSION_EXPIRED, parse_mode="HTML")
        _clear_context(context)
        return ConversationHandler.END

    # Store target and initialise options with defaults
    context.user_data["oldfwd_target_id"] = target_id
    context.user_data["oldfwd_target_name"] = target_name
    context.user_data["oldfwd_forward_messages"] = True
    context.user_data["oldfwd_forward_album"] = True

    text, keyboard = _build_options_keyboard(True, True)
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    return WAITING_OPTIONS


def _build_options_keyboard(forward_messages: bool, forward_album: bool) -> tuple[str, InlineKeyboardMarkup]:
    """Build the forwarding options selection keyboard."""
    msg_on  = "✅ Messages"  if forward_messages else "Messages"
    msg_off = "Messages" if forward_messages else "❌Messages"
    alb_on  = "Album"     if forward_album    else "Album"
    alb_off = "Album"   if forward_album    else "❌Album"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(msg_on,  callback_data="oldfwd_opt:msg:1"),
            InlineKeyboardButton(msg_off, callback_data="oldfwd_opt:msg:0"),
        ],
        [
            InlineKeyboardButton(alb_on,  callback_data="oldfwd_opt:album:1"),
            InlineKeyboardButton(alb_off, callback_data="oldfwd_opt:album:0"),
        ],
        [InlineKeyboardButton("•Start Now•", callback_data="oldfwd_opt:start")],
        [InlineKeyboardButton("❌ Cancel", callback_data="oldfwd_cancel")],
    ])
    return OLDFWD_OPTIONS, keyboard


async def callback_options_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Toggle a forwarding option (messages / album)."""
    query = update.callback_query
    parts = query.data.split(":")
    opt_type, value_str = parts[1], parts[2]
    value = value_str == "1"

    if opt_type == "msg":
        context.user_data["oldfwd_forward_messages"] = value
    elif opt_type == "album":
        context.user_data["oldfwd_forward_album"] = value

    await query.answer("Updated!")
    fwd_msg = context.user_data.get("oldfwd_forward_messages", True)
    fwd_alb = context.user_data.get("oldfwd_forward_album", True)
    text, keyboard = _build_options_keyboard(fwd_msg, fwd_alb)
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        log.debug(f"[OldForward] callback_options_toggle edit failed: {e}", exc_info=True)
    return WAITING_OPTIONS


async def callback_options_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Confirm options and start the forward job."""
    query = update.callback_query
    await query.answer("Starting...")

    origin_id   = context.user_data.get("oldfwd_origin")
    origin_name = context.user_data.get("oldfwd_origin_name")
    start_id    = context.user_data.get("oldfwd_start_id")
    end_id      = context.user_data.get("oldfwd_end_id")
    target_id   = context.user_data.get("oldfwd_target_id")
    target_name = context.user_data.get("oldfwd_target_name")
    fwd_msg     = context.user_data.get("oldfwd_forward_messages", True)
    fwd_alb     = context.user_data.get("oldfwd_forward_album", True)

    if not all([origin_id, start_id, end_id, target_id]):
        await query.edit_message_text(OLDFWD_SESSION_EXPIRED, parse_mode="HTML")
        _clear_context(context)
        return ConversationHandler.END

    job_id = f"{origin_id}_{start_id}_{end_id}_{datetime.utcnow().timestamp()}"
    if not await acquire_job_lock(job_id):
        await query.edit_message_text(OLDFWD_ANOTHER_JOB, parse_mode="HTML")
        _clear_context(context)
        return ConversationHandler.END

    db_job_id = await create_job({
        "owner_id": update.effective_user.id,
        "origin_chat_id": origin_id,
        "origin_chat_name": origin_name,
        "target_chat_id": target_id,
        "target_chat_name": target_name,
        "start_msg_id": start_id,
        "end_msg_id": end_id,
    })

    _clear_context(context)

    asyncio.create_task(_run_forward_job(
        query=query,
        job_id=db_job_id,
        origin_id=origin_id,
        origin_name=origin_name,
        target_id=target_id,
        target_name=target_name,
        start_id=start_id,
        end_id=end_id,
        forward_messages=fwd_msg,
        forward_album=fwd_alb,
    ))

    return ConversationHandler.END


async def callback_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the old forward flow."""
    query = update.callback_query
    await query.answer("Cancelled")

    _clear_context(context)
    await query.edit_message_text(OLDFWD_CANCELLED, parse_mode="HTML")
    return ConversationHandler.END


async def callback_refresh_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Refresh joined chats cache."""
    query = update.callback_query
    await query.answer("Refreshing...")

    await refresh_joined_chats()
    chats = get_joined_chats_list()
    context.user_data["oldfwd_chats"] = chats
    
    range_info = context.user_data.get("oldfwd_range_info")
    text, keyboard = build_target_keyboard(chats, 0, range_info)
    
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass  # Ignore "message not modified" error
    return WAITING_TARGET


def _clear_context(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear old forward data from context."""
    keys = [
        "oldfwd_origin", "oldfwd_origin_name", "oldfwd_start_id", "oldfwd_end_id",
        "oldfwd_chats", "oldfwd_range_info",
        "oldfwd_target_id", "oldfwd_target_name",
        "oldfwd_forward_messages", "oldfwd_forward_album",
    ]
    for key in keys:
        context.user_data.pop(key, None)


async def _run_forward_job(
    query,
    job_id: str,
    origin_id: int,
    origin_name: str,
    target_id: int,
    target_name: str,
    start_id: int,
    end_id: int,
    forward_messages: bool = True,
    forward_album: bool = True,
) -> None:
    """Run the forward job with progress updates."""
    total = end_id - start_id + 1
    forwarded = 0
    failed = 0
    start_time = datetime.utcnow()
    last_update = start_time
    cancelled = False

    log.info(
        f"[OldForward] Starting job {job_id}: {origin_name} -> {target_name} "
        f"[{start_id}-{end_id}] forward_messages={forward_messages} forward_album={forward_album}"
    )

    # Album buffer: collect consecutive album-member messages before sending as group
    current_album_group: str | None = None
    album_msg_ids: list[int] = []

    async def flush_album() -> None:
        nonlocal forwarded, failed, current_album_group, album_msg_ids
        if album_msg_ids and current_album_group:
            f, fa = await forward_album_group(origin_id, target_id, album_msg_ids)
            forwarded += f
            failed += fa
        current_album_group = None
        album_msg_ids = []

    try:
        progress_msg = await query.edit_message_text(
            _build_progress_text(origin_name, target_name, total, 0, 0, 0),
            parse_mode="HTML",
            reply_markup=_build_stop_keyboard(job_id),
        )

        for msg_id in range(start_id, end_id + 1):
            # Check stop signal first
            if is_stop_requested(job_id):
                cancelled = True
                break

            success, error, group_id = await forward_single_message(
                origin_id, target_id, msg_id,
                forward_messages=forward_messages,
                forward_album=forward_album,
            )

            if error == "ALBUM_MEMBER" and group_id:
                # Buffer this album member — flush first if the group changed
                if group_id != current_album_group:
                    await flush_album()
                    current_album_group = group_id
                album_msg_ids.append(msg_id)
            else:
                # Flush any pending album before processing a non-album message
                await flush_album()

                if error == "SKIPPED":
                    pass  # Text-only message silently skipped
                elif success:
                    forwarded += 1
                else:
                    if error in ("CHAT_ADMIN_REQUIRED", "CHAT_WRITE_FORBIDDEN"):
                        log.warning(f"[OldForward] No permission in target chat, aborting job")
                        raise PermissionError(f"NO_PERMISSION:{origin_name}:{target_name}")
                    failed += 1
                    log.debug(f"[OldForward] Msg {msg_id} failed: {error}")

            now = datetime.utcnow()
            elapsed = (now - start_time).total_seconds()

            if (now - last_update).total_seconds() >= 5:
                last_update = now
                try:
                    await progress_msg.edit_text(
                        _build_progress_text(
                            origin_name, target_name, total,
                            forwarded + failed, forwarded, failed, elapsed
                        ),
                        parse_mode="HTML",
                        reply_markup=_build_stop_keyboard(job_id),
                    )
                except Exception:
                    pass  # Ignore edit errors

            await asyncio.sleep(1)
            if (forwarded + failed) % 20 == 0:
                await update_job_progress(job_id, forwarded, failed)

        # Flush any remaining buffered album
        await flush_album()

        elapsed = (datetime.utcnow() - start_time).total_seconds()

        if cancelled:
            await complete_job(job_id, "cancelled")
            await update_job_progress(job_id, forwarded, failed)
            try:
                await progress_msg.edit_text(
                    OLDFWD_STOPPED.format(
                        origin=origin_name,
                        target=target_name,
                        forwarded=forwarded,
                        failed=failed,
                        time=format_duration(elapsed),
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        else:
            await complete_job(job_id, "completed")
            await update_job_progress(job_id, forwarded, failed)
            try:
                await progress_msg.edit_text(
                    OLDFWD_COMPLETE.format(
                        origin=origin_name,
                        target=target_name,
                        forwarded=forwarded,
                        failed=failed,
                        time=format_duration(elapsed),
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass

    except PermissionError as e:
        error_msg = str(e)
        if error_msg.startswith("NO_PERMISSION:"):
            parts = error_msg.split(":")
            origin = parts[1] if len(parts) > 1 else origin_name
            target = parts[2] if len(parts) > 2 else target_name
        else:
            origin = origin_name
            target = target_name

        log.warning(f"[OldForward] Job aborted - no permission in target")
        await complete_job(job_id, "failed", "No permission to send messages")
        try:
            await progress_msg.edit_text(
                OLDFWD_NO_PERMISSION.format(origin=origin, target=target),
                parse_mode="HTML",
            )
        except Exception:
            pass

    except Exception as e:
        log.error(f"[OldForward] Job error: {e}", exc_info=True)
        await complete_job(job_id, "failed", str(e)[:200])
        try:
            await query.edit_message_text(
                OLDFWD_FAILED.format(
                    error=str(e)[:200],
                    forwarded=forwarded,
                    failed=failed,
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    finally:
        clear_stop_request(job_id)
        release_job_lock()


def _build_progress_text(
    origin_name: str,
    target_name: str,
    total: int,
    processed: int,
    forwarded: int,
    failed: int,
    elapsed: float = 0,
) -> str:
    """Build progress display text."""
    percent = int((processed / total) * 100) if total > 0 else 0
    bar = build_progress_bar(processed, total)

    return OLDFWD_PROGRESS.format(
        origin=origin_name,
        target=target_name,
        total=total,
        bar=bar,
        percent=percent,
        forwarded=forwarded,
        failed=failed,
        elapsed=format_duration(elapsed),
    )

async def callback_stop_forward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 🛑 Stop Forwarding button — signal the running job to stop."""
    query = update.callback_query
    if not is_owner(query.from_user.id):
        await query.answer("Unauthorized", show_alert=True)
        return

    job_id = query.data.split(":", 1)[1]
    request_stop(job_id)

    await query.answer("Stopped by you baby ✋", show_alert=True)
    try:
        await query.edit_message_text(
            "⏳ <b>Stopping forwarding...</b>",
            parse_mode="HTML",
        )
    except Exception as e:
        log.error(f"[OldForward] callback_stop_forward failed: {e}", exc_info=True)
        pass  # Task will overwrite this with the final status shortly


def register(app: Application) -> None:
    """Register plugin handlers."""
    import warnings
    from telegram.warnings import PTBUserWarning

    app.add_handler(CommandHandler("oldforward", oldforward_cmd))

    # Stop handler — registered globally (job runs outside the conversation)
    app.add_handler(CallbackQueryHandler(callback_stop_forward, pattern=r"^oldfwd_stop:"))
    app.add_handler(CommandHandler("old", oldforward_cmd))

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=PTBUserWarning, message=".*per_message.*")

        conv_handler = ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & filters.User(OWNER_IDS) &
                    filters.Regex(r't\.me/'),
                    handle_link_message
                ),
            ],
            states={
                WAITING_END_LINK: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND & filters.User(OWNER_IDS),
                        handle_link_message
                    ),
                    CallbackQueryHandler(callback_cancel, pattern=r"^oldfwd_cancel$"),
                ],
                WAITING_TARGET: [
                    CallbackQueryHandler(callback_target_select, pattern=r"^oldfwd_target:"),
                    CallbackQueryHandler(callback_page, pattern=r"^oldfwd_page:"),
                    CallbackQueryHandler(callback_refresh_chats, pattern=r"^oldfwd_refresh$"),
                    CallbackQueryHandler(callback_cancel, pattern=r"^oldfwd_cancel$"),
                ],
                WAITING_OPTIONS: [
                    CallbackQueryHandler(callback_options_toggle, pattern=r"^oldfwd_opt:(?:msg|album):"),
                    CallbackQueryHandler(callback_options_start, pattern=r"^oldfwd_opt:start$"),
                    CallbackQueryHandler(callback_cancel, pattern=r"^oldfwd_cancel$"),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", lambda u, c: _cancel_cmd(u, c)),
                CallbackQueryHandler(callback_cancel, pattern=r"^oldfwd_cancel$"),
            ],
            per_user=True,
            per_chat=True,
            per_message=False,
        )
    app.add_handler(conv_handler)

    log.info("[OldForward] Plugin registered.")


async def _cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel command."""
    _clear_context(context)
    await update.message.reply_text(OLDFWD_CANCELLED, parse_mode="HTML")
    return ConversationHandler.END
