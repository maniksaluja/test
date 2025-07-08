import asyncio
import psutil
import platform
import shutil
from datetime import datetime
from pyrogram import Client
from pyrogram.errors import RPCError
import aiohttp
import logging

# ========== CONFIG ==========
API_ID_1 = 28070245
API_HASH_1 = "c436fc81a842d159c75e1e212b7f6e7c"
API_ID_2 = 20886865
API_HASH_2 = "754d23c04f9244762390c095d5d8fe2b"
BOT_TOKEN = "7930566999:AAECSZX32cRS6VqZ3SsnI6jdUPZmJvSLvBA"
CHANNEL_ID = -1002673893183

logging.basicConfig(level=logging.INFO)

# ========== SYSTEM STATS ==========
def get_system_status():
    ram = psutil.virtual_memory().percent
    cpu = psutil.cpu_percent(interval=1)
    disk = psutil.disk_usage('/').percent
    load = os.getloadavg()
    return ram, cpu, disk, load

# ========== TELEGRAM API TEST ==========
async def test_api_connection(api_id, api_hash, session_name):
    try:
        async with Client(session_name, api_id=api_id, api_hash=api_hash) as app:
            me = await app.get_me()
            return f"✅ Working ({me.first_name})"
    except RPCError as e:
        return f"❌ RPCError: {str(e)}"
    except Exception as e:
        return f"❌ Failed: {str(e)}"

# ========== BOT MESSAGE SENDER ==========
async def send_report(bot: Client, text: str):
    try:
        await bot.send_message(CHANNEL_ID, text)
    except Exception as e:
        logging.error(f"Failed to send message: {e}")

# ========== MAIN LOOP ==========
async def monitor():
    bot = Client("monitor_bot", bot_token=BOT_TOKEN, api_id=API_ID_1, api_hash=API_HASH_1)
    await bot.start()

    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # System Stats
        ram, cpu, disk, load = get_system_status()

        # API Tests
        api1_status = await test_api_connection(API_ID_1, API_HASH_1, "api1_session")
        api2_status = await test_api_connection(API_ID_2, API_HASH_2, "api2_session")

        # Build message
        text = f"\ud83d\udda5\ufe0f VPS Status Report ({now})\n\n"
        text += f"\U0001f9e0 RAM: {ram}%\n"
        text += f"\ud83d\udd25 CPU: {cpu}%\n"
        text += f"\ud83d\udcbd Disk: {disk}%\n"
        text += f"\ud83d\udcca Load: {load[0]} / {load[1]} / {load[2]}\n\n"
        text += f"\ud83d\udce1 API 1 ({API_ID_1}): {api1_status}\n"
        text += f"\ud83d\udce1 API 2 ({API_ID_2}): {api2_status}"

        await send_report(bot, text)
        await asyncio.sleep(30)

if __name__ == "__main__":
    import os
    asyncio.run(monitor())
