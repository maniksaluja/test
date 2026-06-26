"""
Broadcast plugin - Send messages to all bot users.
Owner-only feature with progress tracking and rate limiting.
"""
import asyncio
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.error import TelegramError, Forbidden, BadRequest

from config import OWNER_IDS
from util.logging import log
from util.db import users_col, broadcasts_col
from util.owner import owner_only
from util.responses import (
    BROADCAST_NO_MESSAGE,
    BROADCAST_IN_PROGRESS,
    BROADCAST_READY,
    BROADCAST_PROGRESS,
    BROADCAST_COMPLETE,
    BROADCAST_CANCELLED,
    BROADCAST_NO_USERS,
)

# Global broadcast state (only one broadcast at a time)
_broadcast_state = {
    "running": False,
    "cancelled": False,
    "owner_id": None,
    "message_info": None,  # (chat_id, message_id) or text
    "progress_msg_id": None,
}


def _format_eta(seconds: int) -> str:
    """Format seconds into human readable time."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins}m {secs}s"
    else:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}h {mins}m"


def _create_progress_bar(percent: int, length: int = 16) -> str:
    """Create a text progress bar."""
    filled = int(length * percent / 100)
    empty = length - filled
    return "█" * filled + "░" * empty


async def _get_broadcastable_users() -> tuple[int, int, list[int]]:
    """
    Get count of total users, broadcastable users, and list of user IDs.
    Returns: (total_users, broadcastable_users, user_ids)
    """
    total = await users_col().count_documents({})
    # Get users where can_broadcast is not explicitly False
    cursor = users_col().find(
        {"can_broadcast": {"$ne": False}},
        {"user_id": 1}
    )
    user_ids = []
    async for doc in cursor:
        user_ids.append(doc["user_id"])
    return total, len(user_ids), user_ids


@owner_only
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /broadcast command."""
    global _broadcast_state
    
    if _broadcast_state["running"]:
        await update.message.reply_text(BROADCAST_IN_PROGRESS, parse_mode="HTML")
        return
    
    user_id = update.effective_user.id
    message = update.message
    
    # Check for message to broadcast
    broadcast_text = None
    source_message = None
    
    if message.reply_to_message:
        # Broadcast the replied message
        source_message = message.reply_to_message
    elif context.args:
        # Broadcast the text after /broadcast
        broadcast_text = " ".join(context.args)
    else:
        await message.reply_text(BROADCAST_NO_MESSAGE, parse_mode="HTML")
        return
    
    # Get user counts
    total_users, broadcastable, user_ids = await _get_broadcastable_users()
    
    if broadcastable == 0:
        await message.reply_text(BROADCAST_NO_USERS, parse_mode="HTML")
        return
    
    # Calculate ETA (20 messages per second with 1 second sleep = ~20 msg/sec)
    eta_seconds = (broadcastable // 20) + broadcastable  # Rough estimate
    eta = _format_eta(eta_seconds)
    
    # Store broadcast info
    if source_message:
        _broadcast_state["message_info"] = ("forward", source_message.chat_id, source_message.message_id)
    else:
        _broadcast_state["message_info"] = ("text", broadcast_text)
    
    _broadcast_state["owner_id"] = user_id
    _broadcast_state["user_ids"] = user_ids
    
    # Create confirmation buttons
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❌ Cancel", callback_data="broadcast_cancel_confirm"),
            InlineKeyboardButton("✅ Start Broadcast", callback_data="broadcast_start"),
        ]
    ])
    
    await message.reply_text(
        BROADCAST_READY.format(
            total_users=total_users,
            broadcastable_users=broadcastable,
            eta=eta,
        ),
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def callback_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle broadcast callback buttons."""
    global _broadcast_state
    
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in OWNER_IDS:
        await query.answer("🚫 You Are Not Authorized To Use This Command.", show_alert=True)
        return
    
    data = query.data
    
    if data == "broadcast_cancel_confirm":
        # Cancel before starting
        _broadcast_state = {
            "running": False,
            "cancelled": False,
            "owner_id": None,
            "message_info": None,
            "progress_msg_id": None,
        }
        await query.message.edit_text("❌ Broadcast cancelled.", parse_mode="HTML")
        await query.answer("Cancelled")
        return
    
    if data == "broadcast_cancel_running":
        # Cancel running broadcast
        _broadcast_state["cancelled"] = True
        await query.answer("Cancelling...", show_alert=False)
        return
    
    if data == "broadcast_start":
        await query.answer("Starting broadcast...")
        
        if _broadcast_state["running"]:
            await query.message.edit_text(BROADCAST_IN_PROGRESS, parse_mode="HTML")
            return
        
        _broadcast_state["running"] = True
        _broadcast_state["cancelled"] = False
        
        # Start broadcast in background
        asyncio.create_task(_run_broadcast(query.message, context.bot))


async def _run_broadcast(status_message, bot) -> None:
    """Run the broadcast process."""
    global _broadcast_state
    
    user_ids = _broadcast_state.get("user_ids", [])
    message_info = _broadcast_state.get("message_info")
    
    if not user_ids or not message_info:
        _broadcast_state["running"] = False
        await status_message.edit_text("❌ Broadcast data not found.", parse_mode="HTML")
        return
    
    total = len(user_ids)
    sent = 0
    failed = 0
    blocked = 0
    start_time = datetime.now(timezone.utc)
    last_update = start_time
    
    # Create broadcast record
    broadcast_doc = {
        "owner_id": _broadcast_state["owner_id"],
        "message_info": str(message_info),
        "total_users": total,
        "sent_count": 0,
        "failed_count": 0,
        "blocked_count": 0,
        "status": "running",
        "created_at": start_time,
        "completed_at": None,
    }
    result = await broadcasts_col().insert_one(broadcast_doc)
    broadcast_id = result.inserted_id
    
    # Cancel button
    cancel_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel Broadcast", callback_data="broadcast_cancel_running")]
    ])
    
    try:
        batch_count = 0
        for i, target_user_id in enumerate(user_ids):
            if _broadcast_state["cancelled"]:
                break
            
            try:
                if message_info[0] == "forward":
                    # Forward the message
                    await bot.forward_message(
                        chat_id=target_user_id,
                        from_chat_id=message_info[1],
                        message_id=message_info[2],
                    )
                else:
                    # Send text message
                    await bot.send_message(
                        chat_id=target_user_id,
                        text=message_info[1],
                    )
                sent += 1
                
            except Forbidden:
                # User blocked bot
                failed += 1
                blocked += 1
                # Mark user as can_broadcast = False
                await users_col().update_one(
                    {"user_id": target_user_id},
                    {"$set": {"can_broadcast": False}}
                )
                
            except BadRequest as e:
                # Invalid user (deleted account, etc.)
                failed += 1
                log.warning(f"Broadcast failed for user {target_user_id}: {e}")
                
            except TelegramError as e:
                if "flood" in str(e).lower():
                    # FloodWait - sleep and retry
                    log.warning(f"FloodWait during broadcast, sleeping 5s")
                    await asyncio.sleep(5)
                    # Retry this user
                    try:
                        if message_info[0] == "forward":
                            await bot.forward_message(
                                chat_id=target_user_id,
                                from_chat_id=message_info[1],
                                message_id=message_info[2],
                            )
                        else:
                            await bot.send_message(
                                chat_id=target_user_id,
                                text=message_info[1],
                            )
                        sent += 1
                    except Exception:
                        failed += 1
                else:
                    failed += 1
                    log.warning(f"Broadcast error for user {target_user_id}: {e}")
                    
            except Exception as e:
                failed += 1
                log.error(f"Unexpected broadcast error for user {target_user_id}: {e}")
            
            batch_count += 1
            
            # Rate limiting: 20 messages per batch, then sleep 1 second
            if batch_count >= 20:
                batch_count = 0
                await asyncio.sleep(1)
            
            # Update progress every 2 seconds
            now = datetime.now(timezone.utc)
            if (now - last_update).total_seconds() >= 2:
                last_update = now
                
                # Calculate ETA
                elapsed = (now - start_time).total_seconds()
                if sent + failed > 0:
                    rate = (sent + failed) / elapsed
                    remaining = total - (sent + failed)
                    eta_seconds = int(remaining / rate) if rate > 0 else 0
                else:
                    eta_seconds = 0
                
                percent = int(((sent + failed) / total) * 100)
                bar = _create_progress_bar(percent)
                
                try:
                    await status_message.edit_text(
                        BROADCAST_PROGRESS.format(
                            total=total,
                            sent=sent,
                            failed=failed,
                            eta=_format_eta(eta_seconds),
                            bar=bar,
                            percent=percent,
                        ),
                        parse_mode="HTML",
                        reply_markup=cancel_keyboard,
                    )
                except TelegramError:
                    pass  # Ignore edit errors
        
        # Broadcast finished
        end_time = datetime.now(timezone.utc)
        elapsed = (end_time - start_time).total_seconds()
        
        # Update broadcast record
        await broadcasts_col().update_one(
            {"_id": broadcast_id},
            {
                "$set": {
                    "sent_count": sent,
                    "failed_count": failed,
                    "blocked_count": blocked,
                    "status": "cancelled" if _broadcast_state["cancelled"] else "completed",
                    "completed_at": end_time,
                }
            }
        )
        
        if _broadcast_state["cancelled"]:
            remaining = total - sent - failed
            await status_message.edit_text(
                BROADCAST_CANCELLED.format(sent=sent, remaining=remaining),
                parse_mode="HTML",
            )
        else:
            await status_message.edit_text(
                BROADCAST_COMPLETE.format(
                    sent=sent,
                    failed=failed,
                    time=_format_eta(int(elapsed)),
                    blocked=blocked,
                ),
                parse_mode="HTML",
            )
        
    except Exception as e:
        log.error(f"Broadcast failed: {e}")
        await status_message.edit_text(
            f"❌ <b>Broadcast Failed</b>\n\nError: {e}\n\nSent: {sent}, Failed: {failed}",
            parse_mode="HTML",
        )
        
        # Update broadcast record
        await broadcasts_col().update_one(
            {"_id": broadcast_id},
            {
                "$set": {
                    "sent_count": sent,
                    "failed_count": failed,
                    "blocked_count": blocked,
                    "status": "failed",
                    "completed_at": datetime.now(timezone.utc),
                }
            }
        )
    
    finally:
        # Reset state
        _broadcast_state["running"] = False
        _broadcast_state["cancelled"] = False
        _broadcast_state["owner_id"] = None
        _broadcast_state["message_info"] = None
        _broadcast_state["user_ids"] = []
        _broadcast_state["progress_msg_id"] = None


def register(app: Application) -> None:
    """Register broadcast handlers."""
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("bcast", broadcast_command))
    app.add_handler(CallbackQueryHandler(callback_broadcast, pattern=r"^broadcast_"))