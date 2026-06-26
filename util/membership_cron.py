import asyncio
from datetime import datetime
from typing import Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from config import SUPPORT_USERNAME, EXPIRY_NOTIFY_OWNER, OWNER_IDS
from util.logging import log
from util.db import memberships_col, managed_groups_col
from util.cronJob import add_job, every_minutes
from util.responses import MEMBERSHIP_EXPIRED, MEMBERSHIP_EXPIRED_BTN, EXPIRY_SUDO_MSG,SUDO_EXPIRE_BTN


# Lock to prevent duplicate processing
_processing_lock = asyncio.Lock()

# Bot reference (set during init)
_bot: Optional[Bot] = None


def init_membership_cron(bot: Bot) -> None:
    """Initialize membership cron job with bot reference."""
    global _bot
    _bot = bot
    
    # Register the expiry check job - every 10 minutes
    add_job(
        check_expired_memberships,
        every_minutes(10),
        job_id="membership_expiry_check",
    )
    log.info("[Membership Cron] Expiry check job registered (every 10 minutes)")


async def check_expired_memberships() -> None:
    """
    Check and process expired memberships.
    - Kicks user from group
    - Updates membership status
    - Notifies user
    """
    global _bot
    if _bot is None:
        log.warning("[Membership Cron] Bot not initialized, skipping")
        return
    
    # Prevent concurrent runs
    if _processing_lock.locked():
        log.debug("[Membership Cron] Already processing, skipping")
        return
    
    async with _processing_lock:
        try:
            await _process_expired()
        except Exception as e:
            log.error(f"[Membership Cron] Error processing expired: {e}")


async def _process_expired() -> None:
    """Process all expired memberships."""
    now = datetime.utcnow()
    
    # Find expired active memberships
    col = memberships_col()
    expired_cursor = col.find({
        "status": "active",
        "expires_at": {"$lt": now}
    })
    
    expired_list = await expired_cursor.to_list(length=100)
    
    if not expired_list:
        log.debug("[Membership Cron] No expired memberships found")
        return
    
    log.info(f"[Membership Cron] Found {len(expired_list)} expired memberships")
    
    for membership in expired_list:
        user_id = membership["user_id"]
        group_id = membership["group_id"]
        expires_at = membership.get("expires_at")
        
        try:
            await process_single_expiry(user_id, group_id, expires_at)
        except Exception as e:
            log.error(f"[Membership Cron] Error expiring {user_id} from {group_id}: {e}")
        
        # Small delay to avoid rate limiting
        await asyncio.sleep(0.5)


async def process_single_expiry(user_id: int, group_id: int, expires_at: Optional[datetime] = None) -> None:
    """Process a single expired membership."""
    global _bot
    col = memberships_col()
    
    # Get group info
    group = await managed_groups_col().find_one({"group_id": group_id})
    group_name = group["group_name"] if group else "Unknown Group"
    expires_str = expires_at.strftime("%Y-%m-%d %H:%M UTC") if expires_at else "Unknown"
    
    # Try to kick user from group
    try:
        await _bot.ban_chat_member(group_id, user_id)
        # Immediately unban so they can rejoin later via new invite
        await _bot.unban_chat_member(group_id, user_id, only_if_banned=True)
        log.info(f"[Membership Cron] Kicked {user_id} from {group_name}")
    except TelegramError as e:
        if "user is an administrator" in str(e).lower():
            log.warning(f"[Membership Cron] Cannot kick admin {user_id} from {group_name}")
        elif "user not found" in str(e).lower() or "member not found" in str(e).lower():
            log.debug(f"[Membership Cron] User {user_id} already left {group_name}")
        else:
            log.error(f"[Membership Cron] Failed to kick {user_id}: {e}")
    
    # Update membership status
    await col.update_one(
        {"user_id": user_id, "group_id": group_id},
        {"$set": {"status": "expired"}}
    )
    
    # Notify useril
    try:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(MEMBERSHIP_EXPIRED_BTN, url=f"https://t.me/{SUPPORT_USERNAME}")]
        ])
        await _bot.send_message(
            user_id,
            MEMBERSHIP_EXPIRED.format(group_name=group_name),
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except TelegramError as e:
        log.debug(f"[Membership Cron] Cannot notify {user_id}: {e}")
    
    # Notify owners if enabled
    if EXPIRY_NOTIFY_OWNER and OWNER_IDS:
        user_mention = f'<a href="tg://user?id={user_id}">User {user_id}</a>'
        try:
            user_chat = await _bot.get_chat(user_id)
            user_mention = f'<a href="tg://user?id={user_id}">{user_chat.first_name or "User"}</a>'
        except Exception:
            pass
            
        sudo_msg = EXPIRY_SUDO_MSG.format(
            user_mention=user_mention,
            user_id=user_id,
            group_name=group_name,
            group_id=group_id,
            expires=expires_str
        )
        keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(SUDO_EXPIRE_BTN, url=f"tg://user?id={user_id}?text=%2A%2AYour%20Membership%20Has%20Expired.%20Do%20You%20Want%20To%20Renew%3F%2A%2A")]
            ])
            
        for owner_id in OWNER_IDS:
            try:
                await _bot.send_message(
                    owner_id,
                    sudo_msg,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            except TelegramError as e:
                log.debug(f"[Membership Cron] Cannot notify owner {owner_id}: {e}")


async def force_expire_user(user_id: int, group_id: int) -> bool:
    """
    Manually expire a user's membership.
    Called by owner for immediate revocation.
    """
    global _bot
    if _bot is None:
        return False
    
    try:
        await process_single_expiry(user_id, group_id, None)
        return True
    except Exception as e:
        log.error(f"[Membership Cron] Force expire failed: {e}")
        return False
