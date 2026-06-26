"""
Stats plugin - Show bot and server statistics.
Owner-only feature.
"""
import psutil
from datetime import datetime, timezone, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import OWNER_IDS
from util.logging import log
from util.db import (
    users_col,
    managed_groups_col,
    memberships_col,
    batches_col,
    batch_requests_col,
    unzip_jobs_col,
    get_db,
)
from util.owner import owner_only
from util.responses import STATS_TEMPLATE


def _format_size(size_bytes: int) -> str:
    """Format bytes to human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


async def _get_user_stats() -> dict:
    """Get user statistics."""
    total_users = await users_col().count_documents({})
    broadcastable = await users_col().count_documents({"can_broadcast": {"$ne": False}})
    return {
        "total_users": total_users,
        "broadcastable_users": broadcastable,
    }


async def _get_membership_stats() -> dict:
    """Get membership statistics."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    total_groups = await managed_groups_col().count_documents({})
    active_memberships = await memberships_col().count_documents({"status": "active"})
    
    # Members approved today
    members_today = await memberships_col().count_documents({
        "approved_at": {"$gte": today_start}
    })
    
    # Members approved this month
    members_month = await memberships_col().count_documents({
        "approved_at": {"$gte": month_start}
    })
    
    return {
        "total_groups": total_groups,
        "active_memberships": active_memberships,
        "members_today": members_today,
        "members_month": members_month,
    }


async def _get_batch_stats() -> dict:
    """Get batch statistics."""
    active_batches = await batches_col().count_documents({"is_active": True})
    total_batches = await batches_col().count_documents({})
    
    # Approved batch requests
    approved_requests = await batch_requests_col().count_documents({
        "status": {"$in": ["approved", "approved_restricted"]}
    })
    
    # Total media in all batches (sum of messages array lengths)
    pipeline = [
        {"$project": {"msg_count": {"$size": {"$ifNull": ["$messages", []]}}}},
        {"$group": {"_id": None, "total": {"$sum": "$msg_count"}}}
    ]
    result = await batches_col().aggregate(pipeline).to_list(1)
    total_media = result[0]["total"] if result else 0
    
    return {
        "active_batches": active_batches,
        "total_batches": total_batches,
        "approved_requests": approved_requests,
        "total_media": total_media,
    }


async def _get_forwarder_stats() -> dict:
    """Get forwarder statistics."""
    db = get_db()
    
    # Live forwarders
    live_forwarders = await db.live_forwarders.count_documents({"is_active": True})
    
    # Old forward jobs
    old_forward_jobs = await db.old_forward_jobs.count_documents({})
    
    return {
        "live_forwarders": live_forwarders,
        "old_forward_jobs": old_forward_jobs,
    }


async def _get_unzipper_stats() -> dict:
    """Get unzipper statistics."""
    total_unzipped = await unzip_jobs_col().count_documents({})
    completed_unzipped = await unzip_jobs_col().count_documents({"status": "completed"})
    failed_unzipped = await unzip_jobs_col().count_documents({"status": "failed"})
    
    # Total files extracted (sum of files_sent)
    pipeline = [
        {"$match": {"status": "completed"}},
        {"$group": {
            "_id": None,
            "total_files": {"$sum": {"$ifNull": ["$files_sent", 0]}},
            "total_size": {"$sum": {"$ifNull": ["$extracted_size", 0]}}
        }}
    ]
    result = await unzip_jobs_col().aggregate(pipeline).to_list(1)
    
    files_extracted = result[0]["total_files"] if result else 0
    data_processed = result[0]["total_size"] if result else 0
    
    return {
        "total_unzipped": total_unzipped,
        "completed_unzipped": completed_unzipped,
        "failed_unzipped": failed_unzipped,
        "files_extracted": files_extracted,
        "data_processed": _format_size(data_processed),
    }


def _get_server_stats() -> dict:
    """Get server statistics using psutil."""
    # CPU
    cpu_count = psutil.cpu_count()
    cpu_percent = psutil.cpu_percent(interval=0.9)
    
    # RAM
    mem = psutil.virtual_memory()
    ram_used = _format_size(mem.used)
    ram_total = _format_size(mem.total)
    ram_percent = mem.percent
    
    # Disk
    disk = psutil.disk_usage("/")
    disk_used = _format_size(disk.used)
    disk_total = _format_size(disk.total)
    disk_free = _format_size(disk.free)
    
    return {
        "cpu_count": cpu_count,
        "cpu_percent": f"{cpu_percent:.1f}",
        "ram_used": ram_used,
        "ram_total": ram_total,
        "ram_percent": f"{ram_percent:.1f}",
        "disk_used": disk_used,
        "disk_total": disk_total,
        "disk_free": disk_free,
    }


@owner_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats and /users commands."""
    msg = await update.message.reply_text("📊 Gathering statistics...", parse_mode="HTML")
    
    try:
        # Gather all stats
        user_stats = await _get_user_stats()
        membership_stats = await _get_membership_stats()
        batch_stats = await _get_batch_stats()
        forwarder_stats = await _get_forwarder_stats()
        unzipper_stats = await _get_unzipper_stats()
        server_stats = _get_server_stats()
        
        # Merge all stats
        all_stats = {
            **user_stats,
            **membership_stats,
            **batch_stats,
            **forwarder_stats,
            **unzipper_stats,
            **server_stats,
        }
        
        # Format and send
        response = STATS_TEMPLATE.format(**all_stats)
        await msg.edit_text(response, parse_mode="HTML")
        
    except Exception as e:
        log.error(f"[Stats] Error gathering stats: {e}")
        await msg.edit_text(f"❌ Error gathering statistics: {e}", parse_mode="HTML")


def register(app: Application) -> None:
    """Register stats handlers."""
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("users", stats_command))  # Alias
