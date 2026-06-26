"""
OTP Reader Plugin (owner-only).

/otp [session_string]
  - Detects whether the string is a Telethon (starts with "1") or Pyrogram session.
  - Connects with the proper library and shows account details (name, username, phone).
  - Provides a "Get OTP" button that reads the latest Telegram login code from the
    service chat (777000) that arrived AFTER the command was started.
  - "Get another OTP" fetches a newer code; "Done" stops the client; "Cancel" aborts.
  - The userbot client is kept connected for 10 minutes, then auto-stopped.
"""
import re
import asyncio
from datetime import datetime, timezone

from pyrogram import Client as PyroClient
from telethon import TelegramClient
from telethon.sessions import StringSession

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from config import API_ID, API_HASH
from util.logging import log
from util.owner import owner_only, is_owner
from util import tasks

# Telegram's official service-notifications account that delivers login codes.
TELEGRAM_SERVICE_CHAT = 777000
# How long to keep the userbot client connected before auto-stopping.
SESSION_TTL_SECONDS = 600  # 10 minutes

# Active OTP sessions keyed by chat_id -> state dict.
OTP_SESSIONS: dict[int, dict] = {}

_LOGIN_CODE_RE = re.compile(r"(?:login\s*code|code)\D{0,12}(\d{4,7})", re.IGNORECASE)
_FALLBACK_CODE_RE = re.compile(r"\b(\d{5,6})\b")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ts(dt: datetime) -> float:
    """Return a UTC timestamp for a (possibly naive-UTC) datetime."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).timestamp()
    return dt.timestamp()


def _fmt_dt(dt: datetime) -> str:
    """Format a datetime as a readable UTC string."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def _extract_code(text: str) -> str | None:
    """Pull the numeric login code out of a Telegram service message."""
    m = _LOGIN_CODE_RE.search(text)
    if m:
        return m.group(1)
    m = _FALLBACK_CODE_RE.search(text)
    return m.group(1) if m else None


async def _connect(session_string: str):
    """
    Connect using the appropriate library. Telethon strings start with "1";
    we try the detected library first and fall back to the other on failure.
    Returns (lib, client, info_dict).
    """
    order = ["telethon", "pyrogram"] if session_string.startswith("1") else ["pyrogram", "telethon"]
    last_err: Exception | None = None

    for lib in order:
        client = None
        try:
            if lib == "pyrogram":
                client = PyroClient(
                    name=f"otp_{abs(hash(session_string)) % (10 ** 8)}",
                    api_id=API_ID,
                    api_hash=API_HASH,
                    session_string=session_string,
                    in_memory=True,
                )
                await client.start()
                me = await client.get_me()
                phone = me.phone_number
                info = {
                    "name": " ".join(filter(None, [me.first_name, me.last_name])) or "—",
                    "username": me.username,
                    "phone": phone,
                    "id": me.id,
                }
            else:
                client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
                await client.connect()
                if not await client.is_user_authorized():
                    raise ValueError("Telethon session is not authorized")
                me = await client.get_me()
                info = {
                    "name": " ".join(filter(None, [me.first_name, me.last_name])) or "—",
                    "username": me.username,
                    "phone": me.phone,
                    "id": me.id,
                }
            return lib, client, info
        except Exception as e:
            last_err = e
            if client is not None:
                try:
                    await (client.stop() if lib == "pyrogram" else client.disconnect())
                except Exception:
                    pass
            continue

    raise last_err or ValueError("Could not connect with the provided session string")


async def _disconnect(state: dict) -> None:
    """Stop/disconnect the underlying userbot client."""
    client = state.get("client")
    if not client:
        return
    try:
        if state.get("lib") == "pyrogram":
            await client.stop()
        else:
            await client.disconnect()
    except Exception:
        pass


async def _cleanup(chat_id: int, cancel_timeout: bool = True) -> None:
    """Tear down an OTP session: disconnect client, cancel timer, drop state."""
    state = OTP_SESSIONS.pop(chat_id, None)
    if not state:
        return
    if cancel_timeout:
        t = state.get("timeout_task")
        if t and not t.done():
            t.cancel()
    await _disconnect(state)


async def _fetch_new_otp(state: dict):
    """
    Return (code, datetime) for the newest login-code message in the service
    chat that arrived after state['last_shown_ts'], or None if there is none.
    """
    client = state["client"]
    last_ts = state["last_shown_ts"]

    if state["lib"] == "pyrogram":
        async for m in client.get_chat_history(TELEGRAM_SERVICE_CHAT, limit=30):
            txt = m.text or m.caption
            if not txt:
                continue
            if _ts(m.date) <= last_ts:
                break  # history is newest-first; nothing newer remains
            code = _extract_code(str(txt))
            if code:
                return code, m.date
    else:
        async for m in client.iter_messages(TELEGRAM_SERVICE_CHAT, limit=30):
            txt = m.message
            if not txt:
                continue
            if _ts(m.date) <= last_ts:
                break
            code = _extract_code(txt)
            if code:
                return code, m.date
    return None


def _render(state: dict) -> str:
    """Build the message body from account info + collected OTPs."""
    info = state["info"]
    username = f"@{info['username']}" if info.get("username") else "—"
    phone = info.get("phone") or "—"
    if phone != "—" and not str(phone).startswith("+"):
        phone = f"+{phone}"

    lines = [
        "🔓 <b>OTP Reader</b>\n",
        f"👤 <b>Name:</b> {info['name']}",
        f"🔗 <b>Username:</b> {username}",
        f"📱 <b>Phone:</b> <code>{phone}</code>",
        f"📦 <b>Library:</b> {state['lib'].title()}",
    ]

    if state["otps"]:
        lines.append("\n🔐 <b>OTPs received:</b>")
        for i, (code, dt) in enumerate(state["otps"], start=1):
            lines.append(f"<blockquote>{i}. <code>{code}</code> — {_fmt_dt(dt)}</blockquote>")
    else:
        lines.append("\n<i>Waiting — press “Get OTP” after the code arrives.</i>")

    return "\n".join(lines)


def _keyboard(chat_id: int, got_otp: bool) -> InlineKeyboardMarkup:
    if got_otp:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Get another OTP", callback_data=f"otp_get:{chat_id}")],
            [InlineKeyboardButton("✅ Done", callback_data=f"otp_done:{chat_id}")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Get OTP", callback_data=f"otp_get:{chat_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"otp_cancel:{chat_id}")],
    ])


async def _expire(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Auto-stop the session after the TTL elapses."""
    try:
        await asyncio.sleep(SESSION_TTL_SECONDS)
    except asyncio.CancelledError:
        return
    state = OTP_SESSIONS.get(chat_id)
    if not state:
        return
    await _cleanup(chat_id, cancel_timeout=False)
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=state["message_id"],
            text="⏱ <b>OTP session expired</b> (10 min). Client stopped.\nRun /otp again to restart.",
            parse_mode="HTML",
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────────────────────────────────────

@owner_only
async def otp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /otp [session_string]."""
    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/otp [session_string]</code>\n\n"
            "Pass a Pyrogram or Telethon session string.",
            parse_mode="HTML",
        )
        return

    session_string = context.args[0].strip()
    chat_id = update.effective_chat.id

    # Clear any previous session in THIS chat (safe to replace your own).
    await _cleanup(chat_id)

    # Global single-session guard: only ONE OTP session may run at a time across
    # all owners. Connecting two userbots at once risks invalidating a session
    # string. There are no awaits between this check and the reservation below,
    # so the check-and-reserve is atomic on the event loop.
    if OTP_SESSIONS:
        busy = next(iter(OTP_SESSIONS.values()))
        who = (busy.get("info") or {}).get("phone") or "another account"
        await update.message.reply_text(
            "⚠️ <b>An OTP session is already running</b>"
            f" (<code>{who}</code>).\n"
            "Only one can run at a time. Finish it with “Done”, or wait — "
            "it auto-stops after 10 minutes.",
            parse_mode="HTML",
        )
        return

    # Reserve the slot immediately so a concurrent /otp is blocked while we connect.
    OTP_SESSIONS[chat_id] = {"connecting": True, "client": None, "lib": None, "info": None}

    msg = await update.message.reply_text("⏳ Checking ID…")

    try:
        lib, client, info = await _connect(session_string)
    except Exception as e:
        OTP_SESSIONS.pop(chat_id, None)  # release the reservation
        log.error(f"[OTP] Connect failed: {e}")
        await msg.edit_text(f"❌ Failed to connect: <code>{e}</code>", parse_mode="HTML")
        return

    baseline_ts = datetime.now(timezone.utc).timestamp()
    state = {
        "lib": lib,
        "client": client,
        "info": info,
        "otps": [],
        "last_shown_ts": baseline_ts,
        "message_id": msg.message_id,
        "chat_id": chat_id,
        "timeout_task": None,
    }
    OTP_SESSIONS[chat_id] = state

    state["timeout_task"] = tasks.create_task(_expire(context, chat_id), name=f"otp_ttl_{chat_id}")

    await msg.edit_text(_render(state), parse_mode="HTML", reply_markup=_keyboard(chat_id, got_otp=False))
    log.info(f"[OTP] Session started for {info.get('phone')} ({lib}) by chat {chat_id}")


async def otp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Get OTP / Get another OTP / Done / Cancel buttons."""
    query = update.callback_query

    if not is_owner(query.from_user.id):
        await query.answer("Not authorized.", show_alert=True)
        return

    action, _, cid_str = query.data.partition(":")
    chat_id = int(cid_str)
    state = OTP_SESSIONS.get(chat_id)

    if not state:
        await query.answer("This OTP session has expired. Run /otp again.", show_alert=True)
        return

    if action == "otp_cancel":
        await query.answer("Cancelled.")
        await _cleanup(chat_id)
        await query.edit_message_text("❌ <b>OTP session cancelled.</b> Client stopped.", parse_mode="HTML")
        return

    if action == "otp_done":
        await query.answer("Done.")
        await _cleanup(chat_id)
        text = _render(state) + "\n\n✅ <b>Session finished.</b> Client stopped."
        await query.edit_message_text(text, parse_mode="HTML")
        return

    # action == "otp_get"
    await query.answer("Checking…")
    try:
        result = await _fetch_new_otp(state)
    except Exception as e:
        log.error(f"[OTP] Fetch failed: {e}")
        await query.answer(f"Error reading messages: {e}", show_alert=True)
        return

    if not result:
        msg = "No new OTP received yet." if state["otps"] else "No OTP received since you started /otp."
        await query.answer(msg, show_alert=True)
        return

    code, dt = result
    state["otps"].append((code, dt))
    state["last_shown_ts"] = _ts(dt)

    try:
        await query.edit_message_text(
            _render(state), parse_mode="HTML", reply_markup=_keyboard(chat_id, got_otp=True)
        )
    except Exception:
        pass


def register(app: Application) -> None:
    """Register OTP reader handlers."""
    app.add_handler(CommandHandler("otp", otp_command))
    app.add_handler(CallbackQueryHandler(otp_callback, pattern=r"^otp_(get|done|cancel):"))
    log.info("OTP plugin registered.")
