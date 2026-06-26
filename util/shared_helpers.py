"""
Shared helpers used across forward_client, old_forward_client, and reaction.
Single source of truth — no duplicates.
"""
import asyncio
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from pyrogram import Client
from pyrogram.types import Message

from util.logging import log

# ─── Terabox domains ────────────────────────────────────────────────────────

_TERABOX_DOMAINS = (
    'terabox.com', 'teraboxapp.com', 'teraboxlink.com', 'terasharefile.com',
    'neoboxlinks.com', '1024terabox.com', 'terafileshare.com', 'mirrobox.com',
    '4funbox.com', 'terabox.app', 'terabox.tech', 'terabox.me', 'terabox.fun',
    'freeterabox.com', 'terabox.club', 'teraboxcdn.com',
)

_URL_PATTERN = re.compile(r'https?://\S+', re.IGNORECASE)
_USERNAME_PATTERN = re.compile(r'@\w+', re.IGNORECASE)


def _is_terabox_link(url: str) -> bool:
    url_lower = url.lower()
    return any(domain in url_lower for domain in _TERABOX_DOMAINS)


def clean_caption(text: Optional[str]) -> Optional[str]:
    """Remove non-Terabox links and @mentions. Keep Terabox links only."""
    if not text:
        return None

    def replace_url(match):
        url = match.group(0)
        return url if _is_terabox_link(url) else ''

    cleaned = _URL_PATTERN.sub(replace_url, text)
    cleaned = _USERNAME_PATTERN.sub('', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = re.sub(r' {2,}', ' ', cleaned)
    cleaned = cleaned.strip()
    return cleaned if cleaned else None


# ─── Media type detection ────────────────────────────────────────────────────

def get_message_type(msg: Message) -> str:
    """Return the media type string used by uploader_bot.upload_media."""
    if msg.photo:
        return "photo"
    elif msg.video:
        return "video"
    elif msg.audio:
        return "audio"
    elif msg.voice:
        return "voice"
    elif msg.animation:
        return "animation"
    elif msg.video_note:
        return "video_note"
    elif msg.sticker:
        return "sticker"
    return "document"


def get_file_name(msg: Message) -> str:
    """Generate a sensible local filename for a message's media."""
    if msg.document and msg.document.file_name:
        return f"{msg.id}_{msg.document.file_name}"
    elif msg.video:
        ext = 'mp4'
        mime = getattr(msg.video, 'mime_type', '') or ''
        if 'webm' in mime:
            ext = 'webm'
        elif 'matroska' in mime:
            ext = 'mkv'
        elif 'quicktime' in mime:
            ext = 'mov'
        return f"video_{msg.id}.{ext}"
    elif msg.photo:
        return f"photo_{msg.id}.jpg"
    elif msg.audio:
        ext = (msg.audio.file_name or '').rsplit('.', 1)[-1] or 'mp3'
        return f"audio_{msg.id}.{ext}"
    elif msg.voice:
        return f"voice_{msg.id}.ogg"
    elif msg.video_note:
        return f"vnote_{msg.id}.mp4"
    elif msg.animation:
        return f"anim_{msg.id}.mp4"
    return f"file_{msg.id}"


# ─── Download helpers ────────────────────────────────────────────────────────

async def download_media(msg: Message, temp_dir: Path) -> Optional[str]:
    """Download media from a Pyrogram message to temp_dir."""
    try:
        file_name = get_file_name(msg)
        media_path = str(temp_dir / file_name)
        return await msg.download(file_name=media_path)
    except Exception as e:
        log.debug(f"[Helpers] Download failed for msg {msg.id}: {e}")
        return None


async def download_thumbnail(client: Client, msg: Message, temp_dir: Path) -> Optional[str]:
    """Download the best available thumbnail for a video/document."""
    try:
        thumbs = None
        if msg.video and msg.video.thumbs:
            thumbs = msg.video.thumbs
        elif (msg.document and msg.document.thumbs
              and getattr(msg.document, 'mime_type', '').startswith('video/')):
            thumbs = msg.document.thumbs
        if not thumbs:
            return None
        largest = thumbs[-1]
        thumb_path = str(temp_dir / f"thumb_{msg.id}.jpg")
        return await client.download_media(largest.file_id, file_name=thumb_path)
    except Exception as e:
        log.debug(f"[Helpers] Thumbnail download failed for msg {msg.id}: {e}")
        return None


async def generate_thumb(media_path: str) -> Optional[str]:
    """Generate a thumbnail with ffmpeg at ~3s. Returns path or None."""
    if not os.path.exists(media_path):
        return None
    name, _ = os.path.splitext(media_path)
    thumb_path = f"{name}_thumb.jpg"
    try:
        result = subprocess.run(
            ['ffmpeg', '-ss', '3', '-i', media_path,
             '-vframes', '1', '-vf', 'scale=320:-1', '-y', thumb_path],
            capture_output=True, timeout=15,
        )
        if result.returncode == 0 and os.path.exists(thumb_path):
            return thumb_path
    except Exception as e:
        log.debug(f"[Helpers] FFmpeg thumb failed: {e}")
    return None


def generate_video_thumb(video_path: str, seek_seconds: int = 5, min_duration: float = 6.0) -> Optional[str]:
    """
    Generate a thumbnail for a local video file using ffmpeg.
    - Probes duration with ffprobe; skips if duration < min_duration or unknown.
    - Seeks to seek_seconds, grabs one frame, scales to 320px wide.
    - Returns thumb path or None (caller must clean up).
    """
    if not os.path.exists(video_path):
        return None

    # Probe duration
    try:
        probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
            capture_output=True, text=True, timeout=10,
        )
        duration = float(probe.stdout.strip()) if probe.returncode == 0 and probe.stdout.strip() else 0.0
    except Exception:
        duration = 0.0

    if duration < min_duration:
        return None

    name, _ = os.path.splitext(video_path)
    thumb_path = f"{name}_vthumb.jpg"
    # Telegram requires BOTH thumbnail dimensions <= 320px. Plain scale=320:-1
    # produces 320xN thumbs taller than 320 for portrait videos, which fail
    # the upload with MEDIA_FILE_INVALID. Scale the longest side to 320 instead.
    scale_filter = "scale='if(gt(iw,ih),320,-2)':'if(gt(iw,ih),-2,320)'"
    try:
        result = subprocess.run(
            ['ffmpeg', '-ss', str(seek_seconds), '-i', video_path,
             '-vframes', '1', '-vf', scale_filter, '-qscale:v', '5',
             '-y', thumb_path],
            capture_output=True, timeout=20,
        )
        if result.returncode == 0 and os.path.exists(thumb_path):
            return thumb_path
    except Exception as e:
        log.debug(f"[Helpers] generate_video_thumb failed for {video_path}: {e}")
    return None


# ─── Cleanup ─────────────────────────────────────────────────────────────────

def cleanup_files(*paths) -> None:
    """Delete temporary files, silently ignoring errors."""
    for path in paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
