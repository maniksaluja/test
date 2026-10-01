"""Telegram bot: /start pe video + text + 2 rich buttons (Bot API 10.3).

Long polling, sirf `requests` chahiye. Config env variables se aata hai.
"""
import os
import sys
import time

import requests
BOT_TOKEN = os.environ["8806844930:AAH6mYLRHywwx6VJ0-fC3zpkfTSs7rbmupw"]          # BotFather token
CHAT_ID = os.environ["@hehduehdhehhe"]              # @channel_username ya chat id

VIDEO_URL = os.environ.get("https://gofile.io/d/rtcN3TKm")
POST_TEXT = os.environ.get("ShanayaFANBaseBot Has Been Updated With Fresh Content.!!! \n\n• Indian 𝘊𝘰𝘯𝘵𝘦𝘯𝘵▾ \n>17 𝘓𝘪𝘯𝘬𝘴 𝘗𝘰𝘀𝘵𝘦𝘥\n• Global 𝘊𝘰𝘯𝘵𝘦𝘯𝘵▾\n> 21 𝘓𝘪𝘯𝘬𝘴 𝘗𝘰𝘀𝘵𝘦𝘥\n• Dark 𝘊𝘰𝘯𝘵𝘦𝘯𝘵▾\n>02 𝘓𝘪𝘯𝘬𝘴 𝘗𝘰𝘀𝘵𝘦𝘥\n• Others 𝘊𝘰𝘯𝘵𝘦𝘯𝘵▾\n> 08 𝘓𝘪𝘯𝘬𝘴 𝘗𝘰𝘀𝘵𝘦𝘥\n\n≼The Perspective≽\nTotal Links Submitted≽  48\n All-over Reaction As Per Feedback\n👍🏻84 • ❤️‍🔥133 • 😂14 • 🤤14• \n>👎🏻7 • 💔0 • 😭0 • 🤬14• ")
WEBVIEW_URL = os.environ.get("WEBVIEW_URL", "https://example.com/watch")
TODAY_URL = os.environ.get("TODAY_URL", "https://example.com/today")


class TelegramError(RuntimeError):
    pass


def call(api, method, payload, timeout=70):
    resp = requests.post(f"{api}/{method}", json=payload, timeout=timeout)
    data = resp.json()
    if not data.get("ok"):
        raise TelegramError(f"{method}: {data.get('error_code')} {data.get('description')}")
    return data["result"]


def build_keyboard(chat_type):
    # web_app button sirf private chat me allowed hai
    if chat_type == "private":
        webview_btn = {"text": "Open in WebView", "web_app": {"url": WEBVIEW_URL}}
    else:
        webview_btn = {"text": "Open in WebView", "url": WEBVIEW_URL}
    webview_btn["style"] = "primary"  # blue
    today_btn = {"text": "Today's Posting", "url": TODAY_URL, "style": "success"}  # green
    return {"inline_keyboard": [[webview_btn, today_btn]]}  # ek hi row


def is_direct_video(url):
    return url.lower().split("?")[0].endswith((".mp4", ".mov", ".webm", ".m4v"))


def send_post(api, chat_id, chat_type):
    keyboard = build_keyboard(chat_type)
    if not is_direct_video(VIDEO_URL):
        # gofile jaise page link video player me nahi chalte; link text me bhejo
        call(api, "sendMessage", {
            "chat_id": chat_id,
            "text": f"{POST_TEXT}\n\n🎬 {VIDEO_URL}",
            "reply_markup": keyboard,
        })
        return
    try:
        call(api, "sendRichMessage", {
            "chat_id": chat_id,
            "rich_message": {"markdown": f"![]({VIDEO_URL})\n\n{POST_TEXT}"},
            "reply_markup": keyboard,
        })
    except TelegramError as err:
        print(f"sendRichMessage fail ({err}); sendVideo fallback", flush=True)
        call(api, "sendVideo", {
            "chat_id": chat_id,
            "video": VIDEO_URL,
            "caption": POST_TEXT,
            "reply_markup": keyboard,
        })


def is_start(message):
    text = (message.get("text") or "").split()
    return bool(text) and text[0].split("@")[0] == "/start"


def run():
    if not BOT_TOKEN:
        sys.exit("BOT_TOKEN env variable set karo")
    api = f"https://api.telegram.org/bot{BOT_TOKEN}"
    offset = None
    print("Bot chalu, /start ka wait", flush=True)
    while True:
        try:
            updates = call(api, "getUpdates", {
                "offset": offset, "timeout": 50, "allowed_updates": ["message"],
            })
        except (requests.RequestException, TelegramError) as err:
            print(f"getUpdates error: {err}", flush=True)
            time.sleep(5)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message")
            if not message or not is_start(message):
                continue
            chat = message["chat"]
            try:
                send_post(api, chat["id"], chat["type"])
            except (requests.RequestException, TelegramError) as err:
                print(f"send error: {err}", flush=True)


if __name__ == "__main__":
    run()
