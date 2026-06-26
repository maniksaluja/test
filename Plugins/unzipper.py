"""
Unzipper Plugin - Extract archive files sent by owner.
Supports: ZIP, RAR, 7z, tar.gz archives, Telegram files, URLs, password-protected.
Converts videos to MP4 with ffmpeg.
"""
import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from util.logging import log
from util.owner import owner_only
from util.db import unzip_jobs_col
from util.pyro_bot import pyro_bot
from util.shared_helpers import generate_video_thumb, cleanup_files
from util.responses import (
    UNZIP_CHECKING,
    UNZIP_DOWNLOADING,
    UNZIP_EXTRACTING,
    UNZIP_PASSWORD_REQUIRED,
    UNZIP_CANCELLED,
    UNZIP_SENDING,
    UNZIP_FAILED,
    UNZIP_QUEUED,
    UNZIP_PROCESSING,
    UNZIP_SIZE_ERROR,
    UNZIP_INVALID,
)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
DATA_DIR = Path("data")
ZIPS_DIR = DATA_DIR / "zips"
UNZIPPED_DIR = DATA_DIR / "unzipped"
VIDEO_EXTENSIONS = {".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"}
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz"}
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB limit
SEND_DELAY = 2  # Seconds between file sends to avoid flood control

# Conversation states
WAITING_PASSWORD = 1

# Ensure directories exist
ZIPS_DIR.mkdir(parents=True, exist_ok=True)
UNZIPPED_DIR.mkdir(parents=True, exist_ok=True)

# Queue for processing
_queue: asyncio.Queue = asyncio.Queue()
_processing = False
_queue_task: asyncio.Task | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def format_size(size: int) -> str:
    """Format bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def format_speed(bytes_per_sec: float) -> str:
    """Format download speed to human-readable string."""
    if bytes_per_sec < 1024:
        return f"{bytes_per_sec:.0f} B/s"
    elif bytes_per_sec < 1024 * 1024:
        return f"{bytes_per_sec / 1024:.1f} KB/s"
    else:
        return f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"


def format_eta(seconds: float) -> str:
    """Format ETA to human-readable string."""
    if seconds < 0 or seconds > 86400:  # More than a day or negative
        return "∞"
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m"


def create_progress_bar(current: int, total: int, width: int = 10) -> str:
    """Create a visual progress bar."""
    if total <= 0:
        return "[" + "□" * width + "]"
    
    percent = min(current / total, 1.0)
    filled = int(width * percent)
    empty = width - filled
    
    bar = "■" * filled + "□" * empty
    return f"[{bar}]"


def get_free_space(path: Path) -> int:
    """Get free disk space in bytes."""
    stat = os.statvfs(path)
    return stat.f_bavail * stat.f_frsize


def is_valid_url(text: str) -> bool:
    """Check if text is a valid URL."""
    try:
        result = urlparse(text)
        return result.scheme in ("http", "https") and bool(result.netloc)
    except Exception:
        return False


async def get_url_size(url: str) -> Optional[int]:
    """Get file size from URL headers."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(url, allow_redirects=True) as resp:
                if resp.status == 200:
                    return int(resp.headers.get("Content-Length", 0))
    except Exception as e:
        log.error(f"Failed to get URL size: {e}")
    return None


async def download_url(url: str, dest: Path, progress_callback=None) -> bool:
    """Download file from URL with optional progress callback."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return False
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with open(dest, "wb") as f:
                    async for chunk in resp.content.iter_chunked(1024 * 64):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total:
                            await progress_callback(downloaded, total)
                return True
    except Exception as e:
        log.error(f"Download failed: {e}")
        return False


def get_archive_type(file_path: Path) -> Optional[str]:
    """Detect archive type by magic bytes."""
    try:
        with open(file_path, "rb") as f:
            header = f.read(10)
        
        # ZIP: PK\x03\x04 or PK\x05\x06 (empty) or PK\x07\x08 (spanned)
        if header[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
            return "zip"
        # RAR: Rar!
        if header[:4] == b"Rar!":
            return "rar"
        # 7z: 7z\xbc\xaf\x27\x1c
        if header[:6] == b"7z\xbc\xaf\x27\x1c":
            return "7z"
        # GZIP: \x1f\x8b
        if header[:2] == b"\x1f\x8b":
            return "gz"
        # TAR: "ustar" at offset 257 (need more bytes)
        with open(file_path, "rb") as f:
            f.seek(257)
            if f.read(5) == b"ustar":
                return "tar"
        
        return None
    except Exception:
        return None


def is_password_protected(archive_path: Path) -> bool:
    """Check if archive is password protected (ZIP only for now)."""
    archive_type = get_archive_type(archive_path)
    
    if archive_type == "zip":
        try:
            with zipfile.ZipFile(archive_path) as zf:
                for info in zf.infolist():
                    if info.flag_bits & 0x1:
                        return True
                if zf.namelist():
                    zf.read(zf.namelist()[0])
            return False
        except RuntimeError:
            return True
        except Exception:
            return False
    
    # For RAR/7z, we'll try extraction and handle password prompt
    return False


def validate_password(archive_path: Path, password: str) -> bool:
    """Validate password for a password-protected archive."""
    archive_type = get_archive_type(archive_path)
    
    if archive_type == "zip":
        try:
            with zipfile.ZipFile(archive_path) as zf:
                # Try to read the first file with the password
                if zf.namelist():
                    zf.read(zf.namelist()[0], pwd=password.encode())
                    return True
            return True
        except RuntimeError as e:
            # Bad password error
            if "password" in str(e).lower() or "bad" in str(e).lower():
                return False
            return False
        except Exception:
            return False
    
    # For RAR/7z, use 7z to test
    try:
        cmd = ["7z", "t", str(archive_path), f"-p{password}"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.returncode == 0
    except Exception:
        return False


def extract_archive(archive_path: Path, dest: Path, password: Optional[str] = None) -> bool:
    """Extract archive to destination. Supports ZIP, RAR, 7z, tar.gz."""
    archive_type = get_archive_type(archive_path)
    log.info(f"[Unzip] Detected archive type: {archive_type or 'unknown'}")
    
    dest.mkdir(parents=True, exist_ok=True)
    
    # Try ZIP first (native Python) - fast for simple ZIPs
    if archive_type == "zip":
        try:
            with zipfile.ZipFile(archive_path) as zf:
                pwd = password.encode() if password else None
                zf.extractall(dest, pwd=pwd)
            log.info(f"[Unzip] ZIP extracted successfully (Python zipfile)")
            return True
        except Exception as e:
            log.warning(f"[Unzip] Python zipfile failed: {e}, trying 7z...")
    
    # Try 7z command (handles RAR, 7z, corrupted ZIPs, and many others)
    # Use -aoa to overwrite and continue on errors for partial extraction
    try:
        cmd = ["7z", "x", str(archive_path), f"-o{dest}", "-y", "-aoa"]
        if password:
            cmd.append(f"-p{password}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        # Check if any files were extracted (even with errors)
        extracted_files = list(dest.rglob("*"))
        extracted_files = [f for f in extracted_files if f.is_file()]
        
        if result.returncode == 0:
            log.info(f"[Unzip] 7z extracted successfully ({len(extracted_files)} files)")
            return True
        elif extracted_files:
            # Partial extraction - some files were recovered
            log.warning(f"[Unzip] 7z partial extraction: {len(extracted_files)} files recovered (archive may be corrupted)")
            return True
        else:
            log.warning(f"[Unzip] 7z extraction failed: {result.stderr[:200]}")
    except FileNotFoundError:
        log.warning("[Unzip] 7z not installed, trying other methods...")
    except Exception as e:
        log.warning(f"[Unzip] 7z command error: {e}")
    
    # Try unrar for RAR files
    if archive_type == "rar":
        try:
            cmd = ["unrar", "x", "-y", str(archive_path), str(dest) + "/"]
            if password:
                cmd.insert(2, f"-p{password}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode == 0:
                log.info(f"[Unzip] unrar extracted successfully")
                return True
            else:
                log.error(f"[Unzip] unrar failed: {result.stderr}")
        except FileNotFoundError:
            log.error("[Unzip] unrar not installed")
        except Exception as e:
            log.error(f"[Unzip] unrar error: {e}")
    
    # Try tar for gzipped tarballs
    if archive_type in ("gz", "tar"):
        try:
            cmd = ["tar", "-xzf" if archive_type == "gz" else "-xf", str(archive_path), "-C", str(dest)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode == 0:
                log.info(f"[Unzip] tar extracted successfully")
                return True
            else:
                log.error(f"[Unzip] tar failed: {result.stderr}")
        except Exception as e:
            log.error(f"[Unzip] tar error: {e}")
    
    # Final check - maybe some files were extracted despite errors
    extracted_files = list(dest.rglob("*"))
    extracted_files = [f for f in extracted_files if f.is_file()]
    if extracted_files:
        log.warning(f"[Unzip] Partial extraction: {len(extracted_files)} files recovered")
        return True
    
    log.error(f"[Unzip] Failed to extract archive: unsupported or corrupted")
    return False


def convert_video_to_mp4(video_path: Path) -> Optional[Path]:
    """Convert video to MP4 using ffmpeg. Uses stream copy (fast) first, falls back to re-encode."""
    output_path = video_path.with_suffix(".mp4")
    if video_path.suffix.lower() == ".mp4":
        return video_path
    
    try:
        cmd = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-c:v", "copy",  
            "-c:a", "copy", 
            str(output_path)
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=500)
        if result.returncode == 0 and output_path.exists():
            video_path.unlink()  # Remove original
            log.info(f"[Unzip] Video remuxed (stream copy): {output_path.name}")
            return output_path
    except Exception as e:
        log.debug(f"[Unzip] Stream copy failed, trying re-encode: {e}")
    
    # Fallback: Re-encode if stream copy failed (incompatible codec)
    try:
        if output_path.exists():
            output_path.unlink()  # Remove failed attempt
        cmd = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path)
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        video_path.unlink()  # Remove original
        log.info(f"[Unzip] Video re-encoded: {output_path.name}")
        return output_path
    except Exception as e:
        log.error(f"Video conversion failed: {e}")
        return video_path


def clean_filename(filename: str) -> str:
    """Clean filename for display (remove extension)."""
    return Path(filename).stem


def find_all_files(base_path: Path, max_depth: int = 10) -> list[Path]:
    """
    Recursively find all files up to max_depth levels.
    Skips hidden files/folders and returns only actual files.
    """
    files = []
    
    def scan_dir(current_path: Path, depth: int):
        if depth > max_depth:
            return
        try:
            for item in current_path.iterdir():
                # Skip hidden files/folders
                if item.name.startswith('.'):
                    continue
                if item.is_file():
                    files.append(item)
                elif item.is_dir():
                    scan_dir(item, depth + 1)
        except PermissionError:
            log.warning(f"[Unzip] Permission denied: {current_path}")
        except Exception as e:
            log.warning(f"[Unzip] Error scanning {current_path}: {e}")
    
    scan_dir(base_path, 0)
    return files


# ─────────────────────────────────────────────────────────────────────────────
# Job management
# ─────────────────────────────────────────────────────────────────────────────

async def add_job(
    user_id: int,
    chat_id: int,
    message_id: int,
    source_type: str,
    source: str,
    file_size: int = 0,
    original_msg_id: int = None,
    file_name: str = None,
) -> str:
    """Add a new unzip job to the database and queue."""
    job_id = f"{user_id}_{datetime.now().timestamp()}"
    job = {
        "job_id": job_id,
        "user_id": user_id,
        "chat_id": chat_id,
        "message_id": message_id,
        "original_msg_id": original_msg_id or message_id,
        "source_type": source_type,
        "source": source,
        "file_size": file_size,
        "file_name": file_name or "archive.zip",
        "status": "queued",
        "created_at": datetime.utcnow(),
        "password": None,
        "zip_path": None,  # Store path to downloaded zip to avoid re-download
        "password_attempts": 0,  # Track password attempts
    }
    await unzip_jobs_col().insert_one(job)
    await _queue.put(job_id)
    return job_id


async def update_job_status(job_id: str, status: str, **kwargs) -> None:
    """Update job status in database."""
    update = {"status": status, **kwargs}
    await unzip_jobs_col().update_one({"job_id": job_id}, {"$set": update})


async def get_job(job_id: str) -> Optional[dict]:
    """Get job from database."""
    return await unzip_jobs_col().find_one({"job_id": job_id})


# ─────────────────────────────────────────────────────────────────────────────
# Queue processor
# ─────────────────────────────────────────────────────────────────────────────

async def process_queue(app: Application) -> None:
    """Background worker to process unzip queue."""
    global _processing
    try:
        while True:
            job_id = await _queue.get()
            log.info(f"[Unzip] Queue picked job: {job_id}")
            log.info(f"[Unzip] Queue size remaining: {_queue.qsize()}")
            _processing = True
            try:
                await process_job(app, job_id)
            except Exception as e:
                log.error(f"Job {job_id} failed: {e}")
                await update_job_status(job_id, "failed", error=str(e))
            finally:
                _processing = False
                _queue.task_done()
                log.info(f"[Unzip] Job {job_id} finished, ready for next")
    except asyncio.CancelledError:
        log.debug("Unzipper queue processor cancelled.")
        raise


async def process_job(app: Application, job_id: str) -> None:
    """Process a single unzip job."""
    job = await get_job(job_id)
    if not job or job["status"] == "cancelled":
        log.info(f"[Unzip] Job {job_id} skipped (cancelled or not found)")
        return

    bot = app.bot
    chat_id = job["chat_id"]
    reply_msg_id = job.get("original_msg_id") or job["message_id"]
    
    log.info(f"[Unzip] Processing job {job_id} | msg_id: {reply_msg_id}")

    # Status message
    status_msg = await bot.send_message(chat_id, UNZIP_CHECKING, reply_to_message_id=reply_msg_id, parse_mode="HTML")

    # Check if we already have a downloaded zip (for password retry)
    timestamp = int(datetime.now().timestamp())
    if job.get("zip_path") and Path(job["zip_path"]).exists():
        zip_path = Path(job["zip_path"])
        log.info(f"[Unzip] Using existing downloaded file: {zip_path}")
    else:
        zip_filename = f"archive_{job_id}_{timestamp}.zip"
        zip_path = ZIPS_DIR / zip_filename
    extract_path = UNZIPPED_DIR / f"extract_{job_id}_{timestamp}"

    try:
        # Skip download if file already exists (password retry case)
        already_downloaded = job.get("zip_path") and Path(job["zip_path"]).exists()
        
        if already_downloaded:
            log.info(f"[Unzip] Skipping download, file already exists: {zip_path}")
        else:
            # Check disk space
            free_space = get_free_space(DATA_DIR)
            file_size = job.get("file_size", 0)
            log.info(f"[Unzip] Checking disk: file={format_size(file_size)}, free={format_size(free_space)}")
            
            if job["source_type"] == "url":
                log.info(f"[Unzip] Downloading from URL: {job['source'][:50]}...")
                await status_msg.edit_text(UNZIP_DOWNLOADING.format(size=format_size(job["file_size"])), parse_mode="HTML")
                success = await download_url(job["source"], zip_path)
                if not success:
                    log.error(f"[Unzip] URL download failed for job {job_id}")
                    await status_msg.edit_text(UNZIP_FAILED.format(error="Download failed"), parse_mode="HTML")
                    return
                log.info(f"[Unzip] URL download completed: {zip_path}")
            else:
                # Telegram file - use pyro_bot for 2GB download support
                log.info(f"[Unzip] Downloading Telegram file via PyroBot: {job['source']}")
                
                # Get file name and size for display
                file_name = job.get("file_name") or "archive.zip"
                expected_size = job.get("file_size") or 0
                
                # Progress tracking state
                progress_state = {
                    "last_update": 0,
                    "start_time": asyncio.get_event_loop().time(),
                    "last_bytes": 0,
                    "last_time": asyncio.get_event_loop().time(),
                }
                
                async def progress_callback(current: int, total: int):
                    """Update progress message every 2 seconds."""
                    now = asyncio.get_event_loop().time()
                    
                    # Only update every 2 seconds to avoid rate limits
                    if now - progress_state["last_update"] < 2:
                        return
                    progress_state["last_update"] = now
                    
                    # Use expected_size from job if total is 0
                    actual_total = total if total > 0 else expected_size
                    
                    # Calculate speed based on time since last update
                    elapsed = now - progress_state["last_time"]
                    if elapsed > 0:
                        bytes_delta = current - progress_state["last_bytes"]
                        speed = bytes_delta / elapsed
                    else:
                        speed = 0
                    
                    progress_state["last_bytes"] = current
                    progress_state["last_time"] = now
                    
                    # Calculate percentage and ETA
                    if actual_total > 0:
                        percent = (current / actual_total) * 100
                        if speed > 0:
                            remaining = actual_total - current
                            eta = remaining / speed
                        else:
                            eta = -1
                    else:
                        percent = 0
                        eta = -1
                    
                    # Build progress message
                    progress_bar = create_progress_bar(current, actual_total, width=10)
                    progress_text = (
                        f"<b>• Status ≽ Downloading..</b>\n"
                        f"<b>• Size ≽ {format_size(current)} / {format_size(actual_total)} </b>\n"
                        f"<b>• Speed≽ {format_speed(speed)}</b>\n"
                        f"<b>• ETA ≽  {format_eta(eta)}</b>\n"
                        f"<blockquote><b> {progress_bar} {percent:.1f}% </b></blockquote>"
                    )
                    
                    try:
                        await status_msg.edit_text(progress_text, parse_mode="HTML")
                    except Exception:
                        pass  # Ignore edit errors (message not modified, etc.)
                
                await pyro_bot.download_media(
                    job["source"],
                    file_name=str(zip_path),
                    progress=progress_callback
                )
                log.info(f"[Unzip] Telegram download completed: {zip_path}")

            # Store the zip path in case we need it for password retry
            await update_job_status(job_id, "downloaded", zip_path=str(zip_path))
            log.info(f"[Unzip] Download complete, file size on disk: {format_size(zip_path.stat().st_size)}")

        # Check password
        password = job.get("password")
        password_attempts = job.get("password_attempts", 0)
        
        if is_password_protected(zip_path):
            if not password:
                # First time - ask for password
                log.info(f"[Unzip] Archive is password protected, waiting for password")
                await update_job_status(job_id, "waiting_password", zip_path=str(zip_path))
                keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data=f"unzip_cancel:{job_id}")]]
                await status_msg.edit_text(
                    UNZIP_PASSWORD_REQUIRED,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML",
                )
                # Store context for password handling
                app.bot_data[f"unzip_waiting_{chat_id}"] = job_id
                return
            else:
                # Validate password before extraction
                log.info(f"[Unzip] Validating password (attempt {password_attempts + 1}/2)")
                if not validate_password(zip_path, password):
                    password_attempts += 1
                    log.warning(f"[Unzip] Invalid password, attempt {password_attempts}/2")
                    
                    if password_attempts >= 2:
                        # Max attempts reached, cancel
                        log.error(f"[Unzip] Password failed after 2 attempts, cancelling job")
                        await status_msg.edit_text(
                            "❌ <b>Extraction cancelled.</b>\n\nPassword was incorrect after 2 attempts.",
                            parse_mode="HTML"
                        )
                        await update_job_status(job_id, "cancelled")
                        # Cleanup downloaded file
                        if zip_path.exists():
                            zip_path.unlink()
                            log.info(f"[Unzip] Deleted zip after failed password attempts: {zip_path}")
                        return
                    else:
                        # Ask for password again
                        await update_job_status(job_id, "waiting_password", password=None, password_attempts=password_attempts)
                        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data=f"unzip_cancel:{job_id}")]]
                        await status_msg.edit_text(
                            f"🔐 <b>Incorrect password!</b>\n\nYou have <b>{2 - password_attempts}</b> attempt(s) remaining.\n\nPlease send the correct password:",
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode="HTML"
                        )
                        app.bot_data[f"unzip_waiting_{chat_id}"] = job_id
                        return
                else:
                    log.info(f"[Unzip] Password validated successfully")

        # Extract
        log.info(f"[Unzip] Extracting to: {extract_path}")
        await status_msg.edit_text(UNZIP_EXTRACTING, parse_mode="HTML")
        extract_path.mkdir(parents=True, exist_ok=True)

        if not extract_archive(zip_path, extract_path, password):
            log.error(f"[Unzip] Extraction failed for job {job_id}")
            await status_msg.edit_text(UNZIP_FAILED.format(error="Extraction failed. Make sure archive is valid."), parse_mode="HTML")
            return

        await update_job_status(job_id, "extracted")
        log.info(f"[Unzip] Extraction completed successfully")

        # Find all files recursively (up to 10 levels deep)
        files = find_all_files(extract_path, max_depth=10)
        total = len(files)
        sent = 0
        videos_converted = 0
        
        # Calculate total extracted size for stats
        extracted_size = sum(f.stat().st_size for f in files if f.is_file())
        await update_job_status(job_id, "sending", extracted_size=extracted_size)
        
        log.info(f"[Unzip] Found {total} files to send ({format_size(extracted_size)})")

        # Check for videos that need conversion
        videos_to_convert = [f for f in files if f.suffix.lower() in VIDEO_EXTENSIONS]
        if videos_to_convert:
            log.info(f"[Unzip] Found {len(videos_to_convert)} videos to convert to MP4")
        else:
            log.info(f"[Unzip] No videos need conversion, skipping conversion step")

        for i, file_path in enumerate(files, 1):
            await status_msg.edit_text(UNZIP_SENDING.format(current=i, total=total), parse_mode="HTML")
            log.info(f"[Unzip] Sending file {i}/{total}: {file_path.name}")

            # Convert video if needed
            if file_path.suffix.lower() in VIDEO_EXTENSIONS:
                log.info(f"[Unzip] Converting video: {file_path.name}")
                converted = convert_video_to_mp4(file_path)
                if converted and converted != file_path:
                    file_path = converted
                    videos_converted += 1
                    log.info(f"[Unzip] Video converted: {file_path.name}")

            # Send file using pyro_bot for 2GB upload support
            caption = clean_filename(file_path.name)
            try:
                file_size = file_path.stat().st_size
                log.info(f"[Unzip] Sending {file_path.name} ({format_size(file_size)}) via PyroBot")
                
                if file_path.suffix.lower() in (".mp4", ".mov"):
                    thumb_path = generate_video_thumb(str(file_path))
                    try:
                        await pyro_bot.send_video(chat_id, str(file_path), caption=caption, thumb=thumb_path, disable_notification=True)
                    finally:
                        cleanup_files(thumb_path)
                elif file_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif"):
                    await pyro_bot.send_photo(chat_id, str(file_path), caption=caption, disable_notification=True)
                else:
                    await pyro_bot.send_document(chat_id, str(file_path), caption=caption, disable_notification=True)
                sent += 1
                log.info(f"[Unzip] Sent file {i}/{total} successfully")
                
                # Delay between sends to avoid flood control
                if i < total:
                    await asyncio.sleep(SEND_DELAY)
            except Exception as e:
                log.error(f"[Unzip] Failed to send {file_path.name}: {e}")
                # If flood control, wait and retry once
                if "flood" in str(e).lower():
                    log.info(f"[Unzip] Flood control hit, waiting 5 seconds...")
                    await asyncio.sleep(5)
                    try:
                        if file_path.suffix.lower() in (".mp4", ".mov"):
                            thumb_path = generate_video_thumb(str(file_path))
                            try:
                                await pyro_bot.send_video(chat_id, str(file_path), caption=caption, thumb=thumb_path, disable_notification=True)
                            finally:
                                cleanup_files(thumb_path)
                        elif file_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif"):
                            await pyro_bot.send_photo(chat_id, str(file_path), caption=caption, disable_notification=True)
                        else:
                            await pyro_bot.send_document(chat_id, str(file_path), caption=caption, disable_notification=True)
                        sent += 1
                        log.info(f"[Unzip] Retry successful for {file_path.name}")
                    except Exception as retry_e:
                        log.error(f"[Unzip] Retry also failed: {retry_e}")

        # Final summary - delete progress message and send fresh summary as reply to archive
        log.info(f"[Unzip] Sending completed: {sent}/{total} files sent, {videos_converted} videos converted")
        
        # Delete the progress/status message
        try:
            await status_msg.delete()
        except Exception:
            pass  # Ignore if can't delete
        
        # Send final summary as reply to original archive message
        final_msg = (
            f"<blockquote><b>Process Complete 💯</b></blockquote>\n"
            f"<b>• Total Files≽ {sent}/{total}</b>\n"
            f"<b>• Video converted≽ {videos_converted}</b>"
        )
        await bot.send_message(chat_id, final_msg, reply_to_message_id=reply_msg_id, parse_mode="HTML")
        await update_job_status(job_id, "completed", files_sent=sent, completed_at=datetime.utcnow())

    finally:
        # Cleanup - but only if job is not waiting for password
        job = await get_job(job_id)
        job_status = job.get("status", "") if job else ""
        
        if job_status == "waiting_password":
            # Don't delete the zip file if waiting for password
            log.info(f"[Unzip] Job {job_id} waiting for password, keeping zip file")
        else:
            # Cleanup files
            log.info(f"[Unzip] Cleaning up files for job {job_id}")
            if zip_path.exists():
                zip_path.unlink()
                log.info(f"[Unzip] Deleted zip: {zip_path}")
            if extract_path.exists():
                shutil.rmtree(extract_path)
                log.info(f"[Unzip] Deleted extracted folder: {extract_path}")
            log.info(f"[Unzip] Job {job_id} cleanup complete, queue will process next")


# ─────────────────────────────────────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────────────────────────────────────

@owner_only
async def unzip_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /unzip command."""
    message = update.message
    reply = message.reply_to_message
    
    log.info(f"[Unzip] /unzip command received from user {update.effective_user.id}")

    source_type = None
    source = None
    file_size = 0
    original_msg_id = None
    file_name = None

    # Check if reply to a file
    if reply and reply.document:
        doc = reply.document
        file_ext = Path(doc.file_name.lower()).suffix
        if file_ext not in ARCHIVE_EXTENSIONS:
            log.info(f"[Unzip] Invalid file type: {doc.file_name}")
            await message.reply_text(UNZIP_INVALID, parse_mode="HTML")
            return
        source_type = "telegram"
        source = doc.file_id
        file_size = doc.file_size or 0
        file_name = doc.file_name
        original_msg_id = reply.message_id  # Reply to the zip file
        log.info(f"[Unzip] Got zip file via reply: {doc.file_name} ({format_size(file_size)})")

    # Check command args for URL
    elif context.args:
        url = context.args[0]
        if is_valid_url(url):
            source_type = "url"
            source = url
            file_size = await get_url_size(url) or 0
            original_msg_id = message.message_id
            log.info(f"[Unzip] Got zip URL: {url[:50]}... ({format_size(file_size)})")
        else:
            log.info(f"[Unzip] Invalid URL provided: {url}")
            await message.reply_text(UNZIP_INVALID, parse_mode="HTML")
            return
    else:
        log.info(f"[Unzip] No zip file or URL provided")
        await message.reply_text(UNZIP_INVALID, parse_mode="HTML")
        return

    # Check disk space
    free_space = get_free_space(DATA_DIR)
    needed = file_size * 3  # Estimate: zip + extracted + buffer
    log.info(f"[Unzip] Disk check: need={format_size(needed)}, free={format_size(free_space)}")
    if needed > free_space:
        log.warning(f"[Unzip] Insufficient disk space")
        await message.reply_text(UNZIP_SIZE_ERROR, parse_mode="HTML")
        return

    # Add job
    job_id = await add_job(
        user_id=update.effective_user.id,
        chat_id=message.chat_id,
        message_id=message.message_id,
        source_type=source_type,
        source=source,
        file_size=file_size,
        original_msg_id=original_msg_id,
        file_name=file_name,
    )
    log.info(f"[Unzip] Job created: {job_id}")

    # Queue position
    queue_size = _queue.qsize()
    log.info(f"[Unzip] Queue status: size={queue_size}, processing={_processing}")
    if queue_size > 0 or _processing:
        log.info(f"[Unzip] Job queued at position {queue_size + 1}")
        await message.reply_text(UNZIP_QUEUED.format(position=queue_size + 1), parse_mode="HTML")
    else:
        log.info(f"[Unzip] Ready to process immediately")


@owner_only
async def auto_unzip_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Auto-detect and process zip files from owner."""
    message = update.message
    doc = message.document

    if not doc or not doc.file_name:
        return

    # Only handle archive files
    file_ext = Path(doc.file_name.lower()).suffix
    if file_ext not in ARCHIVE_EXTENSIONS:
        return

    log.info(f"[Unzip] Auto-detected archive: {doc.file_name} | msg_id: {message.message_id}")
    
    source_type = "telegram"
    source = doc.file_id
    file_size = doc.file_size or 0
    original_msg_id = message.message_id  # The zip file message itself
    
    log.info(f"[Unzip] File size: {format_size(file_size)}")

    # Check disk space
    free_space = get_free_space(DATA_DIR)
    needed = file_size * 3  # Estimate: zip + extracted + buffer
    log.info(f"[Unzip] Disk check: need={format_size(needed)}, free={format_size(free_space)}")
    if needed > free_space:
        log.warning(f"[Unzip] Insufficient disk space for {doc.file_name}")
        await message.reply_text(UNZIP_SIZE_ERROR, parse_mode="HTML")
        return

    # Add job
    job_id = await add_job(
        user_id=update.effective_user.id,
        chat_id=message.chat_id,
        message_id=message.message_id,
        source_type=source_type,
        source=source,
        file_size=file_size,
        original_msg_id=original_msg_id,
        file_name=doc.file_name,
    )
    log.info(f"[Unzip] Job created: {job_id}")

    # Queue position
    queue_size = _queue.qsize()
    log.info(f"[Unzip] Queue status: size={queue_size}, processing={_processing}")
    if queue_size > 0 or _processing:
        log.info(f"[Unzip] Job queued at position {queue_size + 1}")
        await message.reply_text(UNZIP_QUEUED.format(position=queue_size + 1), parse_mode="HTML")
    else:
        log.info(f"[Unzip] Ready to process immediately")
        await message.reply_text(UNZIP_PROCESSING, parse_mode="HTML")


@owner_only
async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle password input for protected archives."""
    chat_id = update.effective_chat.id
    key = f"unzip_waiting_{chat_id}"

    if key not in context.application.bot_data:
        return

    job_id = context.application.bot_data.pop(key)
    password = update.message.text.strip()
    log.info(f"[Unzip] Password received for job {job_id}, re-queuing")

    await update_job_status(job_id, "downloaded", password=password)

    # Re-queue job for processing
    await _queue.put(job_id)
    await update.message.delete()


async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle cancel button for unzip."""
    query = update.callback_query
    await query.answer()

    data = query.data.split(":")
    if len(data) < 2:
        return

    job_id = data[1]
    await update_job_status(job_id, "cancelled")

    # Clean up waiting state
    chat_id = update.effective_chat.id
    key = f"unzip_waiting_{chat_id}"
    if key in context.application.bot_data:
        del context.application.bot_data[key]

    await query.edit_message_text(UNZIP_CANCELLED, parse_mode="HTML")


# ─────────────────────────────────────────────────────────────────────────────
# Plugin registration
# ─────────────────────────────────────────────────────────────────────────────

def register(app: Application) -> None:
    """Register unzipper handlers."""
    global _queue_task
    from config import OWNER_IDS
    
    app.add_handler(CommandHandler("unzip", unzip_command))
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern=r"^unzip_cancel:"))

    # Auto-detect zip files from owner (high priority)
    app.add_handler(
        MessageHandler(
            filters.Document.ALL & filters.User(OWNER_IDS) & filters.ChatType.PRIVATE,
            auto_unzip_handler,
        ),
        group=0,
    )

    # Password handler (simple text filter for owner in private)
    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.User(OWNER_IDS) & filters.ChatType.PRIVATE & ~filters.COMMAND,
            handle_password,
        ),
        group=1,
    )

    # Start background queue processor and register for cleanup
    from util import tasks
    _queue_task = tasks.create_task(process_queue(app), name="unzipper_queue")
    log.info("Unzipper plugin registered.")
