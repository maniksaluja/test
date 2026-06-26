from pyrogram import Client
from pyrogram.session import Session

from config import BOT_TOKEN, API_ID, API_HASH, PYROBOT_WORKERS
from util.logging import log

Session.MAX_CHUNK_SIZE = 4 * 1024 * 1024  # 4MB

# Pyrogram uses MTProto directly - already supports 2GB uploads natively
# Local Bot API server is only for Bot API clients (PTB), not MTProto clients
pyro_bot: Client = Client(
    "pyro_bot",
    bot_token=BOT_TOKEN,
    api_id=API_ID,
    api_hash=API_HASH,
    no_updates=True,
    in_memory=True,
    workers=PYROBOT_WORKERS,
)

async def start_pyro_bot() -> None:
    """Start the pyrogram bot client."""
    global pyro_bot
    try:
        if not pyro_bot.is_connected:
            await pyro_bot.start()
            me = await pyro_bot.get_me()
            log.info(f"[PyroBot] ✓ Started as {me.first_name} (@{me.username}) - for unzipper uploads")
    except Exception as e:
        log.error(f"[PyroBot] Failed to start: {e}")
        raise


async def stop_pyro_bot() -> None:
    """Stop the pyrogram bot client."""
    global pyro_bot
    try:
        if pyro_bot.is_connected:
            await pyro_bot.stop()
            log.info("[PyroBot] Stopped.")
    except Exception as e:
        log.error(f"[PyroBot] Error stopping: {e}")
