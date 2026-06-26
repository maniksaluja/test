import os 
#ADD TELEGRAM BOT TOKEN 
BOT_TOKEN  = os.getenv("BOT_TOKEN","8819471711:AAFueXwj5zBcHGyu4tgUgD8skKu_PLQx8g4")
# SET BOT USERNAME 
BOT_USERNAME = os.getenv("BOT_USERNAME","DonationReceiptTGBot")
#ADD TELEGRAM API TOKEN 
API_ID     = int(os.getenv("API_ID","24490919"))
#ADD TELEGRAM API HASH
API_HASH   = os.getenv("API_HASH","d1b3b15126c47dd4cb491553ee1db910")
#SET BOT WOEKERS
MONGODB_URL = os.getenv("MONGODB_URL","mongodb+srv://shanaya:godfather11@cluster0.t3yd7.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0") 
# Multiple owner IDs ( comma-separated )
_owner_ids_str = os.getenv("OWNER_IDS", os.getenv("OWNER_ID","7307099777,8658121298"))
OWNER_IDS = [int(x.strip()) for x in _owner_ids_str.split(",") if x.strip()]

#SET MEMEBERSHIP PLAN DURATIONS Example "1" = 1Day
MEMBERSHIP_DAYS = ["30","91","182","1",]  #membership days options 

PYROBOT_WORKERS = int(os.getenv("PYROBOT_WORKERS","4"))
LOG_LEVEL = os.getenv("LOG_LEVEL","ERROR")


#LIVE AUTOMATIC FORWARD USERBOT PYROGRAM STRING 
FORWARDING_STRING = os.getenv("FORWARDING_STRING","BQF1s6cAqHNCZBViMjehJBMcKzsq7NwRKZGYPL4w_9bZ2nJOxezKM66jxqwKOi6FTTLqZKmc7JYtGo-NcLcMjI-E4VQjyLBpa4agTAfB00D_HhgdX3ULeiuPRkOqqyl7kjKj8yKzjlX55F5XBnY3f6h2T6VbNoO3xbiiMjZUciihAo9Div8ZsXxcfXy10eURMpyXCo3PyuKYxIjNZgNtSvOnr9TjBXeE6hzqmsRbkX3bQm-4xcFNtw95o9qrcicT8L6HUpt-2NM2iND9NpRyX_K0hXcaVbnkSXnRH5bQ81ig5Yk3YHOr_KnWeqKOHED93tpv5BY6d8FlK82cZoykJPHrhd8ITwAAAAGdyakCAA")
#OLD FORWARDING USERBOT PYRROGRAM STRING 
OLDFORWARDING_STRING = os.getenv("OLDFORWARDING_STRING","BQF1s6cAqHNCZBViMjehJBMcKzsq7NwRKZGYPL4w_9bZ2nJOxezKM66jxqwKOi6FTTLqZKmc7JYtGo-NcLcMjI-E4VQjyLBpa4agTAfB00D_HhgdX3ULeiuPRkOqqyl7kjKj8yKzjlX55F5XBnY3f6h2T6VbNoO3xbiiMjZUciihAo9Div8ZsXxcfXy10eURMpyXCo3PyuKYxIjNZgNtSvOnr9TjBXeE6hzqmsRbkX3bQm-4xcFNtw95o9qrcicT8L6HUpt-2NM2iND9NpRyX_K0hXcaVbnkSXnRH5bQ81ig5Yk3YHOr_KnWeqKOHED93tpv5BY6d8FlK82cZoykJPHrhd8ITwAAAAGdyakCAA")#BQF1s6cAdLPQg6ZJOPde3x9xXA7cwD1muQ6MJ8nDSye2p3uUWEJS0wiPQvFRNjIzKo8Hv8ELJAdUbnRdS9CO7FIyL1e_Hpz3PhjhBU52o-IZStn6p6PuZOVe0471l_4gPwl92-HX-iip6FlYDA_KXUpqWaB7GmQCMos6T3FITMZd4KK-4AGqj4X6p3PBQV5DGzt0xvUi3DW2DgjvIg4025XV73EkKLl2AS-XRCwxGXGu9aoDt1vbarqa5ofNloSsdNdm7P97yslKsIbeDQCs60LZTXTnw3IF2GVmnSdqNv_flQOGdNlc9Jg8RMDgBDAWQ2XoAx7F6mNFHv_m_gPUghEOMGNCQAAAAAGdyakCAA")
# Uploader Bot Token (PTB-based) for re-uploading when forwarding is restricted
UPLOADER_BOT_TOKEN = os.getenv("UPLOADER_BOT_TOKEN", "8269675071:AAGum2fD3INa18wmhmhhmUJmhnoUHv7MX54")
# Maximum file size (in bytes) for uploader bot (2GB default, Telegram limit for bots)
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", str(2 * 1024 * 1024 * 1024)))  # 2GB

# Local Telegram Bot API Server (for files up to 2GB via MTProto)
USE_LOCAL_API = os.getenv("USE_LOCAL_API", "True").lower() in ("True", "1", "yes")
LOCAL_TGAPI_SERVER = os.getenv("LOCAL_TGAPI_SERVER", "http://187.124.19.145")

# Upload timeout settings (in seconds) for large file support (up to 2GB)
# Default 600 seconds (10 minutes) - adjust based on your upload speed
UPLOAD_TIMEOUT = int(os.getenv("UPLOAD_TIMEOUT", "600"))
## TEST LINE
#REACTION AUTO SAVE PYROGRAM STRING 
REACTION_STRING = os.getenv("REACTION_STRING","")#"AgF1s6cAKkKeZttFxq0nWnHfcEIAK9vT8HbuhPql6UxH4_CEQDD_kITZLR5dWjbJI1hnnZcZAcBG-hc2DoIrBQeq1iR6e2yMTXLf2MXuEhsuAzKURLi0wQqG9b4a19Em9t0nvjUqJGDrnyW7gtIFhnChPzknBo4ReNOCsINXlRZ0QpmpVB9VVHcjm9KnFRBqqgsXExxKu1dxxeYcTkJvE345ErwNE9GVYT-RCGIgVvNBG-Gl14QsYE-mgcVpGnWXXNqeUrF-j4slpXfMn_W323NVCIawo17M0iv1RQ3VvgA-K_BgvJ77mwmO0PlIU1SeDZ-pAyFRP5ibIDTZT8SuRWdk_ahROAAAAAGziX6BAA")
TRIGGER_EMOJI = os.getenv("TRIGGER_EMOJI","👍")
REACTION_FORWARDTO = os.getenv("REACTION_FORWARDTO","7096656098") ##can be 'saved' or chat id / userid where you want to forward
THUMBNAIL_TEXT = os.getenv("THUMBNAIL_TEXT","@ShanayaAlertsTG")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME","Cute_GirlTG")
FWD_STICKER = os.getenv("FWD_STICKER", "AAMCBQADGQEAASkY62oCHPF1lBq6A2jyuWWN_H1wcPT1AAIcDgACAZaAVdEb4sBYkgfPAQAHbQADOwQ")
FWD_EMOJI = os.getenv("FWD_EMOJI", "👍")
EXPIRY_NOTIFY_OWNER = os.getenv("EXPIRY_NOTIFY_OWNER", "True").lower() in ("true", "1", "yes")
