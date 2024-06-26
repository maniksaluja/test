from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton as IKB, InlineKeyboardMarkup as IKM
from .encode_decode import decrypt, Char2Int
from config import DB_CHANNEL_ID, AUTO_DELETE_TIME, FSUB_1, FSUB_2, DB_CHANNEL_2_ID, TUTORIAL_LINK, CONTENT_SAVER, STICKER_ID
from time import time
from Database.auto_delete import update, get
from Database.privileges import get_privileges
from . import AUTO_DELETE_STR, tryer
from raw_func import getChatMember
from Database.users import add_user, is_user
from templates import AUTO_DELETE_TEXT, START_MESSAGE, START_MESSAGE_2, TRY_AGAIN_TEXT
from .block import block_dec
from Database.encr import get_encr

FSUB = [FSUB_1, FSUB_2]

me = None
chats = []

async def get_chats(_):
    global chats
    if not chats:
        chats = [await _.get_chat(FSUB_1), await _.get_chat(FSUB_2)]
        new = []
        for x in chats:
            y = await _.create_chat_invite_link(x.id, creates_join_request=True)
            new.append(y.invite_link)
        for x, y in enumerate(new):
            chats[x].invite_link = y
    return chats

async def markup(_, link=None) -> IKM:
    chats = await get_chats(_)
    l = len(FSUB)
    mark = [
        IKB('ᴍᴀɪɴ ᴄʜᴀɴɴᴇʟ', url=chats[0].invite_link),
        IKB('ʙᴀᴄᴋᴜᴘ ᴄʜᴀɴɴᴇʟ', url=chats[1].invite_link)
    ]
    mark = [mark]
    if link:
        mark.append([IKB('ᴛʀʏ ᴀɢᴀɪɴ♻️', url=link)])
    markup = IKM(mark)
    return markup

async def start_markup(_) -> IKM:
    chats = await get_chats(_)
    l = len(FSUB)
    mark = [
        IKB('ᴍᴀɪɴ ᴄʜᴀɴɴᴇʟ', url=chats[0].invite_link),
        IKB('ʙᴀᴄᴋᴜᴘ ᴄʜᴀɴɴᴇʟ', url=chats[1].invite_link)
    ]
    mark = [mark]
    mark.append([IKB('ᴜsᴇ ᴍᴇ ᴛᴜᴛᴏʀɪᴀʟ', url=TUTORIAL_LINK)])
    markup = IKM(mark)
    return markup

@Client.on_message(filters.command('start') & filters.private)
@block_dec
async def start(_, m):
    global me, chats
    if not me:
        me = await _.get_me()
    chats = await get_chats(_)
    if not await is_user(m.from_user.id):
        await add_user(m.from_user.id)
        return await m.reply(START_MESSAGE.format(m.from_user.mention), reply_markup=await start_markup(_))
    if CONTENT_SAVER:
        prem = (await get_privileges(m.from_user.id))[2]
    else:
        prem = True
    txt = m.text.split()
    okkie = None
    if len(txt) > 1:
        command = txt[1]
        if command.startswith('get'):
            encr = command[3:]
            for i in chats:
                res = getChatMember(i.id, m.from_user.id)['result']
                if res['status'] in ['left', 'banned']:
                    mark = await markup(_, f'https://t.me/{me.username}?start=get{encr}')
                    return await m.reply(TRY_AGAIN_TEXT.format(m.from_user.mention), reply_markup=mark)
            std = await m.reply_sticker(STICKER_ID)
            spl = decrypt(encr).split('|')
            try:
                msg = await _.get_messages(DB_CHANNEL_ID, Char2Int(spl[0]))
                if msg.empty:
                    msg = await _.get_messages(DB_CHANNEL_2_ID, Char2Int(spl[2]))
            except:
                msg = await _.get_messages(DB_CHANNEL_2_ID, Char2Int(spl[2]))
            await std.delete()
            if not prem:
                ok = await msg.copy(m.from_user.id, protect_content=True)
            else:
                ok = await msg.copy(m.from_user.id)
            if AUTO_DELETE_TIME != 0:
                ok1 = await ok.reply(AUTO_DELETE_TEXT.format(AUTO_DELETE_STR))
                dic = await get(m.from_user.id)
                dic[str(ok.id)] = [str(ok1.id), time(), f'https://t.me/{me.username}?start=get{encr}']
                await update(m.from_user.id, dic)
            return
        elif command.startswith('batchone'):
            encr = command[8:]
            for i in chats:
                res = getChatMember(i.id, m.from_user.id)['result']
                if res['status'] in ['left', 'banned']:
                    #txt = 'Make sure you have joined all chats below.'
                    mark = await markup(_, f'https://t.me/{me.username}?start=batchone{encr}')
                    return await m.reply(TRY_AGAIN_TEXT.format(m.from_user.mention), reply_markup=mark)
            std = await m.reply_sticker(STICKER_ID)
            spl = decrypt(encr).split('|')[0].split('-')
            st = Char2Int(spl[0])
            en = Char2Int(spl[1])
            if st == en:
                messes = [await _.get_messages(DB_CHANNEL_ID, st)]
            else:
                mess_ids = []
                while en - st + 1 > 200:
                    mess_ids.append(list(range(st, st + 200)))
                    st += 200
                if en - st + 1 > 0:
                    mess_ids.append(list(range(st, en+1)))
                messes = []
                for x in mess_ids:
                    messes += (await _.get_messages(DB_CHANNEL_ID, x))
            if not messes:
                new_encr = await get_encr(encr)
                if new_encr:
                    spl = decrypt(new_encr).split('|')[0].split('-')
                    st = Char2Int(spl[0])
                    en = Char2Int(spl[1])
                    if st == en:
                        messes = [await _.get_messages(DB_CHANNEL_2_ID, st)]
                    else:
                        mess_ids = []
                        while en - st + 1 > 200:
                            mess_ids.append(list(range(st, st + 200)))
                            st += 200
                        if en - st + 1 > 0:
                            mess_ids.append(list(range(st, en+1)))
                        messes = []
                        for x in mess_ids:
                            messes += (await _.get_messages(DB_CHANNEL_2_ID, x))
            if len(messes) > 10:
                okkie = await m.reply("**It's Take Few Seconds...**")
            haha = []
            if not prem:
                for x in messes:
                    if not x:
                        continue
                    if x.empty:
                        continue
                    gg = await tryer(x.copy, m.from_user.id, protect_content=True)
                    haha.append(gg)
            else:
                for x in messes:
                    if not x:
                        continue
                    if x.empty:
                        continue
                    gg = await tryer(x.copy, m.from_user.id)
                    haha.append(gg)
                    # tasks.append(asyncio.create_task(x.copy(m.from_user.id)))
            await std.delete()
            if AUTO_DELETE_TIME != 0:
                ok1 = await m.reply(AUTO_DELETE_TEXT.format(AUTO_DELETE_STR))
                dic = await get(m.from_user.id)
                for ok in haha:
                    if not ok:
                        continue
                    dic[str(ok.id)] = [str(ok1.id), time(), f'https://t.me/{me.username}?start=batchone{encr}']
                await update(m.from_user.id, dic)
            if okkie:
                await okkie.delete()
            return
        elif command.startswith('batchtwo'):
            encr = command[8:]
            for i in chats:
                res = getChatMember(i.id, m.from_user.id)['result']
                if res['status'] in ['left', 'banned']:
                    #txt = 'Make sure you have joined all chats below.'
                    mark = await markup(_, f'https://t.me/{me.username}?start=batchtwo{encr}')
                    return await m.reply(TRY_AGAIN_TEXT.format(m.from_user.mention), reply_markup=mark)
            std = await m.reply_sticker(STICKER_ID)
            spl = decrypt(encr).split('|')[0].split('-')
            st = Char2Int(spl[0])
            en = Char2Int(spl[1])
            if st == en:
                messes = [await _.get_messages(DB_CHANNEL_2_ID, st)]
            else:
                mess_ids = []
                while en - st + 1 > 200:
                    mess_ids.append(list(range(st, st + 200)))
                    st += 200
                if en - st + 1 > 0:
                    mess_ids.append(list(range(st, en+1)))
                messes = []
                for x in mess_ids:
                    messes += (await _.get_messages(DB_CHANNEL_2_ID, x))
            okkie = None
            if len(messes) > 10:
                okkie = await m.reply("**It's Take Few Seconds....**")
            haha = []
            if not prem:
                for x in messes:
                    if not x:
                        continue
                    if x.empty:
                        continue
                    gg = await tryer(x.copy, m.from_user.id, protect_content=True)
                    haha.append(gg)
            else:
                for x in messes:
                    if not x:
                        continue
                    if x.empty:
                        continue
                    gg = await tryer(x.copy, m.from_user.id)
                    haha.append(gg)
                    # tasks.append(asyncio.create_task(x.copy(m.from_user.id)))
            await std.delete()
            if AUTO_DELETE_TIME != 0:
                ok1 = await m.reply(AUTO_DELETE_TEXT.format(AUTO_DELETE_STR))
                dic = await get(m.from_user.id)
                for ok in haha:
                    if not ok:
                        continue
                    dic[str(ok.id)] = [str(ok1.id), time(), f'https://t.me/{me.username}?start=batchtwo{encr}']
                await update(m.from_user.id, dic)
            if okkie:
                await okkie.delete()
            return
    else:
        await m.reply(START_MESSAGE_2.format(m.from_user.mention), reply_markup=await start_markup(_))