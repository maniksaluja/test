from pyrogram import Client, filters
import os

# 🔐 Bot credentials
BOT_TOKEN = "7930566999:AAECSZX32cRS6VqZ3SsnI6jdUPZmJvSLvBA"
API_ID = 28070245
API_HASH = "c436fc81a842d159c75e1e212b7f6e7c"

# 🟢 Bot session
app = Client("thumb-bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

# 📥 Handle media message
@app.on_message(filters.media & filters.private)
async def media_handler(client, message):
    # Media types supported
    media = message.video or message.document or message.animation or message.audio or message.voice or message.sticker

    if not media:
        await message.reply("❌ Yeh media supported nahi hai.")
        return

    # 🔍 Thumbnail check
    if not media.thumbs and not media.thumb:
        await message.reply("❌ Is media ka thumbnail nahi mila.")
        return

    # Get thumbnail object
    thumb = media.thumbs[0] if hasattr(media, 'thumbs') and media.thumbs else media.thumb

    try:
        file_path = await client.download_media(thumb)
        await message.reply_photo(photo=file_path, caption="📸 Thumbnail:")
        os.remove(file_path)  # 🧹 Cleanup
    except Exception as e:
        await message.reply(f"⚠️ Error: {e}")

# ▶️ Start the bot
app.run()
