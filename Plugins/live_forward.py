"""
Live Forwarder Plugin - Forward messages from origin to target channels.
Handles: /live command, add/delete/toggle forwarders, owner UI.
"""
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
from util.forward_queue import (
    get_all_forwarders,
    get_forwarder_by_id,
    get_forwarder_by_origin_target,
    create_forwarder,
    update_forwarder_status,
    delete_forwarder,
    get_forwarder_queue_stats,
)
from util.forward_client import (
    is_forward_client_ready,
    get_chat_info,
    validate_chat_access,
    refresh_forwarder_cache,
    add_forwarder_to_cache,
    remove_forwarder_from_cache,
)
from util.responses import LIVEFWD_OPTIONS

# Conversation states
WAITING_ORIGIN = 1
WAITING_TARGET = 2
WAITING_OPTIONS = 3


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def normalize_chat_id(chat_id: int) -> int:
    """
    Normalize chat ID to Telegram format.
    Channels/supergroups use -100 prefix.
    If user enters without -100, we prepend it.
    """
    if chat_id > 0:
        # Positive ID - prepend -100
        return int(f"-100{chat_id}")
    elif chat_id > -100:
        # Small negative (shouldn't happen for groups, but handle it)
        return int(f"-100{abs(chat_id)}")
    elif not str(chat_id).startswith("-100"):
        # Negative but doesn't start with -100
        return int(f"-100{abs(chat_id)}")
    # Already has -100 prefix
    return chat_id


async def build_forwarders_message() -> tuple[str, InlineKeyboardMarkup]:
    """Build the forwarders list message and keyboard."""
    forwarders = await get_all_forwarders()
    
    # Get current time for last update
    timestamp = datetime.now().strftime("%H:%M")
    
    if not forwarders:
        text = (
            f"<b>LIVE FORWARDER CONFIG LIST</b>\n"
            f"<blockquote><b>Last Update≽ {timestamp} </b></blockquote>\n\n"
            "<blockquote><b>• Currently, No Active Processes Are Being Handled In The Live Forwarder</b></blockquote>\n"
            "<b>Click The Button Below To Add A New</b>"
        )
        keyboard = [[InlineKeyboardButton("➕ Add New Forwarder", callback_data="fwd_add")]]
        return text, InlineKeyboardMarkup(keyboard)
    
    text = f"<b>LIVE FORWARD STATUS</b>\nLast Update &gt; {timestamp}\n\n"
    
    keyboard = []
    for i, fw in enumerate(forwarders, 1):
        fwd_id = str(fw["_id"])
        origin_name = fw.get("origin_chat_name", "Unknown")
        target_name = fw.get("target_chat_name", "Unknown")
        is_active = fw.get("is_active", False)
        
        # Get per-forwarder queue stats
        stats = await get_forwarder_queue_stats(fwd_id)
        queue_count = stats.get("queue", 0)
        pending_count = stats.get("pending", 0)
        failed_count = stats.get("failed", 0)
        
        status = "Active" if is_active else "Inactive"
        
        text += (
            f"<b>S{i}. {origin_name}</b>\n"
            f"• Target &gt; {target_name}\n"
            f"• Status &gt; {status}\n"
            f"<blockquote>• Queue {queue_count:02d} •Pending :{pending_count:02d} •Failed :{failed_count:02d}</blockquote>\n\n"
        )
        
        # Buttons for this forwarder
        toggle_text = " Disable" if is_active else "Enable"
        toggle_data = f"fwd_toggle:{fwd_id}:{'0' if is_active else '1'}"
        
        keyboard.append([
            InlineKeyboardButton(f"#{i} {toggle_text}", callback_data=toggle_data),
            InlineKeyboardButton("🗑 Delete", callback_data=f"fwd_del:{fwd_id}"),
        ])
    
    # Add new forwarder button at the end
    keyboard.append([InlineKeyboardButton(" Add New Forwarder", callback_data="fwd_add")])
    keyboard.append([InlineKeyboardButton("Refresh", callback_data="fwd_refresh")])
    
    return text, InlineKeyboardMarkup(keyboard)


# ─────────────────────────────────────────────────────────────────────────────
# Command Handler
# ─────────────────────────────────────────────────────────────────────────────

@owner_only
async def forward_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /live command - show all forwarders."""
    if not is_forward_client_ready():
        await update.message.reply_text(
            "⚠️ <b>Forward client not ready</b>\n\n"
            "FORWARDING_STRING is not configured or client failed to start.\n"
            "Check your config and logs.",
            parse_mode="HTML",
        )
        return
    
    text, keyboard = await build_forwarders_message()
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")


# ─────────────────────────────────────────────────────────────────────────────
# Callback Handlers
# ─────────────────────────────────────────────────────────────────────────────

async def callback_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Refresh forwarders list."""
    query = update.callback_query
    await query.answer("Refreshing...")
    
    text, keyboard = await build_forwarders_message()
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        log.debug(f"[LiveForward] callback_refresh edit failed: {e}", exc_info=True)
        pass  # Ignore 'message not modified' error


async def callback_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle forwarder status."""
    query = update.callback_query
    _, fwd_id, new_status = query.data.split(":")
    is_active = new_status == "1"
    
    await update_forwarder_status(fwd_id, is_active)
    await refresh_forwarder_cache()
    
    status_text = "enabled" if is_active else "disabled"
    await query.answer(f"Forwarder {status_text}!")
    
    text, keyboard = await build_forwarders_message()
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        log.debug(f"[LiveForward] callback_toggle edit failed: {e}", exc_info=True)
        pass  # Ignore 'message not modified' error


async def callback_delete_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show delete confirmation."""
    query = update.callback_query
    _, fwd_id = query.data.split(":")
    
    forwarder = await get_forwarder_by_id(fwd_id)
    if not forwarder:
        await query.answer("Forwarder not found!", show_alert=True)
        return
    
    origin_name = forwarder.get("origin_chat_name", "Unknown")
    target_name = forwarder.get("target_chat_name", "Unknown")
    
    text = (
        f"⚠️ <b>Delete Forwarder?</b>\n\n"
        f"<b>From:</b> {origin_name}\n"
        f"<b>To:</b> {target_name}\n\n"
        f"This action cannot be undone."
    )
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, Delete", callback_data=f"fwd_del_confirm:{fwd_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data="fwd_del_cancel"),
        ]
    ])
    
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")


async def callback_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm and delete forwarder."""
    query = update.callback_query
    _, fwd_id = query.data.split(":")
    
    await delete_forwarder(fwd_id)
    await refresh_forwarder_cache()  # Full refresh to ensure cache is synced
    
    await query.answer("Forwarder deleted!")
    
    text, keyboard = await build_forwarders_message()
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        log.debug(f"[LiveForward] callback_delete_confirm edit failed: {e}", exc_info=True)
        pass  # Ignore 'message not modified' error


async def callback_delete_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel delete and go back to list."""
    query = update.callback_query
    await query.answer("Cancelled")
    
    text, keyboard = await build_forwarders_message()
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        log.debug(f"[LiveForward] callback_delete_cancel edit failed: {e}", exc_info=True)
        pass  # Ignore 'message not modified' error


# ─────────────────────────────────────────────────────────────────────────────
# Add Forwarder Conversation
# ─────────────────────────────────────────────────────────────────────────────

async def callback_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start add forwarder conversation."""
    query = update.callback_query
    await query.answer()
    
    if not is_forward_client_ready():
        await query.edit_message_text(
            "⚠️ Forward client not ready. Check FORWARDING_STRING config.",
            parse_mode="HTML",
        )
        return ConversationHandler.END
    
    text = (
        "<b>ADD NEW FORWARDER</b>\n"
        "<b>Please Send Me The Source Channel ID To Begin Forwarding. & Store in DataBase</b>\n"
        "<blockquote><b>• Make Sure UserBot Already Joined </b></blockquote>\n"
        "<blockquote><b>• Provide The Channel ID Without The '-100'</b></blockquote>"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="fwd_add_cancel")]
    ])
    
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    return WAITING_ORIGIN


async def receive_origin_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive and validate origin chat ID."""
    text = update.message.text.strip()
    
    try:
        origin_id = int(text)
        # Normalize: add -100 prefix if not present
        origin_id = normalize_chat_id(origin_id)
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid chat ID. Please send a numeric ID.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="fwd_add_cancel")]
            ]),
        )
        return WAITING_ORIGIN
    
    # Validate access
    success, error = await validate_chat_access(origin_id)
    if not success:
        await update.message.reply_text(
            f"<blockquote>❌ Cannot Access Chat: {error} </blockquote>\n\n"
            "<b>• Make sure the userbot is a member</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="fwd_add_cancel")]
            ]),
        )
        return WAITING_ORIGIN
    
    # Get chat info
    chat_info = await get_chat_info(origin_id)
    if not chat_info:
        await update.message.reply_text(
            "❌ Could not get chat info. Please try again.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="fwd_add_cancel")]
            ]),
        )
        return WAITING_ORIGIN
    
    # Store in context
    context.user_data["fwd_origin_id"] = origin_id
    context.user_data["fwd_origin_name"] = chat_info["title"]
    
    text = (
        f"<b>NEW SOURCE FOUND ✨</b>\n\n"
        f"<b>• Name≽ </b> {chat_info['title']}\n"
        f"<b>• ChannelID≽  </b> <code>{origin_id}</code>\n"
        f"<blockquote><b>Now, Send Me The Target Chat ID\n Where You Want To Start Sending....</b></blockquote>"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="fwd_add_cancel")]
    ])
    
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    return WAITING_TARGET


async def receive_target_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive and validate target chat ID, then show forwarding options."""
    text = update.message.text.strip()

    try:
        target_id = int(text)
        # Normalize: add -100 prefix if not present
        target_id = normalize_chat_id(target_id)
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid chat ID. Please send a numeric ID.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="fwd_add_cancel")]
            ]),
        )
        return WAITING_TARGET

    # Validate access
    success, error = await validate_chat_access(target_id)
    if not success:
        await update.message.reply_text(
            f"❌ Cannot access chat: {error}\n\n"
            "Make sure the userbot is a member/admin of this chat.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="fwd_add_cancel")]
            ]),
        )
        return WAITING_TARGET

    # Get chat info
    chat_info = await get_chat_info(target_id)
    if not chat_info:
        await update.message.reply_text(
            "❌ Could not get chat info. Please try again.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="fwd_add_cancel")]
            ]),
        )
        return WAITING_TARGET

    # Get origin info from context
    origin_id = context.user_data.get("fwd_origin_id")
    origin_name = context.user_data.get("fwd_origin_name")

    if not origin_id:
        await update.message.reply_text("❌ Session expired. Please start again with /live")
        return ConversationHandler.END

    # Check if forwarder already exists
    existing = await get_forwarder_by_origin_target(origin_id, target_id)
    if existing:
        status = "• Active" if existing.get("is_active", False) else "• Inactive"
        await update.message.reply_text(
            f"⚠️<b>FORWARDE4 ALREADY EXIST</b>\n\n"
            f"<b>• Source≽ </b> {origin_name}\n"
            f"<b>• Target ≽</b> {chat_info['title']}\n"
            f"<blockquote><b>Current Status: {status}\n Use /live To Manage Forwarders.</b></blockquote>",
            parse_mode="HTML",
        )
        context.user_data.pop("fwd_origin_id", None)
        context.user_data.pop("fwd_origin_name", None)
        return ConversationHandler.END

    # Store target and initialise options with defaults
    context.user_data["fwd_target_id"] = target_id
    context.user_data["fwd_target_name"] = chat_info["title"]
    context.user_data["fwd_forward_messages"] = True
    context.user_data["fwd_forward_album"] = True

    text_msg, keyboard = _build_fwd_options_keyboard(True, True)
    await update.message.reply_text(text_msg, reply_markup=keyboard, parse_mode="HTML")
    return WAITING_OPTIONS


def _build_fwd_options_keyboard(forward_messages: bool, forward_album: bool) -> tuple[str, InlineKeyboardMarkup]:
    """Build the live forwarder options selection keyboard."""
    msg_on  = "✅ Messages"  if forward_messages else "Messages"
    msg_off = " Messages" if forward_messages else "❌ Messages"
    alb_on  = "✅ Album"     if forward_album    else "Album"
    alb_off = "Album"   if forward_album    else "❌ Album"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(msg_on,  callback_data="fwd_opt:msg:1"),
            InlineKeyboardButton(msg_off, callback_data="fwd_opt:msg:0"),
        ],
        [
            InlineKeyboardButton(alb_on,  callback_data="fwd_opt:album:1"),
            InlineKeyboardButton(alb_off, callback_data="fwd_opt:album:0"),
        ],
        [InlineKeyboardButton("•Start Now• ", callback_data="fwd_opt:confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="fwd_add_cancel")],
    ])
    return LIVEFWD_OPTIONS, keyboard


async def callback_fwd_options_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Toggle a forwarder option (messages / album)."""
    query = update.callback_query
    parts = query.data.split(":")
    opt_type, value_str = parts[1], parts[2]
    value = value_str == "1"

    if opt_type == "msg":
        context.user_data["fwd_forward_messages"] = value
    elif opt_type == "album":
        context.user_data["fwd_forward_album"] = value

    await query.answer("Updated!")
    fwd_msg = context.user_data.get("fwd_forward_messages", True)
    fwd_alb = context.user_data.get("fwd_forward_album", True)
    text, keyboard = _build_fwd_options_keyboard(fwd_msg, fwd_alb)
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        log.debug(f"[LiveForward] callback_fwd_options_toggle edit failed: {e}", exc_info=True)
        pass
    return WAITING_OPTIONS


async def callback_fwd_options_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Confirm options and create the forwarder."""
    query = update.callback_query
    await query.answer()

    origin_id   = context.user_data.get("fwd_origin_id")
    origin_name = context.user_data.get("fwd_origin_name")
    target_id   = context.user_data.get("fwd_target_id")
    target_name = context.user_data.get("fwd_target_name")
    fwd_msg     = context.user_data.get("fwd_forward_messages", True)
    fwd_alb     = context.user_data.get("fwd_forward_album", True)

    if not all([origin_id, target_id]):
        await query.edit_message_text(
            "❌ Session expired. Please start again with /live",
            parse_mode="HTML",
        )
        _clear_fwd_context(context)
        return ConversationHandler.END

    # Create forwarder with chosen settings
    forwarder_id = await create_forwarder(
        origin_chat_id=origin_id,
        origin_chat_name=origin_name,
        target_chat_id=target_id,
        target_chat_name=target_name,
        added_by=query.from_user.id,
        forward_messages=fwd_msg,
        forward_album=fwd_alb,
    )

    # Add to cache and refresh listeners
    forwarder = await get_forwarder_by_id(forwarder_id)
    if forwarder:
        await add_forwarder_to_cache(forwarder)

    log.info(
        f"[LiveForward] Created forwarder {forwarder_id}: {origin_name} -> {target_name} "
        f"msg={fwd_msg} album={fwd_alb}"
    )

    _clear_fwd_context(context)

    mode_parts = []
    mode_parts.append("✅MSG" if fwd_msg else "❌MSG")
    mode_parts.append("✅ALBUM" if fwd_alb else "❌ ALBUM")
    mode_str = " ≼:≽ ".join(mode_parts)

    text = (
        "<blockquote><b>NEW LIVE FORWARDER ADDED!!</b></blockquote>\n\n"
        f"<b>• Source≽ </b> {origin_name} \n"
        f"<b>• Target ≽ </b> {target_name} \n"
        f"<b>• Mode ≽  {mode_str} </b>\n"
        f"<blockquote><b>Current Status: •Active \n Use /live To Manage Forwarders.</b></blockquote>\n"
    )

    await query.edit_message_text(text, parse_mode="HTML")
    return ConversationHandler.END


def _clear_fwd_context(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear all add-forwarder context keys."""
    for key in ("fwd_origin_id", "fwd_origin_name", "fwd_target_id", "fwd_target_name",
                "fwd_forward_messages", "fwd_forward_album"):
        context.user_data.pop(key, None)


async def callback_add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel add forwarder conversation."""
    query = update.callback_query
    await query.answer("Cancelled")

    _clear_fwd_context(context)

    text, keyboard = await build_forwarders_message()
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        log.debug(f"[LiveForward] callback_add_cancel edit failed: {e}", exc_info=True)
        pass  # Ignore 'message not modified' error
    return ConversationHandler.END


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel during conversation."""
    _clear_fwd_context(context)

    await update.message.reply_text("❌ Cancelled. Use /live to see forwarders.")
    return ConversationHandler.END


# ─────────────────────────────────────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────────────────────────────────────

def register(app: Application) -> None:
    """Register plugin handlers."""
    import warnings
    from telegram.warnings import PTBUserWarning

    # Main command
    app.add_handler(CommandHandler("forward", forward_cmd))
    app.add_handler(CommandHandler("live", forward_cmd))

    # Suppress the per_message warning for this specific handler
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=PTBUserWarning, message=".*per_message.*")

        # Conversation handler for adding new forwarder
        conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(callback_add_start, pattern=r"^fwd_add$"),
            ],
            states={
                WAITING_ORIGIN: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND & filters.User(OWNER_IDS), receive_origin_id),
                    CallbackQueryHandler(callback_add_cancel, pattern=r"^fwd_add_cancel$"),
                ],
                WAITING_TARGET: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND & filters.User(OWNER_IDS), receive_target_id),
                    CallbackQueryHandler(callback_add_cancel, pattern=r"^fwd_add_cancel$"),
                ],
                WAITING_OPTIONS: [
                    CallbackQueryHandler(callback_fwd_options_toggle, pattern=r"^fwd_opt:(?:msg|album):"),
                    CallbackQueryHandler(callback_fwd_options_confirm, pattern=r"^fwd_opt:confirm$"),
                    CallbackQueryHandler(callback_add_cancel, pattern=r"^fwd_add_cancel$"),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", cancel_conversation),
                CallbackQueryHandler(callback_add_cancel, pattern=r"^fwd_add_cancel$"),
            ],
            per_user=True,
            per_chat=True,
            per_message=False,
        )
    app.add_handler(conv_handler)

    # Callback handlers (outside conversation)
    app.add_handler(CallbackQueryHandler(callback_refresh, pattern=r"^fwd_refresh$"))
    app.add_handler(CallbackQueryHandler(callback_toggle, pattern=r"^fwd_toggle:"))
    app.add_handler(CallbackQueryHandler(callback_delete_prompt, pattern=r"^fwd_del:[^_]"))
    app.add_handler(CallbackQueryHandler(callback_delete_confirm, pattern=r"^fwd_del_confirm:"))
    app.add_handler(CallbackQueryHandler(callback_delete_cancel, pattern=r"^fwd_del_cancel$"))

    log.info("[LiveForward] Plugin registered.")
