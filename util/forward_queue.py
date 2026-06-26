"""
Forward Queue Management.
Handles message queuing, rate limiting, retry logic, and album batching.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from bson import ObjectId

from util.logging import log
from util.db import get_db

# Rate limiting constants
MAX_MESSAGES_PER_SECOND = 20  # Telegram limit is ~30, we stay safe
DELAY_BETWEEN_FORWARDS = 1.5  # Seconds between forwards to same target
ALBUM_WAIT_TIME = 1.5  # Seconds to wait for album parts
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 5  # Seconds base for exponential backoff

# Queue status constants
STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

# In-memory tracking
_last_forward_time: Dict[int, float] = {}  # target_chat_id -> timestamp
_album_buffer: Dict[str, Dict] = {}  # media_group_id -> {messages, timer, forwarder_id}
_queue_lock = asyncio.Lock()


def forward_queue_col():
    """Get forward queue collection."""
    return get_db().forward_queue


def live_forwarders_col():
    """Get live forwarders collection."""
    return get_db().live_forwarders


# ─────────────────────────────────────────────────────────────────────────────
# Queue Operations
# ─────────────────────────────────────────────────────────────────────────────

async def add_to_queue(
    forwarder_id: str,
    origin_chat_id: int,
    target_chat_id: int,
    message_id: int,
    media_group_id: Optional[str] = None,
) -> str:
    """
    Add a message to the forward queue.
    Returns the queue_id.
    """
    queue_doc = {
        "forwarder_id": forwarder_id,
        "origin_chat_id": origin_chat_id,
        "target_chat_id": target_chat_id,
        "message_id": message_id,
        "media_group_id": media_group_id,
        "status": STATUS_PENDING,
        "created_at": datetime.utcnow(),
        "processed_at": None,
        "retry_count": 0,
        "error": None,
    }
    
    result = await forward_queue_col().insert_one(queue_doc)
    queue_id = str(result.inserted_id)
    log.debug(f"[ForwardQueue] Added to queue: {queue_id} (msg {message_id})")
    return queue_id


async def get_pending_items(limit: int = 50) -> List[Dict]:
    """Get pending queue items, ordered by creation time."""
    cursor = forward_queue_col().find(
        {"status": STATUS_PENDING}
    ).sort("created_at", 1).limit(limit)
    return await cursor.to_list(length=limit)


async def get_failed_items_for_retry() -> List[Dict]:
    """Get failed items that can be retried."""
    return await forward_queue_col().find({
        "status": STATUS_FAILED,
        "retry_count": {"$lt": MAX_RETRIES}
    }).sort("created_at", 1).to_list(length=50)


async def mark_processing(queue_id: str) -> bool:
    """Mark item as processing. Returns False if already processed."""
    result = await forward_queue_col().update_one(
        {"_id": ObjectId(queue_id), "status": STATUS_PENDING},
        {"$set": {"status": STATUS_PROCESSING}}
    )
    return result.modified_count > 0


async def mark_completed(queue_id: str) -> None:
    """Mark item as completed."""
    await forward_queue_col().update_one(
        {"_id": ObjectId(queue_id)},
        {"$set": {
            "status": STATUS_COMPLETED,
            "processed_at": datetime.utcnow()
        }}
    )
    log.debug(f"[ForwardQueue] Marked completed: {queue_id}")


async def mark_failed(queue_id: str, error: str) -> None:
    """Mark item as failed and increment retry count."""
    await forward_queue_col().update_one(
        {"_id": ObjectId(queue_id)},
        {
            "$set": {
                "status": STATUS_FAILED,
                "error": error,
                "processed_at": datetime.utcnow()
            },
            "$inc": {"retry_count": 1}
        }
    )
    log.debug(f"[ForwardQueue] Marked failed: {queue_id} - {error}")


async def reset_for_retry(queue_id: str) -> None:
    """Reset failed item for retry."""
    await forward_queue_col().update_one(
        {"_id": ObjectId(queue_id)},
        {"$set": {"status": STATUS_PENDING, "error": None}}
    )
    log.debug(f"[ForwardQueue] Reset for retry: {queue_id}")


async def cleanup_old_completed(hours: int = 24) -> int:
    """Remove completed items older than specified hours."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    result = await forward_queue_col().delete_many({
        "status": STATUS_COMPLETED,
        "processed_at": {"$lt": cutoff}
    })
    if result.deleted_count > 0:
        log.info(f"[ForwardQueue] Cleaned up {result.deleted_count} old items")
    return result.deleted_count


async def get_queue_stats() -> Dict[str, int]:
    """Get queue statistics."""
    pipeline = [
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]
    cursor = forward_queue_col().aggregate(pipeline)
    stats = {STATUS_PENDING: 0, STATUS_PROCESSING: 0, STATUS_COMPLETED: 0, STATUS_FAILED: 0}
    async for doc in cursor:
        stats[doc["_id"]] = doc["count"]
    return stats


async def get_forwarder_queue_stats(forwarder_id: str) -> Dict[str, int]:
    """Get queue statistics for a specific forwarder."""
    pipeline = [
        {"$match": {"forwarder_id": forwarder_id}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]
    cursor = forward_queue_col().aggregate(pipeline)
    stats = {"queue": 0, "pending": 0, "failed": 0}
    async for doc in cursor:
        status = doc["_id"]
        count = doc["count"]
        if status == STATUS_PENDING:
            stats["queue"] += count
            stats["pending"] += count
        elif status == STATUS_PROCESSING:
            stats["queue"] += count
        elif status == STATUS_FAILED:
            stats["failed"] += count
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Album Handling
# ─────────────────────────────────────────────────────────────────────────────

async def buffer_album_message(
    media_group_id: str,
    forwarder_id: str,
    origin_chat_id: int,
    target_chat_id: int,
    message_id: int,
    callback,
) -> None:
    """
    Buffer album messages and process when complete.
    callback is called with (forwarder_id, origin_chat_id, target_chat_id, message_ids)
    """
    global _album_buffer
    
    async with _queue_lock:
        if media_group_id not in _album_buffer:
            _album_buffer[media_group_id] = {
                "forwarder_id": forwarder_id,
                "origin_chat_id": origin_chat_id,
                "target_chat_id": target_chat_id,
                "message_ids": [],
                "timer": None,
                "callback": callback,
            }
        
        buffer = _album_buffer[media_group_id]
        buffer["message_ids"].append(message_id)
        
        if buffer.get("timer"):
            buffer["timer"].cancel()
        
        async def process_album():
            await asyncio.sleep(ALBUM_WAIT_TIME)
            async with _queue_lock:
                if media_group_id in _album_buffer:
                    album_data = _album_buffer.pop(media_group_id)
                    message_ids = sorted(album_data["message_ids"])
                    log.debug(f"[ForwardQueue] Processing album {media_group_id} with {len(message_ids)} messages")
                    await album_data["callback"](
                        album_data["forwarder_id"],
                        album_data["origin_chat_id"],
                        album_data["target_chat_id"],
                        message_ids,
                    )
        
        buffer["timer"] = asyncio.create_task(process_album())


# ─────────────────────────────────────────────────────────────────────────────
# Rate Limiting
# ─────────────────────────────────────────────────────────────────────────────

async def wait_for_rate_limit(target_chat_id: int) -> None:
    """Wait if needed to respect rate limits."""
    global _last_forward_time
    
    now = asyncio.get_event_loop().time()
    last_time = _last_forward_time.get(target_chat_id, 0)
    elapsed = now - last_time
    
    if elapsed < DELAY_BETWEEN_FORWARDS:
        wait_time = DELAY_BETWEEN_FORWARDS - elapsed
        log.debug(f"[ForwardQueue] Rate limit: waiting {wait_time:.2f}s for target {target_chat_id}")
        await asyncio.sleep(wait_time)
    
    _last_forward_time[target_chat_id] = asyncio.get_event_loop().time()

class UploadRateLimiter:
    _last_upload = 0
    _min_interval = 12  # Start with 12s (exceeds Telegram's 11s requirement)

    @classmethod
    async def wait(cls):
        import time
        now = time.time()
        elapsed = now - cls._last_upload
        if elapsed < cls._min_interval:
            wait_time = cls._min_interval - elapsed
            log.debug(f"[ForwardQueue] Upload rate limit: waiting {wait_time:.2f}s")
            await asyncio.sleep(wait_time)
        cls._last_upload = time.time()

    @classmethod
    def update_min_interval(cls, new_value):
        cls._min_interval = max(cls._min_interval, new_value)



# ─────────────────────────────────────────────────────────────────────────────
# Forwarder DB Operations
# ─────────────────────────────────────────────────────────────────────────────

async def get_active_forwarders() -> List[Dict]:
    """Get all active forwarders."""
    return await live_forwarders_col().find(
        {"is_active": True}
    ).to_list(length=100)


async def get_all_forwarders() -> List[Dict]:
    """Get all forwarders (active and inactive)."""
    return await live_forwarders_col().find().sort("added_at", -1).to_list(length=100)


async def get_forwarder_by_id(forwarder_id: str) -> Optional[Dict]:
    """Get forwarder by ID."""
    return await live_forwarders_col().find_one({"_id": ObjectId(forwarder_id)})


async def get_forwarder_by_origin_target(origin_chat_id: int, target_chat_id: int) -> Optional[Dict]:
    """Check if a forwarder with given origin and target already exists."""
    return await live_forwarders_col().find_one({
        "origin_chat_id": origin_chat_id,
        "target_chat_id": target_chat_id,
    })


async def create_forwarder(
    origin_chat_id: int,
    origin_chat_name: str,
    target_chat_id: int,
    target_chat_name: str,
    added_by: int,
    forward_messages: bool = True,
    forward_album: bool = True,
) -> str:
    """Create a new forwarder. Returns forwarder_id."""
    doc = {
        "origin_chat_id": origin_chat_id,
        "origin_chat_name": origin_chat_name,
        "target_chat_id": target_chat_id,
        "target_chat_name": target_chat_name,
        "is_active": True,
        "added_by": added_by,
        "added_at": datetime.utcnow(),
        "last_forwarded_at": None,
        "forward_messages": forward_messages,
        "forward_album": forward_album,
    }
    result = await live_forwarders_col().insert_one(doc)
    forwarder_id = str(result.inserted_id)
    log.info(f"[ForwardQueue] Created forwarder {forwarder_id}: {origin_chat_name} -> {target_chat_name}")
    return forwarder_id


async def update_forwarder_status(forwarder_id: str, is_active: bool) -> bool:
    """Enable/disable a forwarder."""
    result = await live_forwarders_col().update_one(
        {"_id": ObjectId(forwarder_id)},
        {"$set": {"is_active": is_active}}
    )
    status = "enabled" if is_active else "disabled"
    log.info(f"[ForwardQueue] Forwarder {forwarder_id} {status}")
    return result.modified_count > 0


async def update_last_forwarded(forwarder_id: str) -> None:
    """Update last_forwarded_at timestamp."""
    await live_forwarders_col().update_one(
        {"_id": ObjectId(forwarder_id)},
        {"$set": {"last_forwarded_at": datetime.utcnow()}}
    )


async def delete_forwarder(forwarder_id: str) -> bool:
    """Delete a forwarder."""
    result = await live_forwarders_col().delete_one({"_id": ObjectId(forwarder_id)})
    if result.deleted_count > 0:
        log.info(f"[ForwardQueue] Deleted forwarder {forwarder_id}")
        return True
    return False


async def get_forwarders_by_origin(origin_chat_id: int) -> List[Dict]:
    """Get all active forwarders for a given origin chat."""
    return await live_forwarders_col().find({
        "origin_chat_id": origin_chat_id,
        "is_active": True
    }).to_list(length=100)
