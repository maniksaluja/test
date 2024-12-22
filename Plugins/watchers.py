import asyncio

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton as IKB
from pyrogram.types import InlineKeyboardMarkup as IKM
from pyrogram.types import Message

import Plugins
from config import (AUTO_SAVE_CHANNEL, DB_CHANNEL_2_ID, DB_CHANNEL_ID, FSUB_1,
                    LINK_GENERATE_IMAGE, SUDO_USERS, USELESS_IMAGE)
from Database.count import incr_count
from Database.settings import get_settings
from main import app, app1
from templates import LINK_GEN, USELESS_MESSAGE

from . import ADMIN_REPLY_BACK, alpha_grt, get_logs_channel, tryer
from .batch import batch_cwf as bcwf
from .batch import in_batch
from .block import block_dec
from .connect import in_work
from .encode_decode import Int2Char, encrypt
from .get import get
from .listner import is_media_group
from .start import start_markup as build

watch = 1

me = None
async def get_me(_):
    global me
    if not me:
        me = await _.get_me()
    return me



@Client.on_message(filters.private & filters.incoming, group=watch)
@block_dec
async def cwf(_: Client, m: Message):
    if await is_media_group(m):
        return
    if in_work(m.from_user.id):
        return
    if in_batch(m.from_user.id):
        return await bcwf(_, m)
    if m.text and m.text.startswith("https://t.me/"):
        ret = await get(_, m)
        if ret:
            return
    if not m.from_user.id in SUDO_USERS:
        if m.text:
            if not m.command:
                markup = await build(_, True)
                if USELESS_IMAGE:
                    await m.reply_photo(USELESS_IMAGE, caption=USELESS_MESSAGE, reply_markup=markup)
                else:
                    await m.reply(USELESS_MESSAGE, reply_markup=markup)
        else:
            markup = await build(_, True)
            if USELESS_IMAGE:
                await m.reply_photo(USELESS_IMAGE, caption=USELESS_MESSAGE, reply_markup=markup)
            else:
                await m.reply(USELESS_MESSAGE, reply_markup=markup)
        return
    if m.text and m.text.startswith('/'):
        return
    settings = await get_settings()
    """
    if LINK_GENERATE_IMAGE and settings['image']:
        try:
            msg = await m.reply_photo(LINK_GENERATE_IMAGE, caption='**Generating Link...**', quote=True)
        except FloodWait as e:
            await asyncio.sleep(e.value)
            msg = await m.reply_photo(LINK_GENERATE_IMAGE, caption='**Generating Link...**', quote=True)
    else:
        try:
            msg = await m.reply('**Generating Link...**', quote=True)
        except FloodWait as e:
            await asyncio.sleep(e.value)
            msg = await m.reply('**Generating Link...**', quote=True)
    """
    count = await incr_count()
    if m.text:
        m.text += f"#EP{count}"
    res = await asyncio.gather(
        tryer(m.copy, DB_CHANNEL_ID, caption=f"#EP{count}"),
        tryer(m.copy, DB_CHANNEL_2_ID, caption=f"#EP{count}")
    )
    encr = encrypt(f'{Int2Char(res[0].id)}|{Int2Char(count)}|{Int2Char(res[1].id)}')
    link = f'https://t.me/{(await get_me(_)).username}?start=get{encr}'
    if m.video:
        dur = "â‹žâ‹®â‹Ÿ " + alpha_grt(m.video.duration)
    else:
        dur = ''
    txt = LINK_GEN.format(str(count), dur, link)
    markup = IKM([[IKB('Share', url=link)]])
    if LINK_GENERATE_IMAGE and settings['image']:
        msg = await tryer(m.reply_photo, LINK_GENERATE_IMAGE, caption=txt, quote=True)
    else:
        msg = await tryer(m.reply, txt, quote=True)

    if channels := await get_logs_channel():
        for channel in channels:
            if not channel:
                 continue
            await tryer(msg.copy, channel)


@Client.on_message(filters.chat(FSUB_1))
async def reactionnn(c: Client, m: Message):
    try:
        await app.send_reaction(m.chat.id, m.id, "ðŸ‘")
    except Exception as e:
        print(f"Got error while giving reaction: {e}")
    try:
        await app1.send_reaction(m.chat.id, m.id, "ðŸ‘Ž")
    except Exception as e:
        print(f"Got error while giving reaction: {e}")

    if AUTO_SAVE_CHANNEL:
        if not (await get_settings()).get('forwarding', True):
            return
        if m.media_group_id:
            await c.forward_media_group(AUTO_SAVE_CHANNEL, m.chat.id, m.id)
        else:
            await m.forward(AUTO_SAVE_CHANNEL)
    return

@Client.on_message(filters.chat([DB_CHANNEL_2_ID, DB_CHANNEL_ID]))
async def add_counter_in_caption(_, m: Message):
    cur = await incr_count()

    if m.forward_from_chat or m.forward_from:
        return #can't update forwarded messages
    if m.text:
        txt = f"{m.text}\n#EP{cur}"
        await m.edit_text(txt)
    else:
        cap = f"{m.caption}\n#EP{cur}" if m.caption else f"#EP{cur}"
        await m.edit_caption(cap)
