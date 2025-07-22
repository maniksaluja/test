from pyrogram import Client, filters
import os

BOT_TOKEN = "7930566999:AAECSZX32cRS6VqZ3SsnI6jdUPZmJvSLvBA"
API_ID = 28070245
API_HASH = "c436fc81a842d159c75e1e212b7f6e7c"

app = Client("thumb-bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

@app.on_message(filters.media & filters.private)
async def media_handler(client, message):
    try:
        # 📸 Case: If it's a photo, use highest resolution
        if message.photo:
            best_photo = message.photo[-1]  # largest size
            file_path = await client.download_media(best_photo)
            await message.reply_photo(photo=file_path, caption="🖼️ Ye photo ka original version hai (best size)")
            os.remove(file_path)
            return

        # 🎞️ Other media types
        media = message.video or message.document or message.animation or message.audio or message.voice or message.sticker

        if not media:
            await message.reply("❌ Yeh media supported nahi hai.")
            return

        # 🔍 Thumbnail
        thumb = media.thumbs[0] if hasattr(media, 'thumbs') and media.thumbs else media.thumb

        if not thumb:
            await message.reply("❌ Is media ka thumbnail nahi mila.")
            return

        file_path = await client.download_media(thumb)
        await message.reply_photo(photo=file_path, caption="📎 Thumbnail (Telegram compressed)")
        os.remove(file_path)

    except Exception as e:
        await message.reply(f"⚠️ Error: {e}")

app.run()
