#!/usr/bin/env python3
"""
ReactionBot - Multi-utility Telegram Bot
Entry point with plugin-based architecture.
Run: python3 app.py
"""
import asyncio
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.request import HTTPXRequest
from telegram.error import NetworkError

from config import BOT_TOKEN, OWNER_IDS, UPLOADER_BOT_TOKEN, USE_LOCAL_API, LOCAL_TGAPI_SERVER, UPLOAD_TIMEOUT
from util.logging import log, setup_global_exception_handlers
from util.db import init_db, close_db
from util.cronJob import start_scheduler, stop_scheduler
from util.responses import (
    START_RESPONSE, HELP_USER, HELP_OWNER,
    STARTMSG_BTN1, STARTMSG_BTN2, STARTMSG_BTN1URL, STARTMSG_BTN2URL
)
from util.pyro_bot import start_pyro_bot, stop_pyro_bot
from util import tasks


# ─────────────────────────────────────────────────────────────────────────────
# Core handlers
# ─────────────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command with deep link support."""
    # Track user for broadcast
    user = update.effective_user
    if user:
        from util.db import track_user
        await track_user(user.id, user.username, user.first_name)
    
    # Check for membership deep links
    if context.args:
        from plugins.membership import handle_join_deeplink
        if await handle_join_deeplink(update, context):
            return  # Deep link was handled
        
        # Check for batch deep links
        from plugins.batch import handle_batch_deeplink
        if await handle_batch_deeplink(update, context):
            return  # Deep link was handled
    
    # Default start message with buttons
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    keyboard = [
        [
            InlineKeyboardButton(STARTMSG_BTN1, url=STARTMSG_BTN1URL),
            InlineKeyboardButton(STARTMSG_BTN2, url=STARTMSG_BTN2URL),
        ]
    ]
    await update.message.reply_text(
        START_RESPONSE,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command - shows different content for owners vs users."""
    user_id = update.effective_user.id
    
    if user_id in OWNER_IDS:
        await update.message.reply_text(HELP_OWNER, parse_mode="HTML")
    else:
        await update.message.reply_text(HELP_USER, parse_mode="HTML")


# ─────────────────────────────────────────────────────────────────────────────
# Plugin loader
# ─────────────────────────────────────────────────────────────────────────────

def load_plugins(app: Application) -> None:
    """
    Dynamically load all plugins from the plugins/ directory.
    Each plugin must have a `register(app)` function.
    """
    plugins_dir = Path(__file__).parent / "plugins"
    if not plugins_dir.exists():
        log.warning("Plugins directory not found.")
        return

    for plugin_file in plugins_dir.glob("*.py"):
        if plugin_file.name.startswith("_"):
            continue
        module_name = f"plugins.{plugin_file.stem}"
        try:
            module = __import__(module_name, fromlist=["register"])
            if hasattr(module, "register"):
                module.register(app)
                log.info(f"Plugin loaded: {plugin_file.stem}")
            else:
                log.warning(f"Plugin {plugin_file.stem} has no register() function.")
        except Exception as e:
            log.error(f"Failed to load plugin {plugin_file.stem}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Lifecycle hooks
# ─────────────────────────────────────────────────────────────────────────────

async def post_init(app: Application) -> None:
    """Called after Application is initialized."""
    # Validate UPLOADER_BOT_TOKEN is configured (required for forwarding restricted content)
    if not UPLOADER_BOT_TOKEN:
        log.error("Please add Uploader Bot token")
        print("Please add Uploader Bot token")
        import sys
        sys.exit(1)
    
    # Start pyrogram bot for 2GB file operations
    await start_pyro_bot()
    
    await init_db()
    start_scheduler()
    
    # Initialize membership cron with bot reference
    from util.membership_cron import init_membership_cron
    init_membership_cron(app.bot)
    
    # Initialize forward client for live forwarding
    from util.forward_client import init_forward_client
    await init_forward_client()
    
    # Initialize forward cron jobs
    from util.forward_cron import init_forward_cron
    init_forward_cron()
    
    # Initialize batch queue cron for processing queued batch deliveries
    from util.batch_cron import init_batch_cron
    init_batch_cron(app.bot)
    
    # Initialize old forward client for batch forwarding
    from util.old_forward_client import init_old_forward_client
    await init_old_forward_client()
    
    log.info("Bot initialized.")
    print("Bot initialized.")  # Ensure message is printed even if logging fails


async def post_shutdown(app: Application) -> None:
    """Called when Application shuts down."""
    # Cancel all background tasks
    await tasks.cancel_all()
    
    # Stop pyrogram bot
    await stop_pyro_bot()
    
    # Stop forward client
    from util.forward_client import stop_forward_client
    await stop_forward_client()
    
    # Stop old forward client
    from util.old_forward_client import stop_old_forward_client
    await stop_old_forward_client()
    
    stop_scheduler()
    await close_db()
    log.info("Bot shutdown complete.")
    print("Bot shutdown complete.")  # Ensure message is printed even if logging fails


async def application_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log any unhandled exceptions from Telegram handlers."""
    if isinstance(context.error, NetworkError):
        log.warning(f"Telegram NetworkError: {context.error}")
        return
        
    log.error("Unhandled exception in Telegram update handler.", exc_info=context.error)
    log.debug(f"Update causing error: {update}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """Build and run the bot."""
    log.info("Starting ReactionBot...")
    
    # Clear old log file for fresh logs on every start
    log_file = Path("logs") / "bot.log"
    if log_file.exists():
        log_file.unlink()
    log_file.touch()
    
    setup_global_exception_handlers()
    log.info("Global exception handlers installed.")
    print("Starting ReactionBot...")  # Ensure message is printed even if logging fails

    # Custom request with extended timeouts for large file uploads (up to 2GB)
    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=float(UPLOAD_TIMEOUT),
        write_timeout=float(UPLOAD_TIMEOUT),
        pool_timeout=30.0,
    )

    # Build PTB Application with optional local API server support
    if USE_LOCAL_API:
        # PTB internally appends /{TOKEN}/{METHOD} to base_url
        # So base_url should be just the server + /bot prefix (no token)
        local_base_url = f"{LOCAL_TGAPI_SERVER}/bot"
        local_file_url = f"{LOCAL_TGAPI_SERVER}/file/bot"
        app = (
            Application.builder()
            .token(BOT_TOKEN)
            .base_url(local_base_url)
            .base_file_url(local_file_url)
            .request(request)
            .get_updates_request(request)
            .post_init(post_init)
            .post_shutdown(post_shutdown)
            .build()
        )
    else:
        app = (
            Application.builder()
            .token(BOT_TOKEN)
            .request(request)
            .get_updates_request(request)
            .post_init(post_init)
            .post_shutdown(post_shutdown)
            .build()
        )

    app.add_error_handler(application_error_handler)

    # Core handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))

    # Load plugins
    load_plugins(app)

    # Run with more bootstrap retries for unreliable networks
    log.info("Bot is running. Press Ctrl+C to stop.")
    print("Bot is running. Press Ctrl+C to stop.")  # Ensure message is printed even if logging fails
    try:
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            bootstrap_retries=5,
        )
    except Exception:
        log.critical("Bot polling failed unexpectedly.", exc_info=True)
        raise


if __name__ == "__main__":
    main()
