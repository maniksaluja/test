import asyncio
from util.logging import log
from util.cronJob import add_job, every_minutes


def init_forward_cron() -> None:
    """Initialize forward-related cron jobs."""
    add_job(
        _retry_failed_items,
        every_minutes(5),
        job_id="forward_retry_failed",
    )
    
    add_job(
        _cleanup_completed_items,
        every_minutes(60),
        job_id="forward_cleanup_completed",
    )
    
    asyncio.create_task(_process_pending_on_startup())
    
    log.info("[ForwardCron] Cron jobs initialized.")


async def _retry_failed_items() -> None:
    """Retry failed queue items that haven't exceeded max retries."""
    try:
        from util.forward_queue import get_failed_items_for_retry, reset_for_retry
        
        failed_items = await get_failed_items_for_retry()
        if not failed_items:
            return
        
        log.debug(f"[ForwardCron] Retrying {len(failed_items)} failed items")
        
        for item in failed_items:
            queue_id = str(item["_id"])
            await reset_for_retry(queue_id)
        
        log.info(f"[ForwardCron] Reset {len(failed_items)} items for retry")
        
    except Exception as e:
        log.error(f"[ForwardCron] Error retrying failed items: {e}")


async def _cleanup_completed_items() -> None:
    """Remove completed queue items older than 24 hours."""
    try:
        from util.forward_queue import cleanup_old_completed
        
        deleted_count = await cleanup_old_completed(hours=24)
        if deleted_count > 0:
            log.info(f"[ForwardCron] Cleaned up {deleted_count} old queue items")
            
    except Exception as e:
        log.error(f"[ForwardCron] Error cleaning up completed items: {e}")


async def _process_pending_on_startup() -> None:
    """Process any pending items from previous session."""
    try:
        await asyncio.sleep(5)
        
        from util.forward_queue import get_pending_items, mark_processing, mark_failed
        from util.forward_client import is_forward_client_ready
        
        if not is_forward_client_ready():
            log.debug("[ForwardCron] Forward client not ready, skipping pending items")
            return
        
        pending_items = await get_pending_items(limit=100)
        if not pending_items:
            return
        
        log.info(f"[ForwardCron] Found {len(pending_items)} pending items from previous session")
        

        for item in pending_items:
            queue_id = str(item["_id"])
            await mark_failed(queue_id, "Bot restarted - will retry")
        
        log.info(f"[ForwardCron] Marked {len(pending_items)} items for retry")
        
    except Exception as e:
        log.error(f"[ForwardCron] Error processing pending items: {e}")
