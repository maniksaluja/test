"""Telegram rich post: video + text + 2 rich (styled) buttons in one row.

Bot API 10.3: sendRichMessage + InlineKeyboardButton.style.
"""
import os
import sys

import requests

BOT_TOKEN = os.environ.get("BOT_TOKEN")      # BotFather token
CHAT_ID = os.environ.get("CHAT_ID")          # @channel_username ya numeric chat id

VIDEO_URL = os.environ.get("VIDEO_URL", "https://example.com/video.mp4")
POST_TEXT = os.environ.get("POST_TEXT", "Aaj ka video dekho 👇")
WEBVIEW_URL = os.environ.get("WEBVIEW_URL", "https://example.com/watch")
TODAY_URL = os.environ.get("TODAY_URL", "https://example.com/today")


def is_private_chat(chat_id):
    # Private chat id hamesha positive number hota hai
    return str(chat_id).isdigit()


def build_keyboard(chat_id):
    # web_app button sirf private chat me allowed; channel/group me url use karo
    if is_private_chat(chat_id):
        webview_btn = {"text": "Open in WebView", "web_app": {"url": WEBVIEW_URL}}
    else:
        webview_btn = {"text": "Open in WebView", "url": WEBVIEW_URL}
    webview_btn["style"] = "primary"   # blue
    today_btn = {"text": "Today's Posting", "url": TODAY_URL, "style": "success"}  # green
    return {"inline_keyboard": [[webview_btn, today_btn]]}  # ek hi row


def call(api, method, payload):
    resp = requests.post(f"{api}/{method}", json=payload, timeout=60)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"{method} failed: {data.get('error_code')} {data.get('description')}")
    return data["result"]


def send_post():
    if not BOT_TOKEN or not CHAT_ID:
        sys.exit("BOT_TOKEN aur CHAT_ID env variable set karo")
    for name, url in (("VIDEO_URL", VIDEO_URL), ("WEBVIEW_URL", WEBVIEW_URL), ("TODAY_URL", TODAY_URL)):
        if not url.startswith("https://"):
            sys.exit(f"{name} https:// se start hona chahiye")

    api = f"https://api.telegram.org/bot{BOT_TOKEN}"
    keyboard = build_keyboard(CHAT_ID)
    rich_message = {"markdown": f"![]({VIDEO_URL})\n\n{POST_TEXT}"}

    try:
        result = call(api, "sendRichMessage", {
            "chat_id": CHAT_ID,
            "rich_message": rich_message,
            "reply_markup": keyboard,
        })
    except RuntimeError as err:
        # Fallback: purana sendVideo, same styled buttons
        print(f"Rich message nahi gaya ({err}), sendVideo try kar raha hu")
        result = call(api, "sendVideo", {
            "chat_id": CHAT_ID,
            "video": VIDEO_URL,
            "caption": POST_TEXT,
            "reply_markup": keyboard,
        })
    print(f"Post ho gaya, message_id={result['message_id']}")


if __name__ == "__main__":
    send_post()
