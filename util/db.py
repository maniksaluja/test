"""
MongoDB async database client using Motor.
Provides centralized access to all collections.
"""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from config import MONGODB_URL
from util.logging import log

# Global client and database references
_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def init_db(db_name: str = "reactionbot") -> AsyncIOMotorDatabase:
    """
    Initialize the MongoDB connection.
    Call once at startup.
    """
    global _client, _db
    if _client is None:
        log.info("Connecting to MongoDB...")
        _client = AsyncIOMotorClient(MONGODB_URL)
        _db = _client[db_name]
        # Ping to verify connection
        await _client.admin.command("ping")
        log.info("MongoDB connected successfully.")
        await _create_indexes()
    return _db


async def _create_indexes() -> None:
    """Create necessary indexes for collections."""
    if _db is None:
        return
    # Users
    await _db.users.create_index("user_id", unique=True)
    # Managed Groups
    await _db.managed_groups.create_index("group_id", unique=True)
    await _db.managed_groups.create_index("access_code", unique=True)
    # Memberships
    await _db.memberships.create_index([("user_id", 1), ("group_id", 1)], unique=True)
    await _db.memberships.create_index("expires_at")
    await _db.memberships.create_index("status")
    # Membership requests
    await _db.membership_requests.create_index([("user_id", 1), ("group_id", 1)])
    await _db.membership_requests.create_index("status")
    # Unzip jobs
    await _db.unzip_jobs.create_index("status")
    await _db.unzip_jobs.create_index("created_at")
    # Session strings
    await _db.session_strings.create_index("session_phone", unique=True)
    # Live forwarders
    await _db.live_forwarders.create_index("origin_chat_id")
    await _db.live_forwarders.create_index("is_active")
    await _db.live_forwarders.create_index([("origin_chat_id", 1), ("target_chat_id", 1)], unique=True)
    # Forward queue
    await _db.forward_queue.create_index("status")
    await _db.forward_queue.create_index("created_at")
    await _db.forward_queue.create_index([("status", 1), ("created_at", 1)])
    await _db.forward_queue.create_index("forwarder_id")
    # Old forward jobs
    await _db.old_forward_jobs.create_index("owner_id")
    await _db.old_forward_jobs.create_index("status")
    await _db.old_forward_jobs.create_index("created_at")
    # Batches
    await _db.batches.create_index("batch_id", unique=True)
    await _db.batches.create_index("owner_id")
    await _db.batches.create_index("is_active")
    # Batch requests
    await _db.batch_requests.create_index("batch_id")
    await _db.batch_requests.create_index("user_id")
    await _db.batch_requests.create_index([("batch_id", 1), ("user_id", 1), ("status", 1)])
    await _db.batch_requests.create_index([("user_id", 1), ("status", 1)])  # For queue queries
    await _db.batch_requests.create_index("status")  # For cron queries
    # Broadcasts
    await _db.broadcasts.create_index("owner_id")
    await _db.broadcasts.create_index("status")
    await _db.broadcasts.create_index("created_at")
    # Users - for broadcast queries
    await _db.users.create_index("can_broadcast")
    log.debug("Database indexes created.")


async def close_db() -> None:
    """Close the MongoDB connection gracefully."""
    global _client, _db
    if _client:
        log.info("Closing MongoDB connection...")
        _client.close()
        _client = None
        _db = None


def get_db() -> AsyncIOMotorDatabase:
    """
    Get the database instance.
    Raises RuntimeError if not initialized.
    """
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db


# ─────────────────────────────────────────────────────────────────────────────
# Collection helpers
# ─────────────────────────────────────────────────────────────────────────────

def users_col():
    return get_db().users


def managed_groups_col():
    return get_db().managed_groups


def memberships_col():
    return get_db().memberships


def membership_requests_col():
    return get_db().membership_requests


def unzip_jobs_col():
    return get_db().unzip_jobs


def session_strings_col():
    return get_db().session_strings


def old_forward_jobs_col():
    return get_db().old_forward_jobs


def batches_col():
    return get_db().batches


def batch_requests_col():
    return get_db().batch_requests


def broadcasts_col():
    return get_db().broadcasts


# ─────────────────────────────────────────────────────────────────────────────
# User tracking helper
# ─────────────────────────────────────────────────────────────────────────────

async def track_user(user_id: int, username: str | None = None, first_name: str | None = None) -> None:
    """
    Track user interaction. Creates or updates user record.
    Sets can_broadcast = True for active users.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    await users_col().update_one(
        {"user_id": user_id},
        {
            "$set": {
                "username": username,
                "first_name": first_name or "Unknown",
                "last_seen": now,
                "can_broadcast": True,
            },
            "$setOnInsert": {
                "first_seen": now,
            }
        },
        upsert=True
    )
