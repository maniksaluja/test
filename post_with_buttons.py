"""Telegram post with video + 2 rich buttons (single row)."""
import os
import requests

BOT_TOKEN = os.environ["BOT_TOKEN"]          # BotFather token
CHAT_ID = os.environ["CHAT_ID"]              # @channel_username ya chat id

VIDEO_URL = "https://example.com/video.mp4"
CAPTION = "Aaj ka video dekho 👇"
WEBVIEW_URL = "https://example.com/watch"    # WebView me khulne wala link
TODAY_URL = "https://example.com/today"      # Today's posting link

API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def build_keyboard(chat_id):
    # Private chat me web_app button seedha WebView kholta hai.
    # Channel/group me web_app allowed nahi, wahan url button use hota hai.
    is_private = str(chat_id).lstrip("-").isdigit() and not str(chat_id).startswith("-")
    webview_btn = (
        {"text": "Open in WebView", "web_app": {"url": WEBVIEW_URL}}
        if is_private
        else {"text": "Open in WebView", "url": WEBVIEW_URL}
    )
    today_btn = {"text": "Today's Posting", "url": TODAY_URL}
    return {"inline_keyboard": [[webview_btn, today_btn]]}  # ek hi row


def send_post():
    resp = requests.post(
        f"{API}/sendVideo",
        json={
            "chat_id": CHAT_ID,
            "video": VIDEO_URL,
            "caption": f"{CAPTION}\n\n🎬 {VIDEO_URL}",
            "reply_markup": build_keyboard(CHAT_ID),
        },
        timeout=60,
    )
    print(resp.json())


if __name__ == "__main__":
    send_post()
