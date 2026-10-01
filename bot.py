"""Button test bot: /start bhejo, post aa jayegi. Sirf python3 chahiye.

Chalao:  BOT_TOKEN=xxxx python3 bot.py
"""
import json
import os
import sys
import time
import urllib.request

VIDEO_URL = "https://files.catbox.moe/srjre7.mp4"
BTN1_TEXT = "Open in WebView"
BTN1_URL = VIDEO_URL            # test ke liye; baad me apna link daalo
BTN2_TEXT = "Today's Posting"
BTN2_URL = VIDEO_URL            # test ke liye; baad me apna link daalo

POST_TEXT = """ShanayaFANBaseBot Has Been Updated With Fresh Content.!!! 

• Indian 𝘊𝘰𝘯𝘵𝘦𝘯𝘵▾ 
 17 𝘓𝘪𝘯𝘬𝘴 𝘗𝘰𝘀𝘵𝘦𝘥 
• Global 𝘊𝘰𝘯𝘵𝘦𝘯𝘵▾ 
 21 𝘓𝘪𝘯𝘬𝘴 𝘗𝘰𝘀𝘵𝘦𝘥 
• Dark 𝘊𝘰𝘯𝘵𝘦𝘯𝘵▾ 
 02 𝘓𝘪𝘯𝘬𝘴 𝘗𝘰𝘀𝘵𝘦𝘥 
• Others 𝘊𝘰𝘯𝘵𝘦𝘯𝘵▾ 
 08 𝘓𝘪𝘯𝘬𝘴 𝘗𝘰𝘀𝘵𝘦𝘥 

≼The Perspective≽ 
Total Links Submitted≽  48
All-over Reaction As Per Feedback
👍🏻84 • ❤️‍🔥182 • 😂14 • 🤤21• 
👎🏻7 • 💔0 • 😭7 • 🤬14•"""

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    sys.exit("Chalao: BOT_TOKEN=xxxx python3 bot.py")
API = f"https://api.telegram.org/bot{TOKEN}"


def call(method, payload):
    req = urllib.request.Request(
        f"{API}/{method}", json.dumps(payload).encode(),
        {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=70) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        data = json.load(e)
    if not data.get("ok"):
        raise RuntimeError(f"{method}: {data.get('description')}")
    return data["result"]


def keyboard(chat_type):
    # web_app sirf private chat me chalta hai
    b1 = {"text": BTN1_TEXT, "style": "primary"}
    if chat_type == "private":
        b1["web_app"] = {"url": BTN1_URL}
    else:
        b1["url"] = BTN1_URL
    b2 = {"text": BTN2_TEXT, "url": BTN2_URL, "style": "success"}
    return {"inline_keyboard": [[b1, b2]]}  # ek line me 2 button


def send_post(chat):
    kb = keyboard(chat["type"])
    try:
        call("sendRichMessage", {
            "chat_id": chat["id"],
            "rich_message": {"markdown": f"![]({VIDEO_URL})\n\n" + POST_TEXT.replace("\n", "  \n")},
            "reply_markup": kb,
        })
    except RuntimeError as e:
        print("rich fail, sendVideo try:", e, flush=True)
        call("sendVideo", {"chat_id": chat["id"], "video": VIDEO_URL,
                           "caption": POST_TEXT[:1024], "reply_markup": kb})


offset = None
print("Bot chalu. /start bhejo.", flush=True)
while True:
    try:
        for u in call("getUpdates", {"offset": offset, "timeout": 50, "allowed_updates": ["message"]}):
            offset = u["update_id"] + 1
            m = u.get("message") or {}
            if (m.get("text") or "").startswith("/start"):
                send_post(m["chat"])
                print("post bheji", flush=True)
    except Exception as e:
        print("error:", e, flush=True)
        time.sleep(5)
