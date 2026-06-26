"""
Reaction Forwarder Plugin.
Forwards messages that the userbot reacts to with trigger emoji.
Uses pyrogram for userbot functionality.
"""
import asyncio
import os
from pathlib import Path
from typing import Optional, List

from pyrogram import Client
from pyrogram.types import Message, InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio, MessageReactionUpdated
from pyrogram.handlers import RawUpdateHandler, MessageReactionHandler
from pyrogram.raw.types import UpdateMessageReactions, UpdateRecentReactions, UpdateEditMessage, ReactionEmoji
from pyrogram.raw.base import Update
from pyrogram.errors import ChatForwardsRestricted, FloodWait
from telegram.ext import Application

from config import API_ID, API_HASH, REACTION_FORWARDTO, TRIGGER_EMOJI
from util.logging import log
from util.sessions import get_reaction_session
from util.watermark_thumb import add_watermark
from util.shared_helpers import clean_caption, download_media, download_thumbnail, cleanup_files

_userbot: Optional[Client] = None
_userbot_task: Optional[asyncio.Task] = None
_my_user_id: Optional[int] = None  # The userbot's own user ID
_processed_messages: dict[str, float] = {}
_processed_messages_lock = asyncio.Lock()
_last_scan_time: dict[int, float] = {}
_SCAN_COOLDOWN = 1.0  # Minimum seconds between scans of same chat
_processed_albums: dict[str, float] = {}  # Track processed album media_group_ids to prevent duplicates
_processed_albums_lock = asyncio.Lock()

# ─────────────────────────────────────────────────────────────────────────────
# Reaction Queue - First React First Serve (FIFO)
# ─────────────────────────────────────────────────────────────────────────────
_reaction_queue: asyncio.Queue = asyncio.Queue(200)
_queue_processor_task: Optional[asyncio.Task] = None
_semaphore = asyncio.Semaphore(1)  # Strict FIFO ordering - process one at a time

TEMP_DIR = Path(__file__).parent.parent / "data" / "temp" / "reaction"
TEMP_DIR.mkdir(parents=True, exist_ok=True)


def get_forward_target() -> int | str:
    """
    Parse REACTION_FORWARDTO config.
    Returns 'me' for saved messages or chat_id.
    """
    target = REACTION_FORWARDTO.strip().lower()
    if target == 'saved':
        return 'me'
    try:
        return int(REACTION_FORWARDTO)
    except ValueError:
        return 'me'



async def send_downloaded_media(client: Client, target: int | str, message: Message, media_path: str, caption: Optional[str], thumb_path: Optional[str] = None) -> None:
    """Send downloaded media to target via userbot."""
    if thumb_path and not os.path.exists(thumb_path):
        thumb_path = None
    try:
        if message.photo:
            await client.send_photo(chat_id=target, photo=media_path, caption=caption)
        elif message.video:
            await client.send_video(
                chat_id=target, video=media_path, caption=caption, thumb=thumb_path,
                duration=message.video.duration if message.video else None,
                width=message.video.width if message.video else None,
                height=message.video.height if message.video else None,
                supports_streaming=True,
            )
        elif message.animation:
            await client.send_animation(chat_id=target, animation=media_path, caption=caption, thumb=thumb_path)
        elif message.audio:
            await client.send_audio(
                chat_id=target, audio=media_path, caption=caption, thumb=thumb_path,
                duration=message.audio.duration if message.audio else None,
                performer=message.audio.performer if message.audio else None,
                title=message.audio.title if message.audio else None,
            )
        elif message.voice:
            await client.send_voice(chat_id=target, voice=media_path, caption=caption)
        elif message.video_note:
            await client.send_video_note(chat_id=target, video_note=media_path, thumb=thumb_path)
        elif message.sticker:
            await client.send_sticker(chat_id=target, sticker=media_path)
        elif message.document:
            await client.send_document(
                chat_id=target, document=media_path, caption=caption, thumb=thumb_path,
                file_name=message.document.file_name if message.document else None,
            )
        else:
            await client.send_document(chat_id=target, document=media_path, caption=caption)
    except Exception as e:
        log.error(f"[Reaction] Failed to send downloaded media: {e}", exc_info=True)


async def handle_media_group(client: Client, target: int | str, messages: List[Message], max_retries: int = 2) -> None:
    """Download and send album/media group using userbot send_media_group."""
    media_list = []
    downloaded: List[tuple] = []

    try:
        for i, msg in enumerate(messages):
            media_path = None
            thumb_path = None

            for attempt in range(max_retries + 1):
                try:
                    media_path = await download_media(msg, TEMP_DIR)
                    if media_path and os.path.exists(media_path):
                        break
                    if attempt < max_retries:
                        await asyncio.sleep(1)
                except Exception as e:
                    log.warning(f"[Reaction] Album download attempt {attempt+1} for msg {msg.id}: {e}")
                    if attempt < max_retries:
                        await asyncio.sleep(1)

            if not media_path or not os.path.exists(media_path):
                log.error(f"[Reaction] Could not download msg {msg.id} after {max_retries+1} attempts, skipping")
                continue

            thumb_path = await download_thumbnail(client, msg, TEMP_DIR)
            if thumb_path:
                thumb_path = add_watermark(thumb_path)
            downloaded.append((media_path, thumb_path))

            caption = clean_caption(msg.caption) if i == 0 else None

            if msg.photo:
                media_list.append(InputMediaPhoto(media_path, caption=caption))
            elif msg.video:
                media_list.append(InputMediaVideo(
                    media_path, caption=caption,
                    duration=msg.video.duration if msg.video else None,
                    width=msg.video.width if msg.video else None,
                    height=msg.video.height if msg.video else None,
                    supports_streaming=True,
                    thumb=thumb_path if thumb_path and os.path.exists(thumb_path) else None,
                ))
            elif msg.audio:
                media_list.append(InputMediaAudio(media_path, caption=caption))
            elif msg.document:
                media_list.append(InputMediaDocument(media_path, caption=caption))

        if media_list:
            await client.send_media_group(chat_id=target, media=media_list)
            log.debug(f"[Reaction] Sent album of {len(media_list)} items to {target}")
        else:
            log.error("[Reaction] No media downloaded from album, nothing sent")

    except Exception as e:
        log.error(f"[Reaction] Failed to send media group: {e}", exc_info=True)
    finally:
        for mp, tp in downloaded:
            cleanup_files(mp, tp)


async def forward_message(client: Client, message: Message) -> None:
    """
    Forward a message to the target destination.
    - Albums: Forward ALL messages in the album in sequence
    - Private chats: Always forward (no restrictions)
    - Groups/Channels with forwarding enabled: Forward directly via copy_message
    - Groups/Channels with forwarding disabled: Download and re-upload
    """
    global _processed_albums
    target = get_forward_target()
    caption = clean_caption(message.caption or message.text)
    chat = message.chat
    is_private = chat.type.value == "private" if hasattr(chat.type, 'value') else str(chat.type) == "ChatType.PRIVATE"

    # Album handling
    if message.media_group_id:
        album_key = f"{chat.id}:{message.media_group_id}"
        async with _processed_albums_lock:
            now = asyncio.get_running_loop().time()
            if album_key in _processed_albums and now - _processed_albums[album_key] < 60:
                return
            _processed_albums[album_key] = now
            if len(_processed_albums) > 100:
                _processed_albums = {k: v for k, v in _processed_albums.items() if now - v < 300}

        try:
            group_messages = sorted(
                await client.get_media_group(message.chat.id, message.id),
                key=lambda m: m.id,
            )
            # Reaction always uses userbot — download + send_media_group
            await handle_media_group(client, target, group_messages)
        except Exception as e:
            log.error(f"[Reaction] Failed to process album: {e}", exc_info=True)
        return

    # Single message handling
    try:
        if message.media:
            await client.copy_message(
                chat_id=target,
                from_chat_id=message.chat.id,
                message_id=message.id,
                caption=caption,
            )
        else:
            if caption:
                await client.send_message(target, caption)
        return
    except ChatForwardsRestricted:
        if is_private:
            log.warning("[Reaction] Private chat has forwarding restricted")
            return
    except Exception as e:
        if "CHAT_FORWARDS_RESTRICTED" in str(e):
            if is_private:
                log.warning("[Reaction] Private chat has forwarding restricted")
                return
        else:
            log.error(f"[Reaction] Failed to forward message: {e}", exc_info=True)
            return
    
    # Fallback: Download and re-upload single message
    media_path = None
    thumb_path = None
    try:
        if message.media:
            media_path = await download_media(message, TEMP_DIR)
            if media_path:
                thumb_path = await download_thumbnail(client, message, TEMP_DIR)
                if thumb_path:
                    thumb_path = add_watermark(thumb_path)
                await send_downloaded_media(client, target, message, media_path, caption, thumb_path)
        else:
            if caption:
                await client.send_message(target, caption)
    except Exception as e:
        log.error(f"[Reaction] Failed to download/upload media: {e}", exc_info=True)
    finally:
        cleanup_files(media_path, thumb_path)


# ─────────────────────────────────────────────────────────────────────────────
# Queue System - First React First Serve
# ─────────────────────────────────────────────────────────────────────────────

async def enqueue_reaction(chat_id: int, message_id: int) -> None:
    """Add a reaction to the queue for processing. First react = first serve."""
    try:
        _reaction_queue.put_nowait({
            "chat_id": chat_id,
            "message_id": message_id,
            "queued_at": asyncio.get_running_loop().time(),
        })
        log.debug(f"[Reaction] Queued message {message_id} from chat {chat_id} (queue size: {_reaction_queue.qsize()})")
    except asyncio.QueueFull:
        log.debug(f"[Reaction] Queue full (200), dropping message {message_id} from chat {chat_id}")


async def process_reaction_queue() -> None:
    """Background worker to process reactions in FIFO order."""
    global _userbot
    
    log.debug("[Reaction] 🔄 Queue processor started")
    
    try:
        while True:
            # Wait for next item in queue
            item = await _reaction_queue.get()
            
            chat_id = item["chat_id"]
            message_id = item["message_id"]
            queued_at = item.get("queued_at", 0)
            
            queue_size = _reaction_queue.qsize()
            log.debug(f"[Reaction] 📤 Processing message {message_id} from chat {chat_id} (remaining in queue: {queue_size})")
            
            async with _semaphore:
                try:
                    if _userbot and _userbot.is_connected:
                        message = await _userbot.get_messages(chat_id, message_id)
                        if message and message.media:
                            await forward_message(_userbot, message)
                            log.debug(f"[Reaction] Forwarded message {message_id} to {get_forward_target()}")
                        elif message:
                            log.debug(f"[Reaction] Skipping non-media message {message_id}")
                        else:
                            log.warning(f"[Reaction] Could not fetch message {message_id} from chat {chat_id}")
                    else:
                        log.warning(f"[Reaction] Userbot not connected, skipping message {message_id}")
                except FloodWait as e:
                    log.debug(f"[Reaction] FloodWait {e.value}s for message {message_id}, re-queuing after sleep")
                    await asyncio.sleep(e.value)
                    try:
                        _reaction_queue.put_nowait({"chat_id": chat_id, "message_id": message_id,
                                                    "queued_at": asyncio.get_running_loop().time()})
                    except asyncio.QueueFull:
                        log.debug(f"[Reaction] Queue full after FloodWait, dropping message {message_id}")
                except Exception as e:
                    log.error(f"[Reaction] Queue processor error for message {message_id}: {e}")
                finally:
                    _reaction_queue.task_done()
    except asyncio.CancelledError:
        log.debug("[Reaction] Queue processor cancelled")
        # Drain queue
        while not _reaction_queue.empty():
            try:
                _reaction_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        raise
    except Exception as e:
        log.error(f"[Reaction] Queue processor fatal error: {e}", exc_info=True)


async def handle_edit_message_for_reactions(client: Client, update, users: dict) -> None:
    """
    Handle UpdateEditMessage to detect reactions in private chats.
    In private DMs, adding a reaction triggers UpdateEditMessage, not UpdateMessageReactions.
    We check if the edited message has our trigger emoji reaction.
    """
    global _my_user_id, _processed_messages
    
    try:
        # Get the raw message from the update
        raw_message = getattr(update, 'message', None)
        if not raw_message:
            return
        
        # Check if this is a private chat (PeerUser)
        peer_id = getattr(raw_message, 'peer_id', None)
        if not peer_id:
            return
        
        # Only handle private chats
        peer_type = type(peer_id).__name__
        if peer_type != 'PeerUser':
            return  # Not a private chat
        
        user_id = getattr(peer_id, 'user_id', None)
        msg_id = getattr(raw_message, 'id', None)
        
        if not user_id or not msg_id:
            return
        
        log.debug(f"[Reaction] EditMsg: Private chat {user_id}, msg {msg_id}")
        
        # Check if this message has reactions with our trigger emoji
        reactions = getattr(raw_message, 'reactions', None)
        if not reactions:
            log.debug(f"[Reaction] EditMsg: No reactions on message {msg_id}")
            return
        
        # Get the results (list of reaction counts)
        results = getattr(reactions, 'results', None)
        if not results:
            log.debug(f"[Reaction] EditMsg: No reaction results")
            return
        
        # Check if we reacted with trigger emoji (chosen_order is set for our reactions)
        my_reaction_found = False
        for result in results:
            chosen_order = getattr(result, 'chosen_order', None)
            
            # If chosen_order is not None, WE reacted with this emoji
            if chosen_order is not None:
                reaction_emoji = getattr(result, 'reaction', None)
                emoticon = None
                if reaction_emoji:
                    if hasattr(reaction_emoji, 'emoticon'):
                        emoticon = reaction_emoji.emoticon
                
                log.debug(f"[Reaction] EditMsg: Found our reaction - emoji={emoticon}, chosen_order={chosen_order}")
                
                if emoticon == TRIGGER_EMOJI:
                    my_reaction_found = True
                    log.debug(f"[Reaction] EditMsg: ✓ Found our {TRIGGER_EMOJI} on message {msg_id}!")
                    break
        
        if not my_reaction_found:
            return
        
        # Check if already processed
        message_key = f"{user_id}:{msg_id}"
        async with _processed_messages_lock:
            now = asyncio.get_running_loop().time()
            if message_key in _processed_messages and now - _processed_messages[message_key] < 300:
                log.debug(f"[Reaction] EditMsg: Message {message_key} recently processed")
                return
            _processed_messages[message_key] = now
            if len(_processed_messages) > 1000:
                _processed_messages = {k: v for k, v in _processed_messages.items() if now - v < 600}
        
        # Enqueue for FIFO processing
        await enqueue_reaction(user_id, msg_id)
        log.debug(f"[Reaction] EditMsg: Queued message {msg_id} from private chat {user_id}")
            
    except Exception as e:
        log.error(f"[Reaction] EditMsg: Error: {e}", exc_info=True)


async def handle_recent_reactions_update(client: Client, users: dict, chats: dict) -> None:
    """
    Handle UpdateRecentReactions for private DM reactions.
    This is triggered when we react to a message - we use the users dict to find the private chat.
    """
    global _my_user_id, _processed_messages
    import time
    
    log.debug(f"[Reaction] DM: Processing UpdateRecentReactions")
    log.debug(f"[Reaction] DM: users dict has {len(users)} users")
    log.debug(f"[Reaction] DM: My user ID is {_my_user_id}")
    
    try:
        # Find non-self users from the update - these are the private chats we just interacted with
        private_chat_users = []
        for user_id, user_data in users.items():
            # Handle both raw types and high-level types
            is_self = getattr(user_data, 'is_self', False)
            log.debug(f"[Reaction] DM: User {user_id} - is_self={is_self}, type={type(user_data).__name__}")
            
            # Also check by comparing with our user ID
            if not is_self and user_id != _my_user_id:
                private_chat_users.append(user_id)
                log.debug(f"[Reaction] DM: ✓ Found private chat user: {user_id}")
        
        if not private_chat_users:
            log.debug(f"[Reaction] DM: No private chat users found in update")
            return
        
        # Scan each private chat for messages with our trigger reaction
        for chat_id in private_chat_users:
            # Check cooldown to avoid rapid re-scans
            current_time = time.time()
            last_scan = _last_scan_time.get(chat_id, 0)
            if current_time - last_scan < _SCAN_COOLDOWN:
                log.debug(f"[Reaction] DM: Skipping chat {chat_id} (cooldown - {current_time - last_scan:.1f}s ago)")
                continue
            _last_scan_time[chat_id] = current_time
            
            log.debug(f"[Reaction] DM: Scanning chat {chat_id} for {TRIGGER_EMOJI} reactions...")
            
            try:
                # Get last 5 messages from this private chat
                messages = []
                async for msg in client.get_chat_history(chat_id, limit=5):
                    messages.append(msg)
                
                log.debug(f"[Reaction] DM: Found {len(messages)} messages in chat {chat_id}")
                
                # Check each message for our trigger emoji reaction
                for message in messages:
                    log.debug(f"[Reaction] DM: Checking message {message.id} - has reactions: {message.reactions is not None}")
                    
                    if not message or not message.reactions:
                        continue
                    
                    # Log what reactions we found
                    log.debug(f"[Reaction] DM: Message {message.id} reactions: {message.reactions}")
                    
                    # Check if we reacted with trigger emoji
                    has_our_reaction = False
                    for reaction in message.reactions.reactions:
                        # Log each reaction for debugging
                        emoji = getattr(reaction, 'emoji', None)
                        chosen_order = getattr(reaction, 'chosen_order', None)
                        log.debug(f"[Reaction] DM: Reaction - emoji={emoji}, chosen_order={chosen_order}")
                        
                        # Check if this is our reaction (chosen_order is set)
                        if chosen_order is not None and emoji == TRIGGER_EMOJI:
                            has_our_reaction = True
                            log.debug(f"[Reaction] DM: ✓ Found our {TRIGGER_EMOJI} on message {message.id}")
                            break
                    
                    if not has_our_reaction:
                        log.debug(f"[Reaction] DM: Message {message.id} - no matching reaction")
                        continue
                    
                    # Check if already processed
                    message_key = f"{chat_id}:{message.id}"
                    async with _processed_messages_lock:
                        now = asyncio.get_running_loop().time()
                        if message_key in _processed_messages and now - _processed_messages[message_key] < 300:
                            log.debug(f"[Reaction] DM: Message {message_key} already processed")
                            continue
                        _processed_messages[message_key] = now
                        if len(_processed_messages) > 1000:
                            _processed_messages = {k: v for k, v in _processed_messages.items() if now - v < 600}
                    
                    # Enqueue for FIFO processing
                    await enqueue_reaction(chat_id, message.id)
                    log.debug(f"[Reaction] DM: Queued message {message.id} from chat {chat_id}")
                    
            except Exception as e:
                log.error(f"[Reaction] DM: Failed to scan chat {chat_id}: {e}", exc_info=True)
                
    except Exception as e:
        log.error(f"[Reaction] DM: Error: {e}", exc_info=True)


async def handle_raw_update(client: Client, update: Update, users: dict, chats: dict) -> None:
    """
    Handle raw updates for UpdateMessageReactions.
    This catches reactions in groups/channels where chosen_order indicates our reaction.
    """
    global _my_user_id, _processed_messages
    
    update_type = type(update).__name__
    log.debug(f"[Reaction] 🔔 RAW: {update_type}")
    
    if isinstance(update, UpdateRecentReactions):
        log.debug(f"[Reaction] 📩 UpdateRecentReactions received! users={list(users.keys())}, chats={list(chats.keys())}")
        await handle_recent_reactions_update(client, users, chats)
        return
    
    if isinstance(update, UpdateEditMessage):
        await handle_edit_message_for_reactions(client, update, users)
        return
    
    if not isinstance(update, UpdateMessageReactions):
        return
    
    log.debug(f"[Reaction] 📩 UpdateMessageReactions received for msg {update.msg_id}")
    
    try:
        peer = update.peer
        peer_type = type(peer).__name__
        reactions = update.reactions
        
        if not reactions:
            log.debug(f"[Reaction] RawUpdate: No reactions object, skipping")
            return
        
        recent_reactions = getattr(reactions, 'recent_reactions', None)
        results = getattr(reactions, 'results', None)
        
        my_reaction_found = False
        
        if recent_reactions:
            for reaction in recent_reactions:
                peer_id = getattr(reaction, 'peer_id', None)
                reactor_id = None
                if peer_id:
                    reactor_id = getattr(peer_id, 'user_id', None)
                
                if reactor_id == _my_user_id:
                    reaction_emoji = getattr(reaction, 'reaction', None)
                    emoticon = None
                    if reaction_emoji:
                        if isinstance(reaction_emoji, ReactionEmoji):
                            emoticon = reaction_emoji.emoticon
                        elif hasattr(reaction_emoji, 'emoticon'):
                            emoticon = reaction_emoji.emoticon
                    
                    if emoticon == TRIGGER_EMOJI:
                        my_reaction_found = True
                        log.debug(f"[Reaction] RawUpdate: ✓ Found our {TRIGGER_EMOJI} in recent_reactions!")
                        break
        
        if not my_reaction_found and results:
            for result in results:
                chosen_order = getattr(result, 'chosen_order', None)
                
                if chosen_order is not None:
                    reaction_emoji = getattr(result, 'reaction', None)
                    emoticon = None
                    if reaction_emoji:
                        if isinstance(reaction_emoji, ReactionEmoji):
                            emoticon = reaction_emoji.emoticon
                        elif hasattr(reaction_emoji, 'emoticon'):
                            emoticon = reaction_emoji.emoticon
                    
                    if emoticon == TRIGGER_EMOJI:
                        my_reaction_found = True
                        log.debug(f"[Reaction] RawUpdate: ✓ Found our {TRIGGER_EMOJI} via chosen_order!")
                        break
        
        if not my_reaction_found:
            log.debug(f"[Reaction] RawUpdate: No matching reaction found, skipping")
            return
        
        chat_id = None
        peer_type_str = "unknown"
        
        if hasattr(peer, 'channel_id'):
            chat_id = -1000000000000 - peer.channel_id
            peer_type_str = "channel"
        elif hasattr(peer, 'chat_id'):
            chat_id = -peer.chat_id
            peer_type_str = "group"
        elif hasattr(peer, 'user_id'):
            chat_id = peer.user_id
            peer_type_str = "private"
        
        if not chat_id:
            log.warning(f"[Reaction] Could not extract chat_id from peer")
            return
        
        msg_id = update.msg_id
        
        message_key = f"{chat_id}:{msg_id}"
        async with _processed_messages_lock:
            now = asyncio.get_running_loop().time()
            if message_key in _processed_messages and now - _processed_messages[message_key] < 300:
                log.debug(f"[Reaction] Message already processed")
                return
            _processed_messages[message_key] = now
            if len(_processed_messages) > 1000:
                _processed_messages = {k: v for k, v in _processed_messages.items() if now - v < 600}
        
        await enqueue_reaction(chat_id, msg_id)
        log.debug(f"[Reaction] RawUpdate: Queued message {msg_id} from chat {chat_id}")
            
    except Exception as e:
        log.error(f"[Reaction] RawUpdate error: {e}", exc_info=True)


async def handle_reaction_updated(client: Client, reaction_update: MessageReactionUpdated) -> None:
    """
    Handle high-level MessageReactionUpdated events.
    This is the primary handler for reactions - works for private chats and groups.
    """
    global _my_user_id, _processed_messages
    
    try:
        chat = reaction_update.chat
        message_id = reaction_update.message_id
        user = reaction_update.user
        old_reactions = reaction_update.old_reaction or []
        new_reactions = reaction_update.new_reaction or []
        
        log.debug(f"[Reaction] HighLevel: 📩 Event received - chat={chat.id}, msg={message_id}, user={user.id if user else 'None'}, my_id={_my_user_id}")
        log.debug(f"[Reaction] HighLevel: 📩 old_reactions={[getattr(r, 'emoji', getattr(r, 'emoticon', '?')) for r in old_reactions]}, new_reactions={[getattr(r, 'emoji', getattr(r, 'emoticon', '?')) for r in new_reactions]}")
        
        log.debug(f"[Reaction] HighLevel: Reaction update in chat {chat.id}, msg {message_id}")
        
        if user and user.id != _my_user_id:
            log.debug(f"[Reaction] HighLevel: Not our reaction")
            return
        
        if not user:
            log.debug(f"[Reaction] HighLevel: Anonymous reaction, skipping")
            return
        
        old_emojis = set()
        new_emojis = set()
        
        for r in old_reactions:
            if hasattr(r, 'emoji'):
                old_emojis.add(r.emoji)
            elif hasattr(r, 'emoticon'):
                old_emojis.add(r.emoticon)
        
        for r in new_reactions:
            if hasattr(r, 'emoji'):
                new_emojis.add(r.emoji)
            elif hasattr(r, 'emoticon'):
                new_emojis.add(r.emoticon)
        
        if TRIGGER_EMOJI not in new_emojis:
            return
        
        if TRIGGER_EMOJI in old_emojis:
            return
        
        log.debug(f"[Reaction] HighLevel: ✓ Found new {TRIGGER_EMOJI} reaction from us!")
        
        message_key = f"{chat.id}:{message_id}"
        async with _processed_messages_lock:
            now = asyncio.get_running_loop().time()
            if message_key in _processed_messages and now - _processed_messages[message_key] < 300:
                log.debug(f"[Reaction] HighLevel: Message {message_key} already processed, skipping")
                return
            _processed_messages[message_key] = now
            if len(_processed_messages) > 1000:
                _processed_messages = {k: v for k, v in _processed_messages.items() if now - v < 600}
        
        await enqueue_reaction(chat.id, message_id)
        log.debug(f"[Reaction] HighLevel: Queued message {message_id} from chat {chat.id}")
            
    except Exception as e:
        log.error(f"[Reaction] HighLevel: Error: {e}", exc_info=True)


async def start_userbot() -> None:
    """Start the reaction userbot."""
    global _userbot, _my_user_id
    
    session_string = get_reaction_session()
    if not session_string:
        log.debug("[Reaction] Userbot disabled (no valid session string).")
        return
    
    log.debug("[Reaction] Starting pyrogram userbot...")
    
    try:
        _userbot = Client(
            name="reaction_userbot",
            api_id=API_ID,
            api_hash=API_HASH,
            session_string=session_string,
            in_memory=True,
        )
        
        _userbot.add_handler(MessageReactionHandler(handle_reaction_updated))
        _userbot.add_handler(RawUpdateHandler(handle_raw_update))
        
        await _userbot.start()
        
        me = await _userbot.get_me()
        _my_user_id = me.id
        log.debug(f"[Reaction] ✓ Userbot started as {me.first_name} (@{me.username})")
        
        global _queue_processor_task
        _queue_processor_task = asyncio.create_task(process_reaction_queue())
        log.debug(f"[Reaction] ✓ Queue processor started (First React First Serve)")
        
        log.debug(f"[Reaction] ✓ Listening for {TRIGGER_EMOJI} reactions to forward to {get_forward_target()}")
        
        
    except asyncio.CancelledError:
        log.debug("[Reaction] Userbot task cancelled.")
        raise
    except Exception as e:
        log.error(f"[Reaction] Userbot failed to start: {e}", exc_info=True)


async def stop_userbot() -> None:
    """Stop the reaction userbot."""
    global _userbot, _userbot_task, _queue_processor_task
    
    if _queue_processor_task and not _queue_processor_task.done():
        _queue_processor_task.cancel()
        try:
            await _queue_processor_task
        except asyncio.CancelledError:
            pass
    _queue_processor_task = None
    
    if _userbot_task and not _userbot_task.done():
        _userbot_task.cancel()
        try:
            await _userbot_task
        except asyncio.CancelledError:
            pass
    
    _userbot_task = None
    _userbot = None


def register(app: Application) -> None:
    """Register reaction forwarder plugin."""
    global _userbot_task
    
    session_string = get_reaction_session()
    if not session_string:
        log.debug("[Reaction] Plugin skipped (no valid session string).")
        return
    
    from util import tasks
    _userbot_task = tasks.create_task(start_userbot(), name="reaction_userbot")
    
    log.debug("[Reaction] ✓ Plugin registered.")
