"""
Batch Queue Cron - Process queued batch deliveries.
Handles delivery queue when multiple batches are approved for same user.
"""
import asyncio
from datetime import datetime
from typing import Optional

from telegram import Bot
from telegram.error import TelegramError, RetryAfter

from util.logging import log
from util.db import batches_col, batch_requests_col, users_col
from util.cronJob import add_job, every_seconds
from util.responses import SEND_BATCH_START_MSG, BATCH_START_MSG, BATCH_END_MSG
from util.tasks import create_task

# Bot reference (set during init)
_bot: Optional[Bot] = None

# Lock to prevent concurrent processing
_processing_lock = asyncio.Lock()


def init_batch_cron(bot: Bot) -> None:
    """Initialize batch cron job with bot reference."""
    global _bot
    _bot = bot
    
    # Cleanup on startup - run synchronously via asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_cleanup_on_startup())
        else:
            loop.run_until_complete(_cleanup_on_startup())
    except Exception as e:
        log.error(f"[Batch Cron] Startup cleanup failed: {e}")
    
    # Run every 10 seconds to check for queued batches
    add_job(
        process_batch_queue,
        every_seconds(10),
        job_id="batch_queue_processor",
        replace_existing=True
    )
    log.info("[Batch Cron] Initialized batch queue processor (every 10s)")


async def _cleanup_on_startup() -> None:
    """Cleanup stale batch requests from previous bot run."""
    # Delete completed records (no longer needed)
    completed_result = await batch_requests_col().delete_many({"status": "completed"})
    if completed_result.deleted_count:
        log.info(f"[Batch Cron] Startup cleanup: Deleted {completed_result.deleted_count} completed batch requests")
    
    # Reset interrupted deliveries to approved so they are retried (never delete approved work)
    sending_result = await batch_requests_col().update_many(
        {"status": "sending"},
        {"$set": {"status": "approved", "sending_started_at": None}}
    )
    if sending_result.modified_count:
        log.info(f"[Batch Cron] Startup cleanup: Reset {sending_result.modified_count} interrupted deliveries back to approved for retry")
    
    # Count remaining approved batches
    approved_count = await batch_requests_col().count_documents({"status": {"$in": ["approved", "approved_restricted"]}})
    if approved_count:
        log.info(f"[Batch Cron] {approved_count} approved batch requests pending delivery")


async def has_sending_batch(user_id: int) -> bool:
    """Check if user has a batch currently being sent."""
    count = await batch_requests_col().count_documents({
        "user_id": user_id,
        "status": "sending"
    })
    return count > 0


async def get_next_queued_batch(user_id: int) -> Optional[dict]:
    """Get the next approved batch waiting for delivery for a user."""
    return await batch_requests_col().find_one(
        {
            "user_id": user_id,
            "status": {"$in": ["approved", "approved_restricted"]}
        },
        sort=[("handled_at", 1)]  # Oldest approval first (FIFO)
    )


async def process_next_batch_for_user(bot: Bot, user_id: int) -> None:
    """Check and process next queued batch for a user after a delivery completes."""
    next_request = await get_next_queued_batch(user_id)
    if next_request:
        log.info(f"[Batch Cron] Processing next queued batch for user {user_id}")
        await start_batch_delivery(bot, next_request)


async def process_batch_queue() -> None:
    """
    Process the batch delivery queue.
    Finds users with approved batches and no active sending, then delivers.
    The lock only guards the scheduling decision — delivery runs outside it
    so future cron cycles are never blocked by a long-running send.
    """
    global _bot

    if _bot is None:
        return

    if _processing_lock.locked():
        return  # Already scheduling

    requests_to_deliver = []

    async with _processing_lock:
        try:
            # Sort before grouping so $first reliably picks the oldest approval
            pipeline = [
                {
                    "$match": {
                        "status": {"$in": ["approved", "approved_restricted"]}
                    }
                },
                {"$sort": {"handled_at": 1}},  # Oldest approval first (FIFO)
                {
                    "$group": {
                        "_id": "$user_id",
                        "oldest_request": {"$first": "$$ROOT"}
                    }
                },
                {"$limit": 10}  # Up to 10 users per cycle
            ]

            cursor = batch_requests_col().aggregate(pipeline)
            users_to_process = await cursor.to_list(length=10)

            for user_doc in users_to_process:
                user_id = user_doc["_id"]

                if await has_sending_batch(user_id):
                    continue  # Already delivering for this user

                request = await get_next_queued_batch(user_id)
                if not request:
                    continue

                # Pre-mark as sending INSIDE the lock so the next cron cycle
                # sees has_sending_batch=True and skips, preventing double-start
                await batch_requests_col().update_one(
                    {"request_id": request["request_id"]},
                    {"$set": {"status": "sending", "sending_started_at": datetime.utcnow()}}
                )
                requests_to_deliver.append(request)

        except Exception as e:
            log.error(f"[Batch Cron] Error processing queue: {e}")

    # Start deliveries OUTSIDE the lock — each runs as an independent tracked
    # task so the lock is free for the next cron cycle immediately
    for request in requests_to_deliver:
        create_task(
            start_batch_delivery(_bot, request),
            name=f"batch_delivery_{request['request_id']}"
        )


async def start_batch_delivery(bot: Bot, request: dict) -> None:
    """Start delivering a batch from the queue."""
    request_id = request["request_id"]
    user_id = request["user_id"]
    batch_id = request["batch_id"]
    is_restricted = request.get("is_restricted", request["status"] == "approved_restricted")
    owner_id = request.get("handled_by")
    
    # Check if user can receive messages (not blocked)
    user_doc = await users_col().find_one({"user_id": user_id})
    if user_doc and user_doc.get("can_broadcast") is False:
        log.warning(f"[Batch Cron] User {user_id} has blocked bot, skipping delivery")
        print(f"Batch Delivery Stopped {user_id} blocked the bot")
        await batch_requests_col().update_one(
            {"request_id": request_id},
            {"$set": {"status": "failed", "completed_at": datetime.utcnow()}}
        )
        # Process next batch for this user if any
        next_request = await get_next_queued_batch(user_id)
        if next_request:
            await start_batch_delivery(bot, next_request)
        return
    
    # Get batch
    batch = await batches_col().find_one({"batch_id": batch_id})
    if not batch:
        log.warning(f"[Batch Cron] Batch {batch_id} not found, marking request as failed")
        await batch_requests_col().update_one(
            {"request_id": request_id},
            {"$set": {"status": "failed"}}
        )
        return
    
    # Mark as sending
    await batch_requests_col().update_one(
        {"request_id": request_id},
        {"$set": {"status": "sending", "sending_started_at": datetime.utcnow()}}
    )
    
    # Get user mention for progress updates
    user_mention = f'<a href="tg://user?id={user_id}">{user_id}</a>'
    try:
        user_info = await bot.get_chat(user_id)
        display = f"@{user_info.username}" if user_info.username else (user_info.first_name or str(user_id))
        user_mention = f'<a href="tg://user?id={user_id}">{display}</a>'
    except:
        pass
    
    # Get stored message IDs from approval
    user_status_message_id = request.get("user_status_message_id")
    owner_message_id = request.get("owner_message_id")
    
    # Get mode for display
    mode = "Restricted" if is_restricted else "Normal"
    
    # Update user's status message to show processing
    messages = batch.get("messages", [])
    if user_status_message_id:
        try:
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=user_status_message_id,
                text=(
                    f"<blockquote>✅ Batch Approved (Processing)</blockquote>\n\n"
                    f"📦 <b>Batch:</b> <code>{batch_id}</code>\n"
                    f"📊 <b>Files:</b> {len(messages)}\n\n"
                    f"<i>Sending your content...</i>"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            log.warning(f"[Batch Cron] Failed to update user status message: {e}")
    
    # Update owner's message to show processing
    if owner_id and owner_message_id:
        try:
            await bot.edit_message_text(
                chat_id=owner_id,
                message_id=owner_message_id,
                text=(
                    f"<blockquote><b>User Batch Request Approved✅</b></blockquote>\n\n"
                        f"<b>• BatchID≽ {batch_id}</b>\n"
                        f"<b>• UserID≽ {user_mention}</b>\n"
                        f"<b>• Satuts≽  •Sending...</b>\n"
                        f"<b>• Mode≽ {mode}</b>\n"
                        f"<b>• Totel Item≽ {len(messages)} Sent {sent} </b>"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            log.warning(f"[Batch Cron] Failed to update owner message: {e}")
    
    # Deliver the batch
    await deliver_batch_content(
        bot=bot,
        user_id=user_id,
        batch=batch,
        protected=is_restricted,
        owner_id=owner_id,
        user_mention=user_mention,
        request_id=request_id,
        owner_message_id=owner_message_id,
        user_status_message_id=user_status_message_id,
        mode=mode,
    )


async def deliver_batch_content(
    bot: Bot,
    user_id: int,
    batch: dict,
    protected: bool,
    owner_id: Optional[int],
    user_mention: str,
    request_id: str,
    owner_message_id: Optional[int] = None,
    user_status_message_id: Optional[int] = None,
    mode: str = "Normal",
) -> None:
    """Deliver batch content to user with progress updates to owner."""
    messages = batch.get("messages", [])
    batch_id = batch.get("batch_id", "Unknown")
    total = len(messages)
    sent = 0
    failed_delivery = False
    start_time = datetime.utcnow()
    
    last_update_time = datetime.utcnow()
    
    # Send batch start message to user (if enabled)
    if SEND_BATCH_START_MSG:
        try:
            await bot.send_message(
                user_id,
                BATCH_START_MSG.format(batch_id=batch_id, mode=mode),
                parse_mode="HTML"
            )
        except Exception:
            pass
    
    for msg in messages:
        chat_id = msg.get("chat_id")
        message_id = msg.get("message_id")

        if not chat_id or not message_id:
            continue

        # Retry loop: up to 3 attempts per message to handle transient errors
        for attempt in range(3):
            try:
                try:
                    await bot.copy_message(
                        chat_id=user_id,
                        from_chat_id=chat_id,
                        message_id=message_id,
                        protect_content=protected,
                        disable_notification=True,
                    )
                except Exception as inner_e:
                    inner_err_str = str(inner_e).lower()
                    if "media_file_invalid" in inner_err_str or "media_empty" in inner_err_str:
                        log.info(f"[Batch Cron] copy_message failed with invalid media, falling back to forward_message for msg {message_id}")
                        await bot.forward_message(
                            chat_id=user_id,
                            from_chat_id=chat_id,
                            message_id=message_id,
                            protect_content=protected,
                            disable_notification=True,
                        )
                    else:
                        raise inner_e

                sent += 1

                # Update progress every 5 seconds on owner's message
                now = datetime.utcnow()
                if owner_id and owner_message_id and (now - last_update_time).total_seconds() >= 5:
                    try:
                        await bot.edit_message_text(
                            chat_id=owner_id,
                            message_id=owner_message_id,
                            text=(
                                f"<blockquote><b>User Batch Request Approved✅</b></blockquote>\n\n"
                                f"<b>• BatchID≽ {batch_id}</b>\n"
                                f"<b>• UserID≽ {user_mention}</b>\n"
                                f"<b>• Satuts≽  •Sending.....</b>\n"
                                f"<b>• Mode≽ {mode}</b>\n"
                                f"<b>• Totel Item≽ {len(messages)} Sent {sent} </b>"
                            ),
                            parse_mode="HTML"
                        )
                        last_update_time = now
                    except Exception:
                        pass

                await asyncio.sleep(1.0)  # ~40 msg/min — stays under per-chat flood limit
                break  # Success — exit retry loop for this message

            except RetryAfter as e:
                # Telegram told us to back off; sleep the required duration then retry
                wait_secs = float(e.retry_after) + 1.0
                log.warning(
                    f"[Batch Cron] FloodWait {wait_secs:.0f}s on msg {message_id} "
                    f"for user {user_id} (attempt {attempt + 1}/3)"
                )
                await asyncio.sleep(wait_secs)
                # Loop continues — will retry the same message

            except Exception as e:
                error_str = str(e).lower()
                if "blocked" in error_str or "forbidden" in error_str or "chat not found" in error_str:
                    print(f"Batch Delivery Stopped {user_id} blocked the bot")
                    log.warning(f"[Batch Cron] Batch Delivery Stopped {user_id} blocked the bot")
                    failed_delivery = True
                    await users_col().update_one(
                        {"user_id": user_id},
                        {"$set": {"can_broadcast": False}}
                    )
                else:
                    log.warning(f"[Batch Cron] Failed to copy msg {message_id} (attempt {attempt + 1}/3): {e}")
                break  # Exit retry loop for this message (don't retry unknown errors)

        if failed_delivery:
            break  # Stop the entire batch delivery
    
    # Calculate time taken
    elapsed = datetime.utcnow() - start_time
    elapsed_str = str(elapsed).split('.')[0]  # Remove microseconds
    
    if failed_delivery:
        # Keep failed records for debugging
        await batch_requests_col().update_one(
            {"request_id": request_id},
            {
                "$set": {
                    "status": "failed",
                    "completed_at": datetime.utcnow(),
                    "sent_count": sent,
                    "total_count": total,
                }
            }
        )
        
        # Update owner's message to show failure
        if owner_id and owner_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=owner_id,
                    message_id=owner_message_id,
                    text=(
                        f"<blockquote><b>User Batch Request Approved✅</b></blockquote>\n\n"
                        f"<b>• BatchID≽ {batch_id}</b>\n"
                        f"<b>• UserID≽ {user_mention}</b>\n"
                        f"<b>• Satuts≽  •BLOCKED❌</b>\n"
                        f"<b>• Mode≽ {mode}</b>\n"
                       f"<b>• ETA≽ {elapsed_str} </b>\n"
                        f"<b>• Totel Item≽ {len(messages)} Sent {sent} </b>"
                    ),
                    parse_mode="HTML"
                )
            except Exception:
                pass
        
        # Update user's message if possible
        if user_status_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=user_id,
                    message_id=user_status_message_id,
                    text=(
                        f" <blockquote>❌ Batch Delivery Failed</blockquote>\n\n"
                        f"📦 <b>Batch:</b> <code>{batch_id}</code>\n\n"
                        f"<b>Sent:</b> <code>{sent}</code> / <code>{total}</code>"
                    ),
                    parse_mode="HTML"
                )
            except Exception:
                pass
    else:
        # Delete successful delivery record to save space
        await batch_requests_col().delete_one({"request_id": request_id})
        
        # Final update to owner's message
        if owner_id and owner_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=owner_id,
                    message_id=owner_message_id,
                    text=(
                        f"<blockquote><b>User Batch Request Approved✅</b></blockquote>\n\n"
                        f"<b>• BatchID≽ {batch_id}</b>\n"
                        f"<b>• UserID≽ {user_mention}</b>\n"
                        f"<b>• Satuts≽  •DONE✅</b>\n"
                        f"<b>• Mode≽ {mode}</b>\n"
                        f"<b>• ETA≽ {elapsed_str} </b>\n"
                        f"<b>• Totel Item≽ {len(messages)} Sent {sent} </b>"
                    ),
                    parse_mode="HTML"
                )
            except Exception:
                pass
        
        # Update user's status message with completion
        if user_status_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=user_id,
                    message_id=user_status_message_id,
                    text=(
                        f"<blockquote><b>Your Batch Link Request Successfully Delivered To Your Inbox</b></blockquote>\n"
                        f"<b>Total Sent:{sent}/{total} </b>"
                    ),
                    parse_mode="HTML"
                )
            except Exception:
                pass
        
        # Send batch end message to user
        try:
            await bot.send_message(
                user_id,
                BATCH_END_MSG.format(batch_id=batch_id, mode=mode),
                parse_mode="HTML"
            )
        except Exception:
            pass
    
    log.info(f"[Batch Cron] Delivery {'failed' if failed_delivery else 'completed'}: {user_id} → {batch_id} ({sent}/{total})")
    
    # Check for next queued batch for this user
    next_request = await get_next_queued_batch(user_id)
    if next_request:
        log.info(f"[Batch Cron] Processing next queued batch for user {user_id}")
        await start_batch_delivery(bot, next_request)
