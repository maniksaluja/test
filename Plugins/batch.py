"""
Batch Link Plugin - Create shareable batch links for media collections.
Handles: /batch, /makeit, /cancel, /batches, /editb commands.
Owner creates batches, users request via deep link, owner approves/declines.
"""
import asyncio
import random
import time
from datetime import datetime
from typing import Optional

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

from config import BOT_USERNAME, OWNER_IDS
from util.logging import log
from util.owner import owner_only, is_owner
from util.db import batches_col, batch_requests_col, users_col
from util.responses import (
    BATCH_STARTED,
    BATCH_EDIT_STARTED,
    BATCH_CREATED,
    BATCH_UPDATED,
    BATCH_NOT_FOUND,
    BATCH_CANCELLED,
    BATCH_EMPTY,
    BATCH_NO_ACTIVE,
    BATCH_ALREADY_ACTIVE,
    BATCH_LIST_HEADER,
    BATCH_LIST_EMPTY,
    BATCH_LIST_ITEM,
    BATCH_REQUEST_SENT,
    BATCH_INACTIVE,
    BATCH_ACCESS_DECLINED,
    BATCH_OWNER_REQUEST,
    SEND_BATCH_START_MSG,
    BATCH_START_MSG,
    BATCH_END_MSG,
)
from util.batch_cron import has_sending_batch, process_next_batch_for_user, deliver_batch_content
from util.tasks import create_task as tasks_create_task

# Conversation states
COLLECTING_MESSAGES = 1

# In-memory batch sessions: {user_id: {"messages": [], "started_at": datetime, "editing": batch_id|None}}
_batch_sessions: dict[int, dict] = {}

# Session timeout in seconds (30 minutes)
SESSION_TIMEOUT = 4000


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


## OLD BATCH GENERATOR
# async def generate_batch_id() -> str:
#     """Generate a sequential numeric batch ID starting from 100888800001."""
#     cursor = batches_col().find(
#         {"batch_id": {"$regex": r"^\d+$"}},
#         {"batch_id": 1}
#     ).sort("batch_id", -1).limit(1)
    
#     docs = await cursor.to_list(length=1)
#     if docs:
#         try:
#             last_id = int(docs[0]["batch_id"])
#             return str(last_id + 1)
#         except (ValueError, KeyError):
#             pass
    
#     return "100888800001"


def generate_batch_id() -> str:
    """Generate a batch ID: 6 random digits followed by unix timestamp."""
    prefix = random.randint(100000, 999999)
    timestamp = int(time.time())
    return f"{prefix}{timestamp}"


def format_datetime(dt: Optional[datetime]) -> str:
    """Format datetime for display."""
    if not dt:
        return "N/A"
    return dt.strftime("%d %b %Y, %H:%M")


async def get_batch_by_id(batch_id: str) -> Optional[dict]:
    """Find batch by batch_id."""
    return await batches_col().find_one({"batch_id": batch_id.upper()})


async def get_chat_name(bot, chat_id: int) -> str:
    """Try to get chat name, return ID if fails."""
    try:
        chat = await bot.get_chat(chat_id)
        return chat.title or chat.full_name or str(chat_id)
    except Exception:
        return str(chat_id)


def get_source_summary(messages: list) -> str:
    """Get a summary - now shows 'Bot DM' since all messages are stored locally."""
    if not messages:
        return "Empty"
    return "Bot DM"


def is_session_active(user_id: int) -> bool:
    """Check if user has an active batch session."""
    if user_id not in _batch_sessions:
        return False
    session = _batch_sessions[user_id]
    # Check timeout
    elapsed = (datetime.utcnow() - session["started_at"]).total_seconds()
    if elapsed > SESSION_TIMEOUT:
        del _batch_sessions[user_id]
        return False
    return True


def clear_session(user_id: int) -> None:
    """Clear user's batch session."""
    _batch_sessions.pop(user_id, None)


# ─────────────────────────────────────────────────────────────────────────────
# Owner Commands: /batch, /makeit, /cancel, /batches, /editb
# ─────────────────────────────────────────────────────────────────────────────

@owner_only
async def batch_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start batch creation mode."""
    user_id = update.effective_user.id
    
    # Check if already in batch mode
    if is_session_active(user_id):
        await update.message.reply_text(BATCH_ALREADY_ACTIVE, parse_mode="HTML")
        return COLLECTING_MESSAGES
    
    # Start new session
    _batch_sessions[user_id] = {
        "messages": [],
        "started_at": datetime.utcnow(),
        "editing": None,
    }
    
    await update.message.reply_text(BATCH_STARTED, parse_mode="HTML")
    return COLLECTING_MESSAGES


@owner_only
async def editb_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Edit existing batch - add more messages."""
    user_id = update.effective_user.id
    
    # Check args
    if not context.args:
        await update.message.reply_text(
            "❌ Usage: /editb &lt;batch_id&gt;\nExample: /editb ABC123",
            parse_mode="HTML"
        )
        return ConversationHandler.END
    
    batch_id = context.args[0].upper()
    
    # Check if already in batch mode
    if is_session_active(user_id):
        await update.message.reply_text(BATCH_ALREADY_ACTIVE, parse_mode="HTML")
        return COLLECTING_MESSAGES
    
    # Find batch
    batch = await get_batch_by_id(batch_id)
    if not batch:
        await update.message.reply_text(BATCH_NOT_FOUND, parse_mode="HTML")
        return ConversationHandler.END
    
    # Start edit session
    _batch_sessions[user_id] = {
        "messages": [],
        "started_at": datetime.utcnow(),
        "editing": batch_id,
    }
    
    await update.message.reply_text(
        BATCH_EDIT_STARTED.format(batch_id=batch_id, count=len(batch.get("messages", []))),
        parse_mode="HTML"
    )
    return COLLECTING_MESSAGES


async def receive_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive forwarded/sent messages and add to batch.
    
    IMPORTANT: We always store the message ID from the bot's DM (not the original source).
    This ensures the batch remains valid even if the original group bans/removes the bot.
    The bot always has access to its own DM history.
    """
    user_id = update.effective_user.id
    message = update.message
    
    if not is_session_active(user_id):
        # Session expired or not started
        return ConversationHandler.END
    
    session = _batch_sessions[user_id]
    
    # ALWAYS use the message in bot's DM - this is the key to reliability!
    # Even for forwarded messages, we store the DM copy, not the original source.
    chat_id = message.chat_id      # The DM (owner's user_id)
    msg_id = message.message_id    # The message ID in this DM
    
    # Add to session
    msg_entry = {"chat_id": chat_id, "message_id": msg_id}
    session["messages"].append(msg_entry)
    
    # No confirmation message - just silently add
    return COLLECTING_MESSAGES


@owner_only
async def makeit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save the batch to database."""
    user_id = update.effective_user.id
    
    if not is_session_active(user_id):
        await update.message.reply_text(BATCH_NO_ACTIVE, parse_mode="HTML")
        return ConversationHandler.END
    
    session = _batch_sessions[user_id]
    messages = session["messages"]
    
    if not messages:
        await update.message.reply_text(BATCH_EMPTY, parse_mode="HTML")
        clear_session(user_id)
        return ConversationHandler.END
    
    editing = session.get("editing")
    
    if editing:
        # Editing existing batch - append messages
        batch = await get_batch_by_id(editing)
        if not batch:
            await update.message.reply_text(BATCH_NOT_FOUND, parse_mode="HTML")
            clear_session(user_id)
            return ConversationHandler.END
        
        existing_messages = batch.get("messages", [])
        all_messages = existing_messages + messages
        
        await batches_col().update_one(
            {"batch_id": editing},
            {
                "$set": {
                    "messages": all_messages,
                    "updated_at": datetime.utcnow(),
                }
            }
        )
        
        await update.message.reply_text(
            BATCH_UPDATED.format(
                batch_id=editing,
                count=len(all_messages),
                bot_username=BOT_USERNAME,
            ),
            parse_mode="HTML"
        )
        log.info(f"[Batch] Updated batch {editing}: added {len(messages)} messages, total {len(all_messages)}")
    else:
        # Creating new batch
        batch_id = generate_batch_id()
        
        batch_doc = {
            "batch_id": batch_id,
            "owner_id": user_id,
            "messages": messages,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "is_active": True,
        }
        await batches_col().insert_one(batch_doc)
        
        await update.message.reply_text(
            BATCH_CREATED.format(
                batch_id=batch_id,
                count=len(messages),
                bot_username=BOT_USERNAME,
            ),
            parse_mode="HTML"
        )
        log.info(f"[Batch] Created batch {batch_id} with {len(messages)} messages")
    
    clear_session(user_id)
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel batch creation."""
    user_id = update.effective_user.id
    clear_session(user_id)
    await update.message.reply_text(BATCH_CANCELLED, parse_mode="HTML")
    return ConversationHandler.END


@owner_only
async def batches_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all batches."""
    cursor = batches_col().find().sort("created_at", -1)
    batches = await cursor.to_list(length=100)
    
    if not batches:
        await update.message.reply_text(BATCH_LIST_EMPTY, parse_mode="HTML")
        return
    
    text = BATCH_LIST_HEADER.format(count=len(batches))
    
    for i, batch in enumerate(batches, 1):
        source = get_source_summary(batch.get("messages", []))
        text += BATCH_LIST_ITEM.format(
            num=i,
            batch_id=batch["batch_id"],
            source=source,
            count=len(batch.get("messages", [])),
            created=format_datetime(batch.get("created_at")),
            updated=format_datetime(batch.get("updated_at")),
        )
    
    text += "\n<blockquote>Commands</blockquote>\n"
    text += "/editb &lt;batch_id&gt; - Edit batch\n"
    text += "/deleteb &lt;batch_id&gt; - Delete batch"
    
    await update.message.reply_text(text, parse_mode="HTML")


# ─────────────────────────────────────────────────────────────────────────────
# Delete Batch Command
# ─────────────────────────────────────────────────────────────────────────────

@owner_only
async def deleteb_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a batch with confirmation."""
    if not context.args:
        await update.message.reply_text(
            "❌ Usage: /deleteb &lt;batch_id&gt;\nExample: /deleteb 10001",
            parse_mode="HTML"
        )
        return
    
    batch_id = context.args[0]
    batch = await get_batch_by_id(batch_id)
    
    if not batch:
        await update.message.reply_text(BATCH_NOT_FOUND, parse_mode="HTML")
        return
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes, Delete", callback_data=f"batch_del_confirm:{batch_id}"),
            InlineKeyboardButton("❌ No, Cancel", callback_data="batch_del_cancel"),
        ]
    ]
    
    await update.message.reply_text(
        f"⚠️ Delete batch <code>{batch_id}</code>?\n\nThis action cannot be undone.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def callback_batch_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm batch deletion."""
    query = update.callback_query
    await query.answer()
    
    if not is_owner(query.from_user.id):
        return
    
    batch_id = query.data.split(":")[1]
    
    result = await batches_col().delete_one({"batch_id": batch_id})
    
    if result.deleted_count:
        await batch_requests_col().delete_many({"batch_id": batch_id})
        await query.edit_message_text(f"✅ Batch <code>{batch_id}</code> deleted.", parse_mode="HTML")
        log.info(f"[Batch] Deleted batch {batch_id}")
    else:
        await query.edit_message_text(BATCH_NOT_FOUND)


async def callback_batch_delete_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel batch deletion."""
    query = update.callback_query
    await query.answer("Cancelled")
    await query.message.delete()


# ─────────────────────────────────────────────────────────────────────────────
# Deep Link Handler (via /start batch_<batch_id>)
# ─────────────────────────────────────────────────────────────────────────────

async def handle_batch_deeplink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Handle /start batch_<batch_id> deep links.
    Returns True if handled, False otherwise.
    """
    message = update.message
    user = update.effective_user
    
    if not context.args or not context.args[0].startswith("batch_"):
        return False
    
    # Track user for broadcast
    from util.db import track_user
    await track_user(user.id, user.username, user.first_name)
    
    batch_id = context.args[0][6:].upper()  # Remove "batch_" prefix
    
    # Find batch
    batch = await get_batch_by_id(batch_id)
    
    if not batch:
        await message.reply_text(BATCH_NOT_FOUND, parse_mode="HTML")
        return True
    
    if not batch.get("is_active", True):
        await message.reply_text(BATCH_INACTIVE, parse_mode="HTML")
        return True
    
    # Create request
    request_id = f"{user.id}_{batch_id}_{int(datetime.utcnow().timestamp())}"
    
    # Notify user and save message ID for later deletion
    user_msg = await message.reply_text(
        BATCH_REQUEST_SENT.format(batch_id=batch_id),
        parse_mode="HTML"
    )
    
    # Save request with user message ID
    request_doc = {
        "request_id": request_id,
        "batch_id": batch_id,
        "user_id": user.id,
        "status": "pending",
        "requested_at": datetime.utcnow(),
        "handled_by": None,
        "handled_at": None,
        "owner_message_ids": [],
        "user_message_id": user_msg.message_id,  # To delete on action
    }
    await batch_requests_col().insert_one(request_doc)
    log.info(f"[Batch] New request: user {user.id} → batch {batch_id}")
    
    # Build approval keyboard
    keyboard = [
        [
            InlineKeyboardButton("✅𝘍𝘰𝘳𝘸𝘢𝘳𝘥", callback_data=f"batchreq_allow:{request_id}"),
            InlineKeyboardButton("🔒𝘍𝘰𝘳𝘸𝘢𝘳𝘥", callback_data=f"batchreq_restrict:{request_id}"),
        ],
        [
            InlineKeyboardButton("❌𝘙𝘦𝘫𝘦𝘤𝘵 𝘙𝘦𝘲𝘶𝘦𝘴𝘵 ", callback_data=f"batchreq_decline:{request_id}"),
        ]
    ]
    
    # Notify all owners
    user_mention = (
        f'<a href="tg://user?id={user.id}">@{user.username}</a>'
        if user.username
        else f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
    )
    owner_message_ids = []
    
    for owner_id in OWNER_IDS:
        try:
            msg = await context.bot.send_message(
                owner_id,
                BATCH_OWNER_REQUEST.format(
                    batch_id=batch_id,
                    user_mention=user_mention,
                    user_id=user.id,
                    count=len(batch.get("messages", [])),
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            owner_message_ids.append({"owner_id": owner_id, "message_id": msg.message_id})
        except Exception as e:
            log.error(f"[Batch] Failed to notify owner {owner_id}: {e}")
    
    # Save owner message IDs
    await batch_requests_col().update_one(
        {"request_id": request_id},
        {"$set": {"owner_message_ids": owner_message_ids}}
    )
    
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Owner Approval Callbacks
# ─────────────────────────────────────────────────────────────────────────────

async def callback_batch_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle batch access request approval/decline."""
    query = update.callback_query
    
    if not is_owner(query.from_user.id):
        await query.answer("Unauthorized", show_alert=True)
        return
    
    data = query.data
    action = data.split(":")[0]  # batchreq_decline, batchreq_allow, batchreq_restrict
    request_id = data.split(":")[1]
    
    # Find request
    request = await batch_requests_col().find_one({"request_id": request_id})
    
    if not request:
        await query.answer("Request not found", show_alert=True)
        await query.message.delete()
        return
    
    if request.get("status") != "pending":
        # Already handled
        await query.answer("Already handled by another admin", show_alert=True)
        await query.message.delete()
        return
    
    user_id = request["user_id"]
    batch_id = request["batch_id"]
    owner_id = query.from_user.id
    
    # Find batch
    batch = await get_batch_by_id(batch_id)
    if not batch:
        await query.answer("Batch not found", show_alert=True)
        await query.message.delete()
        return
    
    # Handle action
    if action == "batchreq_decline":
        # Decline
        await batch_requests_col().update_one(
            {"request_id": request_id},
            {
                "$set": {
                    "status": "declined",
                    "handled_by": owner_id,
                    "handled_at": datetime.utcnow(),
                }
            }
        )
        
        # Notify user
        try:
            await context.bot.send_message(
                user_id,
                BATCH_ACCESS_DECLINED.format(batch_id=batch_id),
                parse_mode="HTML"
            )
        except Exception as e:
            log.error(f"[Batch] Failed to notify user {user_id}: {e}")
        
        # Delete user's "Access Requested" message
        user_msg_id = request.get("user_message_id")
        if user_msg_id:
            try:
                await context.bot.delete_message(user_id, user_msg_id)
            except Exception:
                pass  # Ignore if already deleted
        
        await query.answer("Declined")
        await query.edit_message_text(
            f"❌ Declined access to batch {batch_id} for user {user_id}.",
            parse_mode="HTML"
        )
        log.info(f"[Batch] Declined: {user_id} → {batch_id}")
        await asyncio.sleep(2)
        try:
            await query.message.delete()
        except Exception:
            pass
        
    elif action in ("batchreq_allow", "batchreq_restrict"):
        # Approve
        is_restricted = action == "batchreq_restrict"
        mode = "Restricted" if is_restricted else "Normal"
        
        # Check if user already has a delivery in progress
        user_has_sending = await has_sending_batch(user_id)
        
        if user_has_sending:
            # Queue this batch - set to approved status (will be processed later)
            status = "approved_restricted" if is_restricted else "approved"
            
            # Edit user's "Access Requested" message to show queued status
            user_msg_id = request.get("user_message_id")
            user_status_msg_id = None
            if user_msg_id:
                try:
                    await context.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=user_msg_id,
                        text=(
                            f"<blockquote><b>Your Request Sucessfully Aprroved By Admin For BatchID:{batch_id} </b></blockquote>\n"
                            f"<b>• Total Content: 🔺 </b>\n"
                            f"<b>• Status : Pending.....</b>\n"
                            f"<b>Content Will Be Sent To Your Inbox Shortly\nThank You For Your Presence 💕</b>"
                        ),
                        parse_mode="HTML"
                    )
                    user_status_msg_id = user_msg_id
                except Exception as e:
                    log.warning(f"[Batch] Failed to edit user message: {e}")
            
            await batch_requests_col().update_one(
                {"request_id": request_id},
                {
                    "$set": {
                        "status": status,
                        "is_restricted": is_restricted,
                        "handled_by": owner_id,
                        "handled_at": datetime.utcnow(),
                        "user_status_message_id": user_status_msg_id,
                        "owner_message_id": query.message.message_id,
                    }
                }
            )
            
            # Update owner message
            messages = batch.get("messages", [])
            user_info = await context.bot.get_chat(user_id)
            user_mention = (
                f'<a href="tg://user?id={user_id}">@{user_info.username}</a>'
                if user_info.username
                else f'<a href="tg://user?id={user_id}">{user_info.full_name}</a>'
            )
            await query.answer("Approved! Content queued.")
            await query.edit_message_text(
                f"<blockquote><b>User Batch Request Approved✅</b></blockquote>\n\n"
                    f"<b>• BatchID≽ {batch_id}</b>\n"
                    f"<b>• UserID≽ {user_mention}</b>\n"
                    f"<b>• Satuts≽  • Waiting....</b>\n"
                    f"<b>• Mode≽ {mode}</b>\n"
                    f"<b>• Totel Item≽ {len(messages)}</b>\n",
                parse_mode="HTML"
            )
            
            log.info(f"[Batch] Approved (Queued - {mode}): {user_id} → {batch_id}")
        else:
            # No active delivery - check if user can receive messages
            user_doc = await users_col().find_one({"user_id": user_id})
            if user_doc and user_doc.get("can_broadcast") is False:
                # User has blocked bot - mark as failed
                await batch_requests_col().update_one(
                    {"request_id": request_id},
                    {
                        "$set": {
                            "status": "failed",
                            "handled_by": owner_id,
                            "handled_at": datetime.utcnow(),
                        }
                    }
                )
                
                user_info = await context.bot.get_chat(user_id)
                user_mention = (
                    f'<a href="tg://user?id={user_id}">@{user_info.username}</a>'
                    if user_info.username
                    else f'<a href="tg://user?id={user_id}">{user_info.full_name}</a>'
                )
                await query.answer("User has blocked the bot")
                await query.edit_message_text(
                    f"<blockquote><b>User Batch Request Approved✅</b></blockquote>\n\n"
                    f"<b>• BatchID≽ {batch_id}</b>\n"
                    f"<b>• UserID≽ {user_mention}</b>\n"
                    f"<b>• Satuts≽  BLOCKED </b>",
                    parse_mode="HTML"
                )
                print(f"Batch Delivery Stopped {user_id} blocked the bot")
                log.warning(f"[Batch] User {user_id} has blocked bot, cannot deliver batch {batch_id}")
            else:
                # Start immediately with "sending" status
                messages = batch.get("messages", [])
                
                # Edit user's "Access Requested" message to show processing status
                user_msg_id = request.get("user_message_id")
                user_status_msg_id = None
                if user_msg_id:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=user_id,
                            message_id=user_msg_id,
                            text=(
                                f"<blockquote><b>Your Request Sucessfully Aprroved By Admin For BatchID:{batch_id} </b></blockquote>\n"
                                f"<b>• Total Content: {len(messages)}</b>\n"
                                f"<b>Sending All Media In Your Inbox\nThank You For Your Presence 💕</b>"
                            ),
                            parse_mode="HTML"
                        )
                        user_status_msg_id = user_msg_id
                    except Exception as e:
                        log.warning(f"[Batch] Failed to edit user message: {e}")
                
                # Get user info
                user_info = await context.bot.get_chat(user_id)
                user_mention = (
                    f'<a href="tg://user?id={user_id}">@{user_info.username}</a>'
                    if user_info.username
                    else f'<a href="tg://user?id={user_id}">{user_info.full_name}</a>'
                )
                 
                # Update owner message
                await query.answer("Approved! Sending content...")
                await query.edit_message_text(
                    f"<blockquote><b>User Batch Request Approved✅</b></blockquote>\n\n"
                    f"<b>• BatchID≽ {batch_id}</b>\n"
                    f"<b>• UserID≽ {user_mention}</b>\n"
                    f"<b>• Satuts≽  • Sending....</b>\n"
                    f"<b>• Mode≽ {mode}</b>\n"
                    f"<b>• Totel Item≽ {len(messages)}</b>\n",
                    parse_mode="HTML"
                )
                owner_message_id = query.message.message_id
                
                # Update DB with message IDs and status
                await batch_requests_col().update_one(
                    {"request_id": request_id},
                    {
                        "$set": {
                            "status": "sending",
                            "is_restricted": is_restricted,
                            "handled_by": owner_id,
                            "handled_at": datetime.utcnow(),
                            "user_status_message_id": user_status_msg_id,
                            "owner_message_id": owner_message_id,
                        }
                    }
                )
                
                log.info(f"[Batch] Approved ({mode}): {user_id} → {batch_id}")

                # Deliver via the unified delivery function as a tracked task
                # (tracked so it is cancelled cleanly on bot shutdown)
                tasks_create_task(
                    deliver_batch_content(
                        bot=context.bot,
                        user_id=user_id,
                        batch=batch,
                        protected=is_restricted,
                        owner_id=owner_id,
                        user_mention=user_mention,
                        request_id=request_id,
                        owner_message_id=owner_message_id,
                        user_status_message_id=user_status_msg_id,
                        mode=mode,
                    ),
                    name=f"batch_delivery_{request_id}",
                )
    
    # Delete messages from other owners
    owner_messages = request.get("owner_message_ids", [])
    for om in owner_messages:
        if om["owner_id"] != owner_id:
            try:
                await context.bot.delete_message(om["owner_id"], om["message_id"])
            except Exception:
                pass



# ─────────────────────────────────────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────────────────────────────────────

def register(app: Application) -> None:
    """Register batch plugin handlers."""
    import warnings
    from telegram.warnings import PTBUserWarning
    
    # Standalone commands
    app.add_handler(CommandHandler("batches", batches_command))
    app.add_handler(CommandHandler("blist", batches_command))
    app.add_handler(CommandHandler("batchlist", batches_command))
    app.add_handler(CommandHandler("deleteb", deleteb_command))
    
    # Batch delete confirmation callbacks
    app.add_handler(CallbackQueryHandler(callback_batch_delete_confirm, pattern=r"^batch_del_confirm:"))
    app.add_handler(CallbackQueryHandler(callback_batch_delete_cancel, pattern=r"^batch_del_cancel$"))
    
    # Batch request callbacks (user access approval)
    app.add_handler(CallbackQueryHandler(callback_batch_request, pattern=r"^batchreq_"))
    
    # Conversation handler for batch creation/editing
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=PTBUserWarning, message=".*per_message.*")
        
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("batch", batch_command),
                CommandHandler("editb", editb_command),
            ],
            states={
                COLLECTING_MESSAGES: [
                    CommandHandler("makeit", makeit_command),
                    CommandHandler("cancel", cancel_command),
                    MessageHandler(
                        filters.ALL & ~filters.COMMAND & filters.User(OWNER_IDS),
                        receive_message
                    ),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", cancel_command),
                CommandHandler("makeit", makeit_command),
            ],
            per_user=True,
            per_chat=True,
            per_message=False,
        )
    app.add_handler(conv_handler)
    
    log.info("[Batch] Plugin registered.")
