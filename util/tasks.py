"""
Background task manager.
Tracks and cleans up background tasks on shutdown.
"""
import asyncio
from typing import Optional

from util.logging import log

# Store background tasks for cleanup
_tasks: list[asyncio.Task] = []


def add_task(task: asyncio.Task) -> None:
    """Register a background task for cleanup on shutdown."""
    _tasks.append(task)
    log.debug(f"Background task registered: {task.get_name()}")


def create_task(coro, name: Optional[str] = None) -> asyncio.Task:
    """Create and register a background task."""
    task = asyncio.get_event_loop().create_task(coro, name=name)
    add_task(task)
    return task


async def cancel_all() -> None:
    """Cancel all registered background tasks."""
    for task in _tasks:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.error(f"Error cancelling task {task.get_name()}: {e}")
    _tasks.clear()
    log.debug("All background tasks cancelled.")
