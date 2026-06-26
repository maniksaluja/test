"""
Membership Plugin - Manage group access via deep links.
Handles: group discovery, user requests, owner approval, expiry management.
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
)
from telegram.constants import ChatMemberStatus, ChatType

from config import BOT_USERNAME, OWNER_IDS, MEMBERSHIP_DAYS, SUPPORT_USERNAME
from util.logging import log
from util.owner import owner_only
from util.db import managed_groups_col, membership_requests_col, memberships_col
from util.responses import (
    MEMBERSHIP_GROUPS_HEADER,
    MEMBERSHIP_GROUPS_EMPTY,
    MEMBERSHIP_GROUP_ITEM,
    MEMBERSHIP_ALREADY_REQUESTED,
    MEMBERSHIP_ALREADY_MEMBER,
    MEMBERSHIP_REQUEST_SENT,
    MEMBERSHIP_GROUP_NOT_FOUND,
    MEMBERSHIP_GROUP_INACTIVE,
    MEMBERSHIP_OWNER_REQUEST,
    MEMBERSHIP_DECLINED,
    MEMBERSHIP_CONTACT_SUPPORT,
    MEMBERSHIP_APPROVED,
    MEMBERSHIP_JOIN_BTN,
    MEMBERSHIP_OWNER_APPROVED,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def generate_access_code() -> str:
    """Generate a short random access code for group deep links."""
    return secrets.token_urlsafe(8)[:10]


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



def format_expiry(dt: datetime) -> str:
    """Format datetime for display."""
    return dt.strftime("%d %b %Y, %H:%M UTC")


async def get_group_by_code(access_code: str) -> Optional[dict]:
    """Find group by access code."""
    return await managed_groups_col().find_one({"access_code": access_code})


async def get_group_by_id(group_id: int) -> Optional[dict]:
    """Find group by group ID."""
    return await managed_groups_col().find_one({"group_id": group_id})


async def sync_group(bot, group_id: int, group_name: str) -> dict:
    """
    Sync a group to the database.
    Creates if not exists, updates name if exists.
    """
    col = managed_groups_col()
    existing = await col.find_one({"group_id": group_id})
    
    if existing:
        # Update group name if changed
        if existing.get("group_name") != group_name:
            await col.update_one(
                {"group_id": group_id},
                {"$set": {"group_name": group_name}}
            )
            existing["group_name"] = group_name
        return existing
    
    # Create new group entry
    access_code = generate_access_code()
    group_doc = {
        "group_id": group_id,
        "group_name": group_name,
        "is_active": True,  # Active by default
        "access_code": access_code,
        "added_at": datetime.utcnow(),
    }
    await col.insert_one(group_doc)
    log.info(f"[Membership] New group synced: {group_name} ({group_id})")
    return group_doc


async def get_pending_request(user_id: int, group_id: int) -> Optional[dict]:
    """Get pending request for user-group pair."""
    return await membership_requests_col().find_one({
        "user_id": user_id,
        "group_id": group_id,
        "status": "pending"
    })


async def get_active_membership(user_id: int, group_id: int) -> Optional[dict]:
    """Get active membership for user-group pair."""
    return await memberships_col().find_one({
        "user_id": user_id,
        "group_id": group_id,
        "status": "active",
        "expires_at": {"$gt": datetime.utcnow()}
    })


def build_duration_keyboard(request_id: str) -> InlineKeyboardMarkup:
    """Build approval keyboard with duration buttons."""
    buttons = []
    row = []
    for days in MEMBERSHIP_DAYS:
        row.append(InlineKeyboardButton(
            f"{days}d",
            callback_data=f"mem_approve:{request_id}:{days}"
        ))
        if len(row) == 4:  # 4 buttons per row
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    # Add decline button
    buttons.append([
        InlineKeyboardButton("❌ Decline", callback_data=f"mem_decline:{request_id}")
    ])
    
    return InlineKeyboardMarkup(buttons)


# ─────────────────────────────────────────────────────────────────────────────
# Owner: /addgroup command (manual group registration)
# ─────────────────────────────────────────────────────────────────────────────

@owner_only
async def addgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Manually add a group by ID.
    Usage: /addgroup <group_id>
    Can also be used inside a group without arguments.
    """
    message = update.message
    bot = context.bot
    
    # Get group_id from args or from current chat
    if context.args:
        try:
            group_id = int(context.args[0])
            # Normalize: add -100 prefix if not present
            group_id = normalize_chat_id(group_id)
        except ValueError:
            await message.reply_text("❌ Invalid group ID. Usage: <code>/addgroup &lt;group_id&gt;</code>", parse_mode="HTML")
            return
    elif message.chat.type in ["group", "supergroup"]:
        group_id = message.chat.id
    else:
        await message.reply_text(
            "<blockquote><b>0 CHANNEL/GROUP IN DATABASE</b></blockquote>\n"
            "<b>• Use /add {ChannelID} Cmand to Add New channel In Database</b>",
            parse_mode="HTML"
        )
        return
    
    # Check if bot is admin in the group
    try:
        chat = await bot.get_chat(group_id)
        member = await bot.get_chat_member(group_id, bot.id)
        
        if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            await message.reply_text(
                f"❌ Bot is not an admin in <b>{chat.title}</b>.\n"
                "Please make the bot admin first.",
                parse_mode="HTML"
            )
            return
        
        # Sync the group
        group_doc = await sync_group(bot, group_id, chat.title)
        
        await message.reply_text(
            f"✅ <b>Group Registered!</b>\n\n"
            f"<b>Name:</b> {chat.title}\n"
            f"<b>ID:</b> <code>{group_id}</code>\n"
            f"<b>Access Code:</b> <code>{group_doc['access_code']}</code>\n\n"
            f"🔗 <b>Deep Link:</b>\n"
            f"<code>t.me/{BOT_USERNAME}?start=join_{group_doc['access_code']}</code>",
            parse_mode="HTML"
        )
        
    except Exception as e:
        log.error(f"[Membership] Error adding group {group_id}: {e}")
        await message.reply_text(f"❌ Cannot access group <code>{group_id}</code>.\n\nError: {e}", parse_mode="HTML")


# ─────────────────────────────────────────────────────────────────────────────
# Owner: /groups command
# ─────────────────────────────────────────────────────────────────────────────

async def build_groups_message(bot) -> tuple[str, InlineKeyboardMarkup | None]:
    """Build the groups list message and keyboard. Returns (text, keyboard)."""
    col = managed_groups_col()
    groups = await col.find({}).to_list(length=100)
    
    valid_groups = []
    for group in groups:
        group_id = group["group_id"]
        try:
            chat = await bot.get_chat(group_id)
            member = await bot.get_chat_member(group_id, bot.id)
            
            if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                await sync_group(bot, group_id, chat.title)
                group["group_name"] = chat.title
                valid_groups.append(group)
        except Exception:
            pass
    
    if not valid_groups:
        return MEMBERSHIP_GROUPS_EMPTY, None
    
    lines = [MEMBERSHIP_GROUPS_HEADER]
    buttons = []
    
    for i, group in enumerate(valid_groups, 1):
        # Refresh is_active from DB since it may have changed
        refreshed = await get_group_by_id(group["group_id"])
        is_active = refreshed.get("is_active", True) if refreshed else True
        
        status = "✅ Active" if is_active else "❌ Inactive"
        lines.append(MEMBERSHIP_GROUP_ITEM.format(
            num=i,
            group_name=group["group_name"],
            group_id=group["group_id"],
            status=status,
            bot_username=BOT_USERNAME,
            access_code=group["access_code"],
        ))
        
        emoji = "🔴" if is_active else "🟢"
        buttons.append([InlineKeyboardButton(
            f"{emoji} Toggle: {group['group_name'][:20]}",
            callback_data=f"mem_toggle:{group['group_id']}"
        )])
    
    keyboard = InlineKeyboardMarkup(buttons) if buttons else None
    return "\n".join(lines), keyboard


@owner_only
async def groups_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all groups where bot is admin."""
    message = update.message
    bot = context.bot
    
    status_msg = await message.reply_text("🔍 Checking registered groups...")
    
    # Use shared builder
    text, keyboard = await build_groups_message(bot)
    
    # Delete the "checking" message
    try:
        await status_msg.delete()
    except Exception:
        pass
    
    # Send final message (same parse_mode for both cases)
    if keyboard is None:
        await message.reply_text(text, parse_mode="HTML")
    else:
        await message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


# ─────────────────────────────────────────────────────────────────────────────
# Deep Link Handler (via /start)
# ─────────────────────────────────────────────────────────────────────────────

async def handle_join_deeplink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Handle /start join_<access_code> deep links.
    Automatically submits request if user is new.
    Returns True if handled, False otherwise.
    """
    message = update.message
    user = update.effective_user
    
    if not context.args or not context.args[0].startswith("join_"):
        return False
    
    # Track user for broadcast
    from util.db import track_user
    await track_user(user.id, user.username, user.first_name)
    
    access_code = context.args[0][5:]  # Remove "join_" prefix
    
    # Find group by access code
    group = await get_group_by_code(access_code)
    
    if not group:
        await message.reply_text(MEMBERSHIP_GROUP_NOT_FOUND)
        return True
    
    if not group.get("is_active", True):
        await message.reply_text(MEMBERSHIP_GROUP_INACTIVE)
        return True
    
    group_id = group["group_id"]
    group_name = group["group_name"]
    
    # Check if user already has active membership
    membership = await get_active_membership(user.id, group_id)
    if membership:
        expires = format_expiry(membership["expires_at"])
        await message.reply_text(
            MEMBERSHIP_ALREADY_MEMBER.format(group_name=group_name, expires=expires),
            parse_mode="HTML"
        )
        return True
    
    # Check if user already has pending request
    pending = await get_pending_request(user.id, group_id)
    if pending:
        await message.reply_text(
            MEMBERSHIP_ALREADY_REQUESTED.format(group_name=group_name),
            parse_mode="HTML"
        )
        return True
    
    # AUTO-SUBMIT REQUEST (no button needed)
    # Create request
    request_id = f"{user.id}_{group_id}_{int(datetime.utcnow().timestamp())}"
    
    # Send confirmation to user first to get message ID
    user_msg = await message.reply_text(
        MEMBERSHIP_REQUEST_SENT.format(group_name=group_name),
        parse_mode="HTML"
    )
    
    request_doc = {
        "request_id": request_id,
        "user_id": user.id,
        "group_id": group_id,
        "requested_at": datetime.utcnow(),
        "status": "pending",
        "handled_by": None,
        "owner_message_ids": [],  # Track messages sent to owners
        "user_message_id": user_msg.message_id,  # Track user's confirmation message
    }
    await membership_requests_col().insert_one(request_doc)
    log.info(f"[Membership] New request (auto): {user.id} → {group_name}")
    
    # Notify all owners
    user_mention = (
        f'<a href="tg://user?id={user.id}">@{user.username}</a>'
        if user.username
        else f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
    )
    owner_message_ids = []

    for owner_id in OWNER_IDS:
        try:
            keyboard = build_duration_keyboard(request_id)
            msg = await context.bot.send_message(
                owner_id,
                MEMBERSHIP_OWNER_REQUEST.format(
                    group_name=group_name,
                    user_mention=user_mention,
                    user_id=user.id,
                ),
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            owner_message_ids.append({"owner_id": owner_id, "message_id": msg.message_id})
        except Exception as e:
            log.error(f"[Membership] Failed to notify owner {owner_id}: {e}")

    # Save message IDs for later cleanup
    await membership_requests_col().update_one(
        {"request_id": request_id},
        {"$set": {"owner_message_ids": owner_message_ids}}
    )

    return True


# ─────────────────────────────────────────────────────────────────────────────
# User: Request Access Callback (kept for backward compatibility)
# ─────────────────────────────────────────────────────────────────────────────

async def request_access_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle user clicking 'Request Access' button."""
    query = update.callback_query
    user = update.effective_user
    await query.answer()
    
    # Parse group_id from callback data
    data = query.data.split(":")
    if len(data) < 2:
        return
    
    group_id = int(data[1])
    
    # Get group info
    group = await get_group_by_id(group_id)
    if not group or not group.get("is_active", True):
        await query.edit_message_text(MEMBERSHIP_GROUP_NOT_FOUND)
        return
    
    group_name = group["group_name"]
    
    # Double-check membership and pending request
    membership = await get_active_membership(user.id, group_id)
    if membership:
        expires = format_expiry(membership["expires_at"])
        await query.edit_message_text(
            MEMBERSHIP_ALREADY_MEMBER.format(group_name=group_name, expires=expires),
            parse_mode="HTML"
        )
        return
    
    pending = await get_pending_request(user.id, group_id)
    if pending:
        await query.edit_message_text(
            MEMBERSHIP_ALREADY_REQUESTED.format(group_name=group_name),
            parse_mode="HTML"
        )
        return
    
    # Create request
    request_id = f"{user.id}_{group_id}_{int(datetime.utcnow().timestamp())}"
    request_doc = {
        "request_id": request_id,
        "user_id": user.id,
        "group_id": group_id,
        "requested_at": datetime.utcnow(),
        "status": "pending",
        "handled_by": None,
        "owner_message_ids": [],  # Track messages sent to owners
        "user_message_id": query.message.message_id,  # Track user's confirmation message
    }
    await membership_requests_col().insert_one(request_doc)
    log.info(f"[Membership] New request: {user.id} → {group_name}")
    
    # Notify user
    await query.edit_message_text(
        MEMBERSHIP_REQUEST_SENT.format(group_name=group_name),
        parse_mode="HTML"
    )
    
    # Notify all owners
    user_mention = (
        f'<a href="tg://user?id={user.id}">@{user.username}</a>'
        if user.username
        else f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
    )
    owner_message_ids = []
    
    for owner_id in OWNER_IDS:
        try:
            keyboard = build_duration_keyboard(request_id)
            msg = await context.bot.send_message(
                owner_id,
                MEMBERSHIP_OWNER_REQUEST.format(
                    group_name=group_name,
                    user_mention=user_mention,
                    user_id=user.id,
                ),
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            owner_message_ids.append({"owner_id": owner_id, "message_id": msg.message_id})
        except Exception as e:
            log.error(f"[Membership] Failed to notify owner {owner_id}: {e}")
    
    # Save message IDs for later cleanup
    await membership_requests_col().update_one(
        {"request_id": request_id},
        {"$set": {"owner_message_ids": owner_message_ids}}
    )


# ─────────────────────────────────────────────────────────────────────────────
# Owner: Approve/Decline Callbacks
# ─────────────────────────────────────────────────────────────────────────────

async def approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle owner approving a request."""
    query = update.callback_query
    owner = update.effective_user
    
    # Parse callback data: mem_approve:<request_id>:<days>
    data = query.data.split(":")
    if len(data) < 3:
        await query.answer("Invalid data")
        return
    
    request_id = data[1]
    days = int(data[2])
    
    # Get request
    col = membership_requests_col()
    request = await col.find_one({"request_id": request_id})
    
    if not request:
        await query.answer("Request not found")
        await query.message.delete()
        return
    
    # Check if already handled
    if request["status"] != "pending":
        await query.answer("Already handled by another owner")
        await query.message.delete()
        return
    
    # Mark as approved
    await col.update_one(
        {"request_id": request_id},
        {"$set": {"status": "approved", "handled_by": owner.id, "days": days}}
    )
    
    user_id = request["user_id"]
    group_id = request["group_id"]
    group = await get_group_by_id(group_id)
    group_name = group["group_name"] if group else "Unknown Group"
    
    # Create membership
    expires_at = datetime.utcnow() + timedelta(days=days)
    await memberships_col().update_one(
        {"user_id": user_id, "group_id": group_id},
        {"$set": {
            "user_id": user_id,
            "group_id": group_id,
            "approved_at": datetime.utcnow(),
            "expires_at": expires_at,
            "status": "active",
            "days_granted": days,
            "approved_by": owner.id,
        }},
        upsert=True,
    )
    log.info(f"[Membership] Approved: {user_id} → {group_name} ({days}d) by {owner.id}")
    
    # Generate invite link
    try:
        invite_link = await context.bot.create_chat_invite_link(
            group_id,
            expire_date=datetime.utcnow() + timedelta(hours=24),
            member_limit=1,
            name=f"User_{user_id}",
        )
        join_url = invite_link.invite_link
    except Exception as e:
        log.error(f"[Membership] Failed to create invite link: {e}")
        await query.answer("Failed to create invite link!")
        return
    
    # Get user info for confirmation message
    try:
        user_info = await context.bot.get_chat(user_id)
        user_mention = f'<a href="tg://user?id={user_id}">{user_info.first_name}</a>'
    except Exception:
        user_mention = f'<a href="tg://user?id={user_id}">User {user_id}</a>'
    
    # Notify user
    try:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(MEMBERSHIP_JOIN_BTN, url=join_url)
        ]])
        msg = await context.bot.send_message( 
            user_id, 
            MEMBERSHIP_APPROVED.format( 
                group_name=group_name, 
                days=days, 
                expires=format_expiry(expires_at), 
            ), 
            parse_mode="HTML", 
            reply_markup=keyboard, 
        ) 
        await context.bot.pin_chat_message(user_id, msg.id)
    except Exception as e:
        log.error(f"[Membership] Failed to notify user {user_id}: {e}")
    
    # Delete messages from all owners
    await cleanup_owner_messages(context.bot, request)
    
    # Send confirmation to the owner who approved
    try:
        await context.bot.send_message(
            owner.id,
            MEMBERSHIP_OWNER_APPROVED.format(
                group_name=group_name,
                user_mention=user_mention,
                days=days,
                expires=format_expiry(expires_at),
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        log.error(f"[Membership] Failed to send confirmation to owner {owner.id}: {e}")
    
    await query.answer(f"✅ Approved for {days} days!")


async def decline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle owner declining a request."""
    query = update.callback_query
    owner = update.effective_user
    
    # Parse callback data: mem_decline:<request_id>
    data = query.data.split(":")
    if len(data) < 2:
        await query.answer("Invalid data")
        return
    
    request_id = data[1]
    
    # Get request
    col = membership_requests_col()
    request = await col.find_one({"request_id": request_id})
    
    if not request:
        await query.answer("Request not found")
        await query.message.delete()
        return
    
    # Check if already handled
    if request["status"] != "pending":
        await query.answer("Already handled by another owner")
        await query.message.delete()
        return
    
    # Mark as declined
    await col.update_one(
        {"request_id": request_id},
        {"$set": {"status": "declined", "handled_by": owner.id}}
    )
    
    user_id = request["user_id"]
    group_id = request["group_id"]
    group = await get_group_by_id(group_id)
    group_name = group["group_name"] if group else "Unknown Group"
    
    log.info(f"[Membership] Declined: {user_id} → {group_name} by {owner.id}")
    
    # Notify user
    try:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(MEMBERSHIP_CONTACT_SUPPORT, url=f"https://t.me/{SUPPORT_USERNAME}")
        ]])
        await context.bot.send_message(
            user_id,
            MEMBERSHIP_DECLINED.format(group_name=group_name),
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except Exception as e:
        log.error(f"[Membership] Failed to notify user {user_id}: {e}")
    
    # Delete messages from all owners
    await cleanup_owner_messages(context.bot, request)
    
    await query.answer("❌ Request declined")


async def cleanup_owner_messages(bot, request: dict) -> None:
    """Delete approval messages from all owners and user's request confirmation message."""
    # Delete owner messages
    for msg_info in request.get("owner_message_ids", []):
        try:
            await bot.delete_message(msg_info["owner_id"], msg_info["message_id"])
        except Exception:
            pass  # Ignore if message already deleted
    
    # Delete user's confirmation message
    user_msg_id = request.get("user_message_id")
    if user_msg_id:
        try:
            await bot.delete_message(request["user_id"], user_msg_id)
        except Exception:
            pass  # Ignore if message already deleted


# ─────────────────────────────────────────────────────────────────────────────
# Owner: Toggle Group Active/Inactive
# ─────────────────────────────────────────────────────────────────────────────

async def toggle_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle group active/inactive status and update message inline."""
    query = update.callback_query
    bot = context.bot
    
    # Verify owner
    if query.from_user.id not in OWNER_IDS:
        await query.answer("Unauthorized")
        return
    
    # Parse callback data: mem_toggle:<group_id>
    data = query.data.split(":")
    if len(data) < 2:
        await query.answer("Invalid data")
        return
    
    group_id = int(data[1])
    
    # Get current state
    group = await get_group_by_id(group_id)
    if not group:
        await query.answer("Group not found")
        return
    
    # Toggle status in DB
    new_status = not group.get("is_active", True)
    await managed_groups_col().update_one(
        {"group_id": group_id},
        {"$set": {"is_active": new_status}}
    )
    
    group_name = group["group_name"]
    if new_status:
        await query.answer(f"✅ {group_name} activated")
    else:
        await query.answer(f"❌ {group_name} deactivated")
    
    # Rebuild and edit the message inline
    text, keyboard = await build_groups_message(bot)
    try:
        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except Exception as e:
        log.debug(f"[Membership] Failed to edit groups message: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# ChatMemberUpdated: Track bot added/removed from groups
# ─────────────────────────────────────────────────────────────────────────────

async def track_bot_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Track when bot is added/removed from groups.
    This is how we discover groups - there's no API to list all chats.
    """
    my_chat_member = update.my_chat_member
    if not my_chat_member:
        return
    
    chat = my_chat_member.chat
    new_status = my_chat_member.new_chat_member.status
    old_status = my_chat_member.old_chat_member.status
    
    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        return
    
    bot = context.bot
    group_id = chat.id
    group_name = chat.title or "Unknown Group"
    
    # Bot was added or promoted to admin
    if new_status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER]:
        # Check if bot is actually admin
        try:
            member = await bot.get_chat_member(group_id, bot.id)
            if member.status == ChatMemberStatus.ADMINISTRATOR:
                await sync_group(bot, group_id, group_name)
                log.info(f"[Membership] Bot added as admin to: {group_name} ({group_id})")
            else:
                log.debug(f"[Membership] Bot added to {group_name} but not as admin")
        except Exception as e:
            log.error(f"[Membership] Error checking bot status in {group_id}: {e}")
    
    # Bot was removed or demoted
    elif new_status in [ChatMemberStatus.LEFT, ChatMemberStatus.BANNED]:
        col = managed_groups_col()
        result = await col.delete_one({"group_id": group_id})
        if result.deleted_count:
            log.info(f"[Membership] Bot removed from: {group_name} ({group_id})")



# ─────────────────────────────────────────────────────────────────────────────
# Plugin registration
# ─────────────────────────────────────────────────────────────────────────────

def register(app: Application) -> None:
    """Register membership handlers."""
    # Owner commands
    app.add_handler(CommandHandler("groups", groups_command))
    app.add_handler(CommandHandler("list", groups_command))
    app.add_handler(CommandHandler("addgroup", addgroup_command))
    app.add_handler(CommandHandler("add", addgroup_command))
    
    # Track bot added/removed/promoted in groups
    app.add_handler(ChatMemberHandler(track_bot_membership, ChatMemberHandler.MY_CHAT_MEMBER))
    
    # Callback handlers
    app.add_handler(CallbackQueryHandler(request_access_callback, pattern=r"^mem_request:"))
    app.add_handler(CallbackQueryHandler(approve_callback, pattern=r"^mem_approve:"))
    app.add_handler(CallbackQueryHandler(decline_callback, pattern=r"^mem_decline:"))
    app.add_handler(CallbackQueryHandler(toggle_group_callback, pattern=r"^mem_toggle:"))
    
    log.info("Membership plugin registered.")
