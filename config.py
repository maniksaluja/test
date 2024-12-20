from os import getenv

# Ensure FSUB_1 and FSUB_2 are defined
FSUB_1 = int(getenv('FSUB_1', '-1002250888713'))
FSUB_2 = int(getenv('FSUB_2', '-1002319501979'))

# Now define FSUB using FSUB_1 and FSUB_2
FSUB = [FSUB_1, FSUB_2]

# Load other values from environment variables
API_ID = int(getenv('API_ID', '26980824'))
API_HASH = getenv('API_HASH', 'fb044056059384d3bea54ab7ce915226')

# Add separate API ID and API Hash for both bots
API_ID2 = int(getenv('API_ID_BOT1', '3510496'))  # Bot2 API ID
API_HASH2 = getenv('API_HASH_BOT1', 'c65647776bb4e93defc9504571d2b990')  # Bot2 API Hash

BOT_TOKEN = getenv('BOT_TOKEN', '6944717193:AAG-4r2ffAWkGte2tzmWTJjiqGiZYMxcXwU')
BOT_TOKEN_2 = getenv('BOT_TOKEN_2', '7208277760:AAGKBNndrcUIjl596wgcpi9SKfiiCOROy8Q')

SUDO_USERS = [int(x) for x in getenv('SUDO_USERS', '6604279354 6104594076').split()]
MONGO_DB_URI = getenv('MONGO_DB_URI', 'mongodb+srv://manik:manik11@cluster0.iam3w.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0')

DB_CHANNEL_ID = int(getenv('DB_CHANNEL_ID', '-1002426471203'))
DB_CHANNEL_2_ID = int(getenv('DB_CHANNEL_2_ID', '-1002465577510'))
LOG_CHANNEL_ID = int(getenv('LOG_CHANNEL_ID', '-1002462410192')) if getenv('LOG_CHANNEL_ID') else None

AUTO_DELETE_TIME = int(getenv('AUTO_DELETE_TIME', '0'))  # Enter time in seconds, keep it 0 for disabling.

MUST_VISIT_LINK = "https://t.me/Ultra_XYZ/14"

LINK_GENERATE_IMAGE = getenv('LINK_GENERATE_IMAGE', 'https://graph.org/file/a1cce5b8533180c2f0029.jpg')

TUTORIAL_LINK = getenv('TUTORIAL_LINK', 'https://t.me/Ultra_XYZ/16')

CONNECT_TUTORIAL_LINK = getenv('CONNECT_TUTORIAL_LINK', 'https://t.me/Terabox_Sharing_Bot?start=batchoneaWZkYS1pZmRjfGhoZg==')
SU_IMAGE = "https://graph.org/file/2342d37844afd1b9b96c0.jpg"

JOIN_MESSAGE = getenv('JOIN_MESSAGE', 'You Joined.')
JOIN_IMAGE = getenv('JOIN_IMAGE', 'https://graph.org/file/015fddf0dbeb03b639647.jpg')

LEAVE_CAPTION = getenv('LEAVE_CAPTION', 'I Love You.')

USELESS_MESSAGE = getenv('USELESS_MESSAGE', 'This is useless text.')
USELESS_IMAGE = getenv('USELESS_IMAGE', 'https://graph.org/file/c579032c65d8353e43b0f.jpg')

STICKER_ID = 'CAACAgUAAxkBAAIiHWZjPezFGPWT_87VHnJUaschvGtrAAJtDgACYpoYV06rLlLA8dv_HgQ'

CONTENT_SAVER = True

EXPIRY_TIME = 30  # In days

AUTO_SAVE_CHANNEL_ID = -1002425448719

PHONE_NUMBER_IMAGE = "https://graph.org/file/2821554b6b082eb8741dc.jpg"

WARN_IMAGE = 'https://graph.org/file/c86c68e014e471c1ce729.jpg'
