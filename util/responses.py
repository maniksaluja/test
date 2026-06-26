"""
Centralized bot response messages.
All user-facing strings live here for easy editing and i18n.
"""
from config import SUPPORT_USERNAME

# ─────────────────────────────────────────────────────────────────────────────
# General
#  <blockquote>👋 <b>TEXT HERE!</b></blockquote> (blockquote)
# 👋 <b>TEXT HERE!</b> (Bold text)
# <code>👋 Text here</code> (monospace)
# ─────────────────────────────────────────────────────────────────────────────
START_RESPONSE = (
    "<b>WELCOME TO SHANAYA PREMIUM BOT!</b>\n"
    "<blockquote> <b>•Meybee Your Entered CMAND Is Wrong.</b> </blockquote>\n"
    "<blockquote> <b>•For BUY ANY ACCESS Contact To Admin</b> </blockquote>"
)

STARTMSG_BTN1 = "𝘈𝘥𝘮𝘪𝘯"
STARTMSG_BTN2 = "𝘎𝘦𝘵 𝘍𝘳𝘦𝘦"
STARTMSG_BTN1URL = "https://t.me/Cute_GirlTG?text=%2A%2AHey%2C%20I%20am%20interested%20in%20your%20premium%20plans.%20Can%20you%20please%20send%20me%20the%20list%3F%2A%2A"
STARTMSG_BTN2URL = f"https://t.me/Shanaya_Alerts"

# User help (shown to regular users)
HELP_USER = """
<b>📚 Available Commands</b>

<blockquote>General</blockquote>
/start - Start the bot
/help - Show this help

<blockquote>Session Generator</blockquote>
/string - Generate Pyrogram/Telethon session string
/cancel - Cancel session generation

💡 <i>Use deep links to request access to groups!</i>
"""

# Owner help (shown to owners only)
HELP_OWNER = """
<b>👑 Owner Commands</b>

<blockquote> Membership Management </blockquote>
/list - List managed groups with access links
/add - Register a group (by ID or in-group)

<blockquote> Batch Links </blockquote>
/batch - Start creating a new batch
/makeit - Save current batch
/batcheslist - List all batches
/editb &lt;batch_id&gt; - Edit existing batch
/deleteb &lt;batch_id&gt; - Delete a batch
/cancel - Cancel batch creation

<blockquote>Broadcast</blockquote>
/bcast - Send message to all users
Reply to message or /bcast &lt;text&gt;

<blockquote> Stats </blockquote>
/users - Alias for /stats

<blockquote> Live Forwarding </blockquote>
/live - Manage live forwarders (origin → target)
/forward - same as Live

<blockquote> Old Forwarding </blockquote>
/oldforward - Batch forward existing messages
              Just send a Telegram post link to start!

<blockquote> Session Management </blockquote>
/sessions - List all saved sessions
/data &lt;phone&gt; - View session details for a phone number

<blockquote> Unzipper </blockquote>
/unzip - Extract archives (ZIP, RAR, 7z, tar.gz)
         Reply to archive or provide URL

<blockquote> User Commands </blockquote>
/start - Start the bot
/help - Show this help
/string - Generate session string
/cancel - Cancel active operation

<b> Tips </b>
• Use /addgroup in a group to register it
• Access links: <code>t.me/Bot?start=join_CODE</code>
• Batch links: <code>t.me/Bot?start=batch_ID</code>
• Membership cron runs every 10 min
• Forward cron retries failed items every 5 min
• Old forward: send any t.me post link to start
"""

UNAUTHORIZED = "<blockquote><b>You Are Not Authorized To Use This Command.</b></blockquote>"

# ─────────────────────────────────────────────────────────────────────────────
# Unzipper
# ─────────────────────────────────────────────────────────────────────────────
UNZIP_CHECKING = "<b>Scanning File..</b>"
UNZIP_DOWNLOADING = "⬇️ Downloading...{size}"
UNZIP_EXTRACTING = "<b>Extracting...</b>"
UNZIP_PASSWORD_REQUIRED = (
    "<b>• Password Protected File</b>\n"
    "<blockquote><b>Send File Password To Go Next Step !!! </b></blockquote>"
)
UNZIP_CANCELLED = "❌ Unzip Cancelled."
UNZIP_SENDING = "<b>EXTRACTION COMPLETE </b>\n<blockquote><b>•File Sent: {current}/{total} </b></blockquote>"
UNZIP_COMPLETE = "✅ Extraction complete! Sent {count} file(s)."
UNZIP_FAILED = "❌ Extraction failed <blockquote> {error} </blockquote>"
UNZIP_QUEUED = "<b>• You Have To Wait : {position}</b>"
UNZIP_PROCESSING = "Zip Detected! Processing..."
UNZIP_SIZE_ERROR = "❌ Not enough disk space today extract this archive."
UNZIP_INVALID = "<b>Please Reply To A Zip File</b>"

# ─────────────────────────────────────────────────────────────────────────────
# Membership
# ─────────────────────────────────────────────────────────────────────────────
# Owner: /groups command
MEMBERSHIP_GROUPS_HEADER = "<b>List Of Memebership Plans:</b>\n"
MEMBERSHIP_GROUPS_EMPTY = """📭<b>There Is 0 Request In DataBase \n\nUse /add {ChannelID} to Add New Request</b>"""
MEMBERSHIP_GROUP_ITEM = (
    "{num}.<b>Name≽ {group_name}</b>\n"
    "<b>• ChannelID≽ {group_id}</b>\n"
    "<b>• Status≽ {status}</b>\n"
    "<blockquote><b>• Url Link≽ https://t.me/{bot_username}?start=join_{access_code}</b></blockquote>\n"
)

# User: Deep link request flow
MEMBERSHIP_INTEREST = (
    "👋 <b>Hey!</b> Seems you're interested in joining\n\n"
    "📍 <b>Group:</b> {group_name}\n\n"
    "We manually review and give access to users.\n"
    "To join, request access using the button below.\n\n"
    "Once approved, you'll receive an invite link."
)
MEMBERSHIP_REQUEST_BTN = "🔐 Request Access"
MEMBERSHIP_ALREADY_REQUESTED = (
    "<b>Wait For The Approval</b>\n"
    "<blockquote><b>Your Request For The {group_name} Is Already Pending With Us. Kindly Wait For Approval</b></blockquote>"
)
MEMBERSHIP_ALREADY_MEMBER = (
    "<b>•You Have Already Access≽ {group_name}</b>\n"
    "<blockquote><b>📅 Expires At≽ {expires}</b></blockquote>"
)
MEMBERSHIP_REQUEST_SENT = (
    "<b>• Request Submitted To Admin  </b>\n"
    "<blockquote><b>Your Request To Join {group_name} Has Been Sent To Admins.</b></blockquote>"
    "<blockquote><b>We'll Notify You Once it's Reviewed.</b></blockquote>"
)
MEMBERSHIP_GROUP_NOT_FOUND = "❌ This Category Is Not Available Or Has Been Deactivated."
MEMBERSHIP_GROUP_INACTIVE = "⚠️ This category Is Currently Not Accepting New Members."

# Owner: Approval notification
MEMBERSHIP_OWNER_REQUEST = (
    "📥 <b>New Membership Request</b>\n\n"
    "<b>• Channel Name≽ </b> {group_name}\n"
    "<b>• UserName≽</b> {user_mention}\n"
    "<b>• UserID≽ </b> <code>{user_id}</code>\n"
    "<blockquote><b>Choose Duration Time to Aprove </b></blockquote>"
)

# User: Declined 
MEMBERSHIP_DECLINED = (
    "<b>Request Rejected By Admin </b>\n\n"
    "<b> Extremely Sorry !!!!😔</b>\n"
    "<blockquote><b>Your Request To Join {group_name} Was Not Approved.</b></blockquote>\n"
    "<b>Contact Admin for more information.</b>"
)
MEMBERSHIP_CONTACT_SUPPORT = "𝘊𝘰𝘯𝘵𝘢𝘤𝘵 𝘛𝘰 𝘈𝘥𝘮𝘪𝘯"

# User: Approved 
MEMBERSHIP_APPROVED = (
    "🎉 <b>Your Membership Request Granted!!!</b>\n"
    "<b>Now You Have Access To Join≽ {group_name}</b>\n\n"
    "<blockquote><b>• Valid For≽ {days} Days</b></blockquote>\n"
    "<blockquote><b>• Expire At≽ {expires}</b></blockquote>\n"
    "<blockquote><b>NOTE: Delete This Message, And You Won't Get The Join URL Again. Plan Duration Starts Once Approved</b></blockquote>\n"
    "<b>Click Below To Join Memebership :</b>"
)
MEMBERSHIP_JOIN_BTN = "𝖩𝗈𝗂𝗇 𝖬𝖾𝗆𝖻𝖾𝗋𝗌𝗁𝗂𝗉 "

# Owner: Approval confirmation (sent to owner after approving) 
MEMBERSHIP_OWNER_APPROVED = (
    "<b>Request Approved Successfully</b>\n\n"
    "<b>• Channel≽ </b> {group_name}\n"
    "<b>• UserID≽ </b> {user_mention}\n"
    "<b>• Duration≽ </b> {days} Days Plan\n"
    "<blockquote><b>Expire At≽</b> {expires} </blockquote>"
)

# User: Expired notification
MEMBERSHIP_EXPIRED = (
    "<b>Hi !!!, Your {group_name} Plan Has Expired </b>\n\n"
    "<b>⚠️ Please Note </b>\n"
    "<blockquote><b>That Your Access To The Channel Is Currently Inactive. If You Do Not Renew Your Plan, You Will Be Removed From The Channel Automatically.</b></blockquote>\n"
    f"<b>Continue Uninterrupted Access By Clicking The Buy Again Button Below To Renew Your Plan.</b>."
)
MEMBERSHIP_EXPIRED_BTN = "𝘽𝙪𝙮 𝙋𝙡𝙖𝙣" ## @{SUPPORT_USERNAME}

# Owner notification for expired memberships
EXPIRY_SUDO_MSG = (
    "<b>USER MEMBERSHIP EXPIRED</b>\n\n"
    "<blockquote><b>• UserID ≽ {user_mention}</b></blockquote>\n"
    "<blockquote><b>• ChannelID ≽ {group_name}</b></blockquote>"
)
SUDO_EXPIRE_BTN = "𝘈𝘴𝘬 𝘍𝘰𝘳 𝘙𝘦𝘯𝘦𝘸"

# Owner: Toggle status
MEMBERSHIP_ACTIVATED = "✅ Channel <b>{group_name}</b> Is Now <b>ACTIVE</b>."
MEMBERSHIP_DEACTIVATED = "❌ Channel <b>{group_name}</b> Is Now <b>INACTIVE</b>."

# ─────────────────────────────────────────────────────────────────────────────
# Session Generator
# ─────────────────────────────────────────────────────────────────────────────
SESSION_WELCOME = (
    "<b>String Session Mode Activated</b> \n"
    "<blockquote><b>Choose Your String Type</b></blockquote> "
)
SESSION_PHONE_PROMPT = (
    "<b>• Send Your Number With Country Code.</b>\n"
    "<blockquote><b>Example: +917890000001 </b></blockquote>\n "
    "<b>Use ❌ Cancel To Abort.</b>"
)
SESSION_OTP_SENT = (
    "<b>📩 OTP Sent To Your Telegram App.</b>\n\n"
    "<b>⚠️ IMPORTANT:</b>\n"
    "<blockquote><b>Send Your OTP With Spaces Between Digits</b>.\n"
    "<b>Example: If Your OTP Is 12345, Send1 2 3 4 5</b></blockquote>\n"
    "<b>Click ❌ Cancel To Abort.</b>"
)
SESSION_2FA_PROMPT = (
    "<b>🔒2-Step Verification Is Enabled.</b>\n"
    "<blockquote><b>• 2-Step Hint: {hint} </b></blockquote>\n"
    "<blockquote><b>• Send your 2FA Password </b></blockquote>\n"
    "<b>Click ❌ Cancel To Abort</b>"
)
SESSION_SUCCESS = (
    "<b>String Generated For</b> {phone} \n\n"
   "<b>• Your String Session is bellow </b>\n"
    "<blockquote> {session} </blockquote>"
)
SESSION_INVALID_PHONE = "<b>❌ Invalid Phone Format. Use +[country Code][number]</b>."
SESSION_CANCELLED = "<b>❌ Session Generation Cancelled.</b>"

# ─────────────────────────────────────────────────────────────────────────────
# Old Forwarder
# ─────────────────────────────────────────────────────────────────────────────
OLDFWD_NOT_READY = (
    "⚠️ <b>• OLD Forward Client Is Not Ready</b>\n"
    "<blockquote><b>Please Check Your OldForward String In Config.py Folder Or Check VPS Logs </b></blockquote>"
)
OLDFWD_JOB_RUNNING = (
    "<b>• Sorry  I Can't Process This Request</b>\n"
    "<blockquote><b>Earlier In The Forward Request, You Will Need To Wait For It To Complete In The Progress Section.</b></blockquote>\n"
    "<b>Please Wait For It To Complete.</b>"
)
OLDFWD_HELP = (
    "📤 <b>OLD FORWARDER ACTIVATD</b>\n"
    "<blockquote><b> Oldforwarder Is Activated. Share The Copy Link To Start The Process.</b></blockquote>\n"
    "<b>Verify The Link Before Sharing.</b>"
    
)
OLDFWD_CHAT_ACCESS_ERROR = (
    "<b>❌ Cannot Access This Chat.\n"
    "<blockquote><b>Make Sure The UserBot Is A Member.</b></blockquote>"
)
OLDFWD_START_DETECTED = (
    "📥 <b>OLD FORWARDER TASK RUNING..</b>\n\n"
    "<b>• Channel≽</b> {chat_name}\n"
    "<b>• ChannelID≽ </b> <code>{chat_id}</code>\n"
    "<b>• Start FileID≽<code>{msg_id}</code> </b>\n"
    "<blockquote><b>Now send me the LAST Copylink To Process.</b></blockquote>"
)
OLDFWD_WRONG_CHAT = (
    "<b>• This Link Is From A Different Chat.</b>\n"
    "<blockquote><b>Use Right CopyLink..</b></blockquote> "
)
OLDFWD_RANGE_CONFIRMED = (
    "<b>CHECK YOUR CONFIGURATION !! </b>\n\n"
    "<blockquote><b>• Starting≽ <code>{start_id}</code></b></blockquote>\n"
    "<blockquote><b>• Ending≽  <code>{end_id}</code></b></blockquote>\n"
    "<b>• Total FileID≽</b> {total} \n"
    "<b>Choose Where To Send These FileID</b>"
)
OLDFWD_PAGE_INFO = ""
OLDFWD_CANCELLED = "<b>❌ Old Forwarding Cancelled</b>."
OLDFWD_SESSION_EXPIRED = "<b>❌ String Expired. Please Start Again!!!.</b>"
OLDFWD_CLIENT_NOT_READY = "<b>❌ UserBot  Not Ready...</b>"
OLDFWD_ANOTHER_JOB = "⏳<b> Another Job Is Running...</b>\n<blockquote><b>Please Wait....</b></blockquote>"
OLDFWD_PROGRESS = (
    "📤 <b>OLD FORWARDER ACTIVATED </b>\n\n"
    "<blockquote><b>• source</b> {origin}</blockquote>\n"
    "<blockquote><b>• Target </b> {target} </blockquote>\n\n"
    "<b>• Total FileID≽ </b> {total}\n"
    "<b>• Total Failed≽ </b> {failed}\n"
    "<blockquote><b> [{bar}] {percent}% </b></blockquote>\n"
    "<b>• Sent : {forwarded}/{total} Elapsed : {elapsed} </b>\n"
)
OLDFWD_COMPLETE = (
    "✅ <b>OLD FORWARDING COMPLETE !!!</b>\n\n"
    "<blockquote><b>• Source≽ {origin} </b></blockquote>\n"
    "<blockquote><b>• Target≽ {target} </b></blockquote>\n"
    "<blockquote><b>• Time≽ {time} </b></blockquote>\n"
    "<b> Total Sent≽ {forwarded}  Total Failed≽ {failed} </b>\n"

)
OLDFWD_STOPPED = (
    "🛑 <b>OLD FORWARDER STOPPED</b>\n\n"
    "<blockquote><b>• Source≽ {origin} </b></blockquote>\n"
    "<blockquote><b>• Target≽ {target} </b></blockquote>\n"
    "<blockquote><b>• Time≽ {time} </b></blockquote>\n"
    "<b>• Total Sent≽ {forwarded}  Total Failed≽ {failed} </b>"
)
OLDFWD_FAILED = (
    "❌ <b>Forwarding Failed</b>\n\n"
    "<blockquote><b> Error≽ {error} </b></blockquote>\n"
    "<b>Sent≽ {forwarded}, UnSend≽ {failed} </b>"
)
  
OLDFWD_NO_PERMISSION = (
    "❌ <b>OLD FORWARD FAILED</b>\n\n"
    "<blockquote><b>• Source≽ {origin} </b></blockquote>\n"
    "<blockquote><b>• Target≽ {target} </b></blockquote>\n"
    "<b>⚠️ FORWARDING FAILED</b>\n"
    "<blockquote><b>Because Assistant Does Not Have Permission To Send Message In Target</b></blockquote>."
)
OLDFWD_OPTIONS = (
    "<b>⚙️ FORWARDING OPTIONS</b>\n\n"
    "<blockquote><b>Messages</b> — Include text-only messages in forward?</blockquote>\n"
    "<blockquote><b>Album</b> — Forward media groups as albums (grouped)?</blockquote>\n\n"
    "<b>Set your options then press Start:</b>"
)
LIVEFWD_OPTIONS = (
    "<b>⚙️ FORWARDER OPTIONS</b>\n\n"
    "<blockquote><b>Messages</b> — Include text-only messages in forward?</blockquote>\n"
    "<blockquote><b>Album</b> — Forward media groups as albums (grouped)?</blockquote>\n\n"
    "<b>Set your options then press Add Forwarder:</b>"
)

# ─────────────────────────────────────────────────────────────────────────────
# Batch Link
# ─────────────────────────────────────────────────────────────────────────────
BATCH_STARTED = (
    "<b>OKAY Now I Can Make Batch Link\nWhen You Are Done Use /makeit /cancel</b>"
)
BATCH_EDIT_STARTED = (
    "✏️ <b>Editing Batch {batch_id}</b>\n\n"
    "<b>Current Items≽ {count} </b>\n"
    "<b>Forward New Messages To Add, Then /makeit To Save.</b>"
)
BATCH_ADDED = "✓ Added ({count}) - Stored in bot's DM"
BATCH_CREATED = (
    "✅ <b>New Batch Link Created !!!</b>\n\n"
    "<b>• BatchID≽</b> <code>{batch_id}</code>\n"
    "<b>• Total Items≽</b> {count} \n"
    "<blockquote><b>• Share Link:</b> t.me/{bot_username}?start=batch_{batch_id} </blockquote>"
)
BATCH_UPDATED = (
    "✅ <b>Batch Updated!</b>\n\n"
    "<b>• Batch ID≽ </b> <code>{batch_id}</code>\n"
    "<b>• Total Items≽ </b> {count} \n"
    "<b>• Share Link≽</b> t.me/{bot_username}?start=batch_{batch_id} "
)
BATCH_NOT_FOUND = "❌ Batch Not Found."
BATCH_CANCELLED = "❌ Batch Creation Cancelled."
BATCH_EMPTY = "<b>❌ No Messages Added To Batch. </b> \n<blockquote><b> Send /batch To Start Again.</b></blockquote>"
BATCH_NO_ACTIVE = "❌ No Active Batch Session. Use /batch To Create One."
BATCH_ALREADY_ACTIVE = (
    "<blockquote><b>You Already Have An Active Batch Session.</b></blockquote>"
    "<blockquote><b>Use /makeit To Save It Or /cancel To Discard</b></blockquote>."
)
BATCH_CANNOT_ACCESS = (
    "❌ Cannot access this message.\n"
    "Ensure bot is a member of the source group/channel."
)

# Batch list
BATCH_LIST_HEADER = "<blockquote><b>Total {count} batch Links Created</b></blockquote>\n\n"
BATCH_LIST_EMPTY = "<b>No Batches Created Yet.\nUse /batch To Create One.</b>"
BATCH_LIST_ITEM = (
    "{num}. <b>BatchID≽</b> <code>{batch_id}</code>\n"
    "<blockquote>• Source≽  {source} </blockquote>\n"
    "<blockquote>• Items≽  {count} </blockquote>\n"
    "<blockquote>• Created≽ {created} </blockquote>\n"
    "<blockquote>• Updated≽ {updated} </blockquote>\n"
  #  "<blockquote>• Link Url≽ t.me/{bot_username}?start=batch_{batch_id} </blockquote>"
)

# User access request
BATCH_REQUEST_SENT = (
    "<b>• Your Request Has Been Sent To Admin. Please wait for approval.</b>\n\n"
    "<b>⚠️ WARRING!!!</b>\n"
    "<blockquote><b> Do not send repeated requests. Inform the admin after sending the request.</b></blockquote>"
)
BATCH_INACTIVE = "⚠️<b> This Batch Is Currently Not Available.</b>"
BATCH_ACCESS_DECLINED = (
    "<b>Batch Request Rejected By Admin : </b>\n\n"
    "<blockquote><b>• Your Request For Batch {batch_id} Was Not Approved </b></blockquote>\n"
    "<blockquote><b>• Meybee You Have Already.Access Of This Batch </b></blockquote>"
)
BATCH_ACCESS_GRANTED = (
    "<blockquote><b>Your Request Successfully Aprroved By Admin For Batch {batch_id} </b></blockquote>\n\n"
    "•<b>Sending {count}\n Sending All Media In Your Inbox  Thank You For Your Presence 💕</b> "
)
BATCH_ACCESS_QUEUED = (
    "<b>Your Batch Access Request Granted!!!</b>\n\n"
    "<blockquote><b>You Have Another Batch Delivery In Progress.\nYour Content Will Be sent Shortly.\nPlease Wait......</b></blockquote>"
)
BATCH_DELIVERY_COMPLETE = (
    "<b>All {total} In This Batch Have Been Forwarded!!</b>\n"
    "<blockquote><b>Next Time You have To Pay If You Want To Access Again!!</b></blockquote>\n"
    "<b>PLEASE PIN THIS BOT FOR FUTURE SAFETY!!</b>"
)

# Batch delivery start/end messages (sent to user)
SEND_BATCH_START_MSG = False

BATCH_START_MSG = (
    "<blockquote><b>Your Request Sucessfully Aprroved By Admin For Batch {batch_id} </b></blockquote>\n\n"
    "<b>• Sending {count} Sending All Media In Your Inbox Thank You For Your Presence 💕</b> "
    "<b>MEMEBERSHIP MODE≽</b> {mode}"
)
BATCH_END_MSG = (
   "<blockquote><b>All Item In This Batch Have Been Forwarded</b></blockquote>\n"
    "<b>• BatchID≽ </b> <code>{batch_id}</code>\n"
    "<b>• Mode≽ </b> {mode}\n"
    "<blockquote><b>Next Time You have To Pay If You Want To Access Again!!</b></blockquote>\n"
    "<b>PIN THIS BOT FOR FUTURE SAFETY!</b>"
)

# Owner approval
BATCH_OWNER_REQUEST = (
    "<blockquote><b>User Sent  Batch Access Request</b></blockquote>\n\n"
    "<b>• BatchID≽ </b> <code>{batch_id}</code>\n"
    "<b>• UserID≽ </b> {user_mention}\n"
    "<b>• UserID≽ </b>{user_id} \n"
    "<b>• Totel Item≽ </b> {count}\n"
    "<blockquote><b>Please Choose Plan Type : </b></blockquote>"
)
BATCH_OWNER_APPROVED = (
    "<blockquote><b>User Batch Request Approved✅</b></blockquote>\n\n"
    "<b>• BatchID≽ </b> {batch_id}\n"
    "<b>• UserID≽ </b> {user_mention}\n"
    "<b>• Mode Type≽  </b> {mode}"
)
BATCH_ALREADY_HANDLED = "This Request Was Already Handled By Another Admin."

# ─────────────────────────────────────────────────────────────────────────────
# Broadcast
# ─────────────────────────────────────────────────────────────────────────────
BROADCAST_NO_MESSAGE = (
    "<b>No Message To Broadcast</b> <blockquote><b>Use /Bcast {tag that Msg }</b></blockquote>"
)
BROADCAST_IN_PROGRESS = (
    "⏳ <b>Broadcast Already Running...</b>"
)
BROADCAST_READY = (
    "<blockquote><b> Broadcast Post Is Ready</b></blockquote>\n\n"
    "<b>• Total Users≽ </b> {total_users}\n"
    "<b>• Broadcasting to≽ </b> {broadcastable_users}\n"
    "<b>• ETA≽ </b> {eta}\n\n"
    "<blockquote><b>Click Below To Start Broadcasting...</b></blockquote>"
)
BROADCAST_PROGRESS = (
    "<blockquote><b>📢Broadcast In Progress</b></blockquote>\n\n"
    "<b>• Total≽ </b> {total}\n"
    "<b>• Sent≽ </b> {sent}\n"
    "<b>• Failed≽ </b> {failed}\n"
    "<b>• ETA≽ </b> {eta}\n\n"
    "<blockquote> [{bar}] {percent}% </blockquote>"
)
BROADCAST_COMPLETE = (
    "<blockquote> <b>✅Broadcast Complete!</b></blockquote>\n\n"
    "<b>• Sent≽ </b> {sent}\n"
    "<b>• Failed≽ </b> {failed}\n"
    "<b>• Time≽ </b> {time}\n"
    "<b>• Blocked≽ </b> {blocked} "
)
BROADCAST_CANCELLED = (
    "<blockquote>❌ <b>Broadcast Cancelled</b></blockquote>\n\n"
    "✅ <b>Sent≽ </b> {sent}\n"
    "❌ <b>Not Sent≽ </b> {remaining}"
)
BROADCAST_NO_USERS = "❌ No Users To Broadcast To."

# ─────────────────────────────────────────────────────────────────────────────
# Stats
# ─────────────────────────────────────────────────────────────────────────────
STATS_TEMPLATE = """
📊 <b>Bot Statistics</b>

<b>👥 Users</b>
Total Users: <code>{total_users}</code>
Broadcastable: <code>{broadcastable_users}</code>

<b>🔐 Membership Status</b>
Total Groups: <code>{total_groups}</code>
Active Memberships: <code>{active_memberships}</code>
Members Today: <code>{members_today}</code>
Members This Month: <code>{members_month}</code>

<b>📦 Batch Status</b>
Active Batches: <code>{active_batches}</code>
Total Batches: <code>{total_batches}</code>
Approved Requests: <code>{approved_requests}</code>
Total Media Items: <code>{total_media}</code>

<b>📤 Forwarder Status</b>
Live Forwarders: <code>{live_forwarders}</code>
Old Forward Jobs: <code>{old_forward_jobs}</code>

<b>🗜 Unzipper Status</b>
Total Processed: <code>{total_unzipped}</code>
Completed: <code>{completed_unzipped}</code>
Failed: <code>{failed_unzipped}</code>
Files Extracted: <code>{files_extracted}</code>
Data Processed: <code>{data_processed}</code>

<b>💻 Server Info</b>
CPU: <code>{cpu_count} cores ({cpu_percent}%)</code>
RAM: <code>{ram_used}/{ram_total} ({ram_percent}%)</code>
Disk: <code>{disk_used}/{disk_total}</code> (Free: <code>{disk_free}</code>)
"""
