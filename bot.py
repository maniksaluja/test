from pyrogram import Client, filters
import os
import subprocess

BOT_TOKEN = "7930566999:AAECSZX32cRS6VqZ3SsnI6jdUPZmJvSLvBA"
API_ID = 28070245
API_HASH = "c436fc81a842d159c75e1e212b7f6e7c"

app = Client("hd-thumb-bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

@app.on_message(filters.media & filters.private)
async def hd_thumb(client, message):
    try:
        # If it's a photo
        if message.photo:
            photo = message.photo[-1]  # Best resolution
            file_path = await client.download_media(photo)
            await message.reply_photo(photo=file_path, caption="🖼️ HD Photo")
            os.remove(file_path)
            return

        # If it's a video
        if message.video or message.animation:
            media = message.video or message.animation
            video_path = await client.download_media(media)
            thumb_path = "thumb.jpg"

            # Extract HD frame using ffmpeg
            subprocess.run([
                "ffmpeg", "-i", video_path, "-ss", "00:00:01.000", "-vframes", "1", "-q:v", "2", thumb_path
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            if os.path.exists(thumb_path):
                await message.reply_photo(photo=thumb_path, caption="📸 Extracted HD Frame (Thumbnail)")
                os.remove(thumb_path)

            os.remove(video_path)
            return

        await message.reply("❌ Sirf photo ya video ka HD thumbnail bhej sakta hoon.")
    except Exception as e:
        await message.reply(f"⚠️ Error: {e}")

app.run()
