import datetime
import json
import os
import subprocess
import sys
import textwrap
import time
import logging
import random
import asyncio
from typing import Optional, Any

from bot import Bot
from Script import script
from pyrogram import Client, filters, enums
from pyrogram.raw.functions import messages as rmsg
from database.batch_db import get_batch
from pyrogram.errors.exceptions.bad_request_400 import ChatAdminRequired
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from database.ia_filterdb import Media, get_file_details, unpack_new_file_id
from database.restart_db import start_restart_stage
from database.users_chats_db import db
from info import CHANNELS, ADMINS, AUTH_CHANNEL, CUSTOM_FILE_CAPTION, LOG_CHANNEL, PICS, HELPABLE, FILE_PROTECT
from plugins.broadcast import send_broadcast_message
from plugins.misc import paginate_modules
from database.settings_db import sett_db
from database.connections_mdb import active_connection, all_connections
from utils import get_size, is_subscribed, temp, split_quotes, get_msg_type, build_keyboard_cb_url
import re

logger = logging.getLogger(__name__)
BATCH_FILES = {}


@Client.on_message(filters.command("start") & filters.incoming)    # & ~filters.edited
async def start(client, message):
    if message.chat.type.name in ['GROUP', 'SUPERGROUP']:
        if message.from_user.id in ADMINS:
            buttons = [
                [
                    InlineKeyboardButton('🤖 Updates', url='https://t.me/TeamEvamaria')
                ],
                [
                    InlineKeyboardButton('ℹ️ Help', url=f"https://t.me/{temp.U_NAME}?start=help"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(buttons)
            await message.reply(
                script.START_TXT.format(message.from_user.mention if message.from_user else message.chat.title,
                                        temp.U_NAME,
                                        temp.B_NAME), reply_markup=reply_markup)
            await asyncio.sleep(2)
            # 😢 https://github.com/EvamariaTG/EvaMaria/blob/master/plugins/p_ttishow.py#L17 😬 wait a bit, before checking.
            if not await db.get_chat(message.chat.id):
                total = await client.get_chat_members_count(message.chat.id)
                await client.send_message(LOG_CHANNEL,
                                          script.LOG_TEXT_G.format(message.chat.title, message.chat.id, total,
                                                                   "Unknown"))
                await db.add_chat(message.chat.id, message.chat.title)
            return
        else:
            btn = [[
                InlineKeyboardButton("⭕️ᴘᴍ ᴍᴇ ⭕️", url="https://t.me/testufsbot")
            ]]
            message.reply("Goto My PM, Then Click Start.. Here You Are Restricted By Admins...", reply_markup=btn)
            return
    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(message.from_user.id, message.from_user.first_name)
        await client.send_message(LOG_CHANNEL,
                                  script.LOG_TEXT_P.format(message.from_user.id, message.from_user.mention))
    if len(message.command) != 2:
        buttons = [[
            InlineKeyboardButton('🔍 Search', switch_inline_query_current_chat=''),
            InlineKeyboardButton('🤖 Updates', url='https://t.me/EvaMariaUpdates')
        ], [
            InlineKeyboardButton('ℹ️Help', callback_data='help'),
            InlineKeyboardButton('😊 About', callback_data='about')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await message.reply_photo(
            photo=random.choice(PICS),
            caption=script.START_TXT.format(message.from_user.mention, temp.U_NAME, temp.B_NAME),
            reply_markup=reply_markup
        )
        return
    if AUTH_CHANNEL and not await is_subscribed(client, message):
        try:
            invite_link = await client.create_chat_invite_link(int(AUTH_CHANNEL))
        except ChatAdminRequired:
            logger.error("Make sure Bot is admin in Forcesub Channel")
            return

        btn = []
        btn.append(["🤖 Join Here", invite_link.invite_link, False, 'url'])
        btn = [
            [
                InlineKeyboardButton(
                    "🤖 Join Here", url=invite_link.invite_link
                )
            ]
        ]

        if message.command[1] != "subscribe":
            btn.append(["🔄 Try Again", f"checksub#{message.command[1]}", True, 'cb'])
            # btn.append([InlineKeyboardButton(" 🔄 Try Again", callback_data=f"checksub#{message.command[1]}")])
        btn = build_keyboard_cb_url(btn)
        await client.send_message(
            chat_id=message.from_user.id,
            text="**Please Join Below Channel And Click On Try Again Button!**",
            reply_markup=InlineKeyboardMarkup(btn)
        )
        return
    if len(message.command) == 2 and message.command[1] in ["subscribe", "error", "okay", "help"]:
        buttons = [[
            InlineKeyboardButton('🔍 Search', switch_inline_query_current_chat=''),
            InlineKeyboardButton('🤖 Updates', url='https://t.me/TeamEvamaria')
        ], [
            InlineKeyboardButton('ℹ️Help', callback_data='help'),
            InlineKeyboardButton('😊 About', callback_data='about')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await message.reply_photo(
            photo=random.choice(PICS),
            caption=script.START_TXT.format(message.from_user.mention, temp.U_NAME, temp.B_NAME),
            reply_markup=reply_markup
        )
        return

    file_id = message.command[1]
    unique_id, f_id, file_ref, caption = await get_batch(file_id)

    settings = None
    if FILE_PROTECT.get(message.from_user.id):
        grpid = FILE_PROTECT.get(message.from_user.id)
        settings = await sett_db.get_settings(str(grpid))
        del FILE_PROTECT[message.from_user.id]
    FILE_PROTECT[message.from_user.id] = str(message.chat.id)

    if not settings:
        FILE_SECURE = False
    else:
        FILE_SECURE = settings["file_secure"]
    files_ = await get_file_details(file_id)
    if not files_:
        sts = await message.reply("`⏳ Please Wait...`")
        msgs = BATCH_FILES.get(file_id)
        if not msgs:
            file = await client.download_media(file_id)
            try:
                with open(file) as file_data:
                    msgs = json.loads(file_data.read())
            except:
                await sts.edit("FAILED")
                return await client.send_message(LOG_CHANNEL, "UNABLE TO OPEN FILE.")
            os.remove(file)
            BATCH_FILES[file_id] = msgs
        await asyncio.sleep(1)
        await sts.delete()
        for msg in msgs:
            title = msg.get("title")
            size = get_size(int(msg.get("size", 0)))
            f_caption = msg.get("caption", "")
            file_type = msg.get("file_type")
            entities = msg.get("entities")

            if f_caption is None:
                f_caption = f"{title}"
            f_sub_caption = f"<code>💾 Size: {size}</code>\n\n🌟༺ ──•◈•─ ─•◈•──༻🌟\n<b>➧ പുതിയ സിനിമകൾ / വെബ്‌ സീരീസ് " \
                    f"വേണോ? എന്നാൽ പെട്ടെന്ന് ഗ്രൂപ്പിൽ ജോയിൻ ആയിക്കോ\n\n🔊 Gʀᴏᴜᴘ: " \
                    f"@UniversalFilmStudio \n🔊 Gʀᴏᴜᴘ: @UniversalFilmStudioo \n🔊 " \
                    f"Cʜᴀɴɴᴇʟ: <a href='https://t.me/+uuLR9YwyRjg0ODQ0'>Nᴇᴡ Oᴛᴛ Mᴏᴠɪᴇs</a> \n\n🎗️ʝσιи 🎗️ ѕнαяє🎗️ ѕυρρσят🎗️ </b>"

            f_caption + f"\n\n<code>┈•••✿ @UniversalFilmStudio ✿•••┈\n\n💾 Size: {size}</code>"
            try:
                if file_type not in ["video", 'audio', 'document']:
                    await client.send_cached_media(
                        chat_id=message.from_user.id,
                        file_id=msg.get("file_id"),
                        caption=f_caption,
                        protect_content=FILE_SECURE,
                        caption_entities=entities,
                    )
                else:
                    buttons = [[
                        InlineKeyboardButton('🎭 Nᴇᴡ Uᴘᴅᴀᴛᴇs', url="https://t.me/UFSFilmUpdate"),
                        InlineKeyboardButton('🎭 ᴍᴏᴠɪᴇs', url="https://t.me/UniversalFilmStudio")
                    ], [
                        InlineKeyboardButton('⚜ Nᴇᴡ Oᴛᴛ Mᴏᴠɪᴇs ⚜', url='https://t.me/+uuLR9YwyRjg0ODQ0')
                    ]]
                    reply_markup = InlineKeyboardMarkup(buttons)

                    await client.send_cached_media(
                        chat_id=message.from_user.id,
                        file_id=msg.get("file_id"),
                        caption=f_caption + f"\n\n{f_sub_caption}",
                        protect_content=FILE_SECURE,
                        reply_markup=reply_markup
                        InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        '🎭 Nᴇᴡ \nUᴘᴅᴀᴛᴇs', url="https://t.me/UFSFilmUpdate"
                                    ),
                                    InlineKeyboardButton(
                                        '🎭 ᴍᴏᴠɪᴇs', url="https://t.me/UniversalFilmStudio"
                                    )
                                ],
                                [
                                    InlineKeyboardButton(
                                        '⭕️ ᴘᴍ ᴍᴇ ⭕️', url="https://t.me/UFSChatBot"
                                    )
                                ]
                            ]
                        )
                    )
            except Exception as err:
                await sts.edit("FAILED")
                return await client.send_message(LOG_CHANNEL, f"{str(err)}")
            await asyncio.sleep(0.5)
        return await message.reply(f"<b><a href='https://t.me/UniversalFilmStudio'>Thank For Using Me...</a></b>")

    if unique_id:
        temp_msg = await message.reply("Please wait...")
        file_args = f_id.split("#")
        cap_args = caption.split("#")
        i = 0
        await asyncio.sleep(2)
        await temp_msg.delete()
        for b_file in file_args:
            f_caption = cap_args[i]
            if f_caption is None:
                f_caption = ""
            f_caption = f_caption + f"\n\n<code>┈•••✿</code> @UniversalFilmStudio <code>✿•••┈</code>"
            i += 1
            try:
                await client.send_cached_media(
                    chat_id=message.from_user.id,
                    file_id=b_file,
                    caption=f_caption,
                    parse_mode="html",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    '🎭 ⭕️ ᴄᴏɴᴛᴀᴄᴛ ᴍᴇ ⭕️', url="https://t.me/UFSChatBot"
                                )
                            ]
                        ]
                    )
                )
            except Exception as err:
                return await message.reply(f"{str(err)}")
            await asyncio.sleep(1)
   
        return await message.reply(f"<b><a href='https://t.me/UniversalFilmStudio'>Thank For Using Me...</a></b>")

    files_ = await get_file_details(file_id)
    if not files_:
        return await message.reply('No such file exist.')
    files = files_[0]
    title = files.file_name
    size = get_size(files.file_size)
    f_caption = files.caption
    if CUSTOM_FILE_CAPTION:
        try:
            f_caption = CUSTOM_FILE_CAPTION.format(file_name=title, file_size=size, file_caption=f_caption)
        except Exception as e:
            logger.exception(e)
            f_caption = f_caption
    if f_caption is None:
        f_caption = f"{files.file_name}"
    f_sub_caption = f"<code>💾 Size: {size}</code>\n\n🌟༺ ──•◈•─ ─•◈•──༻🌟\n<b>➧ പുതിയ സിനിമകൾ / വെബ്‌ സീരീസ് " \
                    f"വേണോ? എന്നാൽ പെട്ടെന്ന് ഗ്രൂപ്പിൽ ജോയിൻ ആയിക്കോ\n\n🔊 Gʀᴏᴜᴘ: " \
                    f"@UniversalFilmStudio \n🔊 Gʀᴏᴜᴘ: @UniversalFilmStudioo \n🔊 " \
                    f"Cʜᴀɴɴᴇʟ: <a href='https://t.me/+uuLR9YwyRjg0ODQ0'>Nᴇᴡ Oᴛᴛ Mᴏᴠɪᴇs</a> \n\n🎗️ʝσιи 🎗️ ѕнαяє🎗️ ѕυρρσят🎗️ </b>"

    f_caption = f_caption + f"\n\n{f_sub_caption}"
    try:
        buttons = [[
            InlineKeyboardButton('🎭 Nᴇᴡ Uᴘᴅᴀᴛᴇs', url="https://t.me/UFSFilmUpdate"),
            InlineKeyboardButton('🎭 ᴍᴏᴠɪᴇs', url="https://t.me/UniversalFilmStudio")
        ], [
            InlineKeyboardButton('⚜ Nᴇᴡ Oᴛᴛ Mᴏᴠɪᴇs ⚜', url='https://t.me/+uuLR9YwyRjg0ODQ0')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await client.send_cached_media(
            chat_id=message.from_user.id,
            file_id=file_id,
            caption=f_caption,
            protect_content=FILE_SECURE,
            reply_markup=reply_markup
            InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            '🎭 Nᴇᴡ Uᴘᴅᴀᴛᴇs', url="https://t.me/UFSFilmUpdate"
                        ),
                        InlineKeyboardButton(
                            '🎭 ᴍᴏᴠɪᴇs', url="https://t.me/UniversalFilmStudio"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            '⭕️ ᴘᴍ ᴍᴇ ⭕️', url="https://t.me/UFSChatBot"
                        )
                    ]
                ]
            )
        )
    except Exception as e:
        return await message.reply(e)


@Client.on_message(filters.command("help"))
async def help(client, message):
    first_name = message.from_user.first_name
    chat = message.chat.id  # type: Optional[Chat]
    args = message.text.split(None, 1)

    # ONLY send help in PM
    if chat.type != chat.PRIVATE:

        message.reply_text("Contact Me In PM To Get The List Of Possible Commands.",
                           reply_markup=InlineKeyboardMarkup(
                               [[InlineKeyboardButton(text="Help",
                                                      url="t.me/{}?start=help".format(
                                                          temp.U_NAME))]]))
        return

    elif len(args) >= 2 and any(args[1].lower() == x for x in HELPABLE):
        module = args[1].lower()
        text = "Here Is The Available Help For The **{}** Module:\n".format(HELPABLE[module].__mod_name__) \
               + HELPABLE[module].__help__
        send_help(client, chat.id, text,
                  InlineKeyboardMarkup([[InlineKeyboardButton(text="Back", callback_data="help_back")]]))

    else:
        send_help(client, chat.id, script.HELP_STRINGS.format(first_name, "@lnc3f3r"))


@Client.on_message(filters.command('channel') & filters.user(ADMINS))
async def channel_info(bot, message):
    """Send basic information of channel"""
    if isinstance(CHANNELS, (int, str)):
        channels = [CHANNELS]
    elif isinstance(CHANNELS, list):
        channels = CHANNELS
    else:
        raise ValueError("Unexpected type of CHANNELS")

    text = '📑 **Indexed channels/groups**\n'
    for channel in channels:
        chat = await bot.get_chat(channel)
        if chat.username:
            text += '\n@' + chat.username
        else:
            text += '\n' + chat.title or chat.first_name

    text += f'\n\n**Total:** {len(CHANNELS)}'

    if len(text) < 4096:
        await message.reply(text)
    else:
        file = 'Indexed channels.txt'
        with open(file, 'w') as f:
            f.write(text)
        await message.reply_document(file)
        os.remove(file)


@Client.on_message(filters.command('logs') & filters.user(ADMINS))
async def log_file(bot, message):
    """Send log file"""
    try:
        await message.reply_document('TelegramBot.log')
    except Exception as e:
        await message.reply(str(e))


@Client.on_message(filters.command('delete') & filters.user(ADMINS))
async def delete(bot, message):
    """Delete file from database"""
    reply = message.reply_to_message
    if reply and reply.media:
        msg = await message.reply("Processing...⏳", quote=True)
    else:
        await message.reply('Reply to file with /delete which you want to delete', quote=True)
        return

    for file_type in ("document", "video", "audio"):
        media = getattr(reply, file_type, None)
        if media is not None:
            break
    else:
        await msg.edit('This Is Not Supported File Format')
        await asyncio.sleep(2)
        await msg.delete()
        await message.delete()
        return

    file_id, file_ref = unpack_new_file_id(media.file_id)

    result = await Media.collection.delete_one({
        '_id': file_id,
    })
    if result.deleted_count:
        await msg.edit('File Is Successfully Deleted From Database')
        await asyncio.sleep(2)
        await msg.delete()
        await reply.delete()
        await message.delete()
    else:
        file_name = re.sub(r"(_|\-|\.|\+)", " ", str(media.file_name))
        result = await Media.collection.delete_one({
            'file_name': file_name,
            'file_size': media.file_size,
            'mime_type': media.mime_type
        })
        if result.deleted_count:
            await msg.edit('File Is Successfully Deleted From Database')
            await asyncio.sleep(2)
            await msg.delete()
            await reply.delete()
            await message.delete()
        else:
            # files indexed before https://github.com/EvamariaTG/EvaMaria/commit/f3d2a1bcb155faf44178e5d7a685a1b533e714bf#diff-86b613edf1748372103e94cacff3b578b36b698ef9c16817bb98fe9ef22fb669R39 
            # have original file name.
            result = await Media.collection.delete_one({
                'file_name': media.file_name,
                'file_size': media.file_size,
                'mime_type': media.mime_type
            })
            if result.deleted_count:
                await msg.edit('File Is Successfully Deleted From Database')
                await asyncio.sleep(2)
                await msg.delete()
                await reply.delete()
                await message.delete()
            else:
                await msg.edit('File Not Found In Database')
                await asyncio.sleep(2)
                await msg.delete()
                await message.delete()


@Client.on_message(filters.command('deleteall') & filters.user(ADMINS))
async def delete_all_index(bot, message):
    await message.reply_text(
        'This will delete all indexed files.\nDo you want to continue??',
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="YES", callback_data="autofilter_delete"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="CANCEL", callback_data="close_data"
                    )
                ],
            ]
        ),
        quote=True,
    )


@Client.on_callback_query(filters.regex(r'^autofilter_delete'))
async def delete_all_index_confirm(bot, message):
    await Media.collection.drop()
    await message.answer()
    await message.message.edit('Successfully Deleted All The Indexed Files.')


# Update

@Client.on_message(filters.command("update") & filters.user(ADMINS))
async def update_restart(bot, message):
    try:
        out = subprocess.check_output(["git", "pull"]).decode("UTF-8")
        if "Already up to date." in str(out):
            return await message.reply_text("Its Already Up-To Date!")
        await message.reply_text(f"```{out}```")
    except Exception as e:
        return await message.reply_text(str(e))
    m = await message.reply_text(
        "**Updated With Default Branch, Restarting Now.**")
    await restart(m)


# Update

# @Client.on_message(filters.command('update') & filters.user(ADMINS))
# async def upstream_repo(bot, message):
#     try:
#         out = subprocess.check_output(["git", "pull"]).decode("UTF-8")
#         if "Already up to date." in str(out):
#             return await message.reply_text("Its already up-to date!")
#         await message.reply_text(f"```{out}```")
#     except Exception as e:
#         return await message.reply_text(str(e))
#     m = await message.reply_text(
#         "**Updated with default branch, restarting now.**")
#     os.execvp(sys.executable, [sys.executable, "main.py"])


@Bot.on_message(filters.command("bat"))
async def start111(client: Client, message):
    try:
        answer = await client.ask(message.chat.id, '*Send me your name:*')
        await client.send_message(message.chat.id, f'Your name is: ')
    except Exception as err:
        await client.send_message(message.chat.id, f'Error is: {str(err)}')


async def restart(message):
    if message:
        await start_restart_stage(message.chat.id, message.id)
    os.execvp(sys.executable, [sys.executable, "main.py"])


def send_help(client, chat_id, text, keyboard=None):
    if not keyboard:
        keyboard = InlineKeyboardMarkup(paginate_modules(0, HELPABLE, "help"))
    client.send_message(chat_id=chat_id,
                        text=text,
                        reply_markup=keyboard)


@Client.on_message(filters.command('settings') & filters.private)
async def settings(client, message):
    try:
        userid = message.from_user.id if message.from_user else None
        if not userid:
            return await message.reply(f"You are anonymous admin. Use /connect {message.chat.id} in PM")
        chat_type = message.chat.type
        args = message.text.html.split(None, 1)

        if chat_type == enums.ChatType.PRIVATE:
            grpid = await active_connection(str(userid))
            if grpid is not None:
                grp_id = grpid
                try:
                    chat = await client.get_chat(grpid)
                    title = chat.title
                except:
                    await message.reply_text("Make sure I'm present in your group!!", quote=True)
                    return
            else:
                await message.reply_text("I'm not connected to any groups!", quote=True)
                return

        elif chat_type.name in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            grp_id = message.chat.id
            title = message.chat.title

        else:
            return

        st = await client.get_chat_member(grp_id, userid)
        if (
                st.status != enums.ChatMemberStatus.ADMINISTRATOR
                and st.status != enums.ChatMemberStatus.OWNER
                and str(userid) not in ADMINS
        ):
            return

        if not await sett_db.is_settings_exist(str(grp_id)):
            await sett_db.add_settings(str(grp_id), True, 120)

        settings = await sett_db.get_settings(str(grp_id))

        if settings is not None:
            buttons = [
                [
                    InlineKeyboardButton('Fɪʟᴛᴇʀ Bᴜᴛᴛᴏɴ',
                                         callback_data=f'setgs#button#{settings["button"]}#{str(grp_id)}#{settings["delete_time"]}'),
                    InlineKeyboardButton('Sɪɴɢʟᴇ' if settings["button"] else 'Dᴏᴜʙʟᴇ',
                                         callback_data=f'setgs#button#{settings["button"]}#{str(grp_id)}#{settings["delete_time"]}')
                ],
                [
                    InlineKeyboardButton('Bᴏᴛ PM',
                                         callback_data=f'setgs#botpm#{settings["botpm"]}#{str(grp_id)}#{settings["delete_time"]}'),
                    InlineKeyboardButton('✅ Yᴇs' if settings["botpm"] else '❌ Nᴏ',
                                         callback_data=f'setgs#botpm#{settings["botpm"]}#{str(grp_id)}#{settings["delete_time"]}')
                ],
                [
                    InlineKeyboardButton('Fɪʟᴇ Sᴇᴄᴜʀᴇ',
                                         callback_data=f'setgs#file_secure#{settings["file_secure"]}#{str(grp_id)}#{settings["delete_time"]}'),
                    InlineKeyboardButton('✅ Yᴇs' if settings["file_secure"] else '❌ Nᴏ',
                                         callback_data=f'setgs#file_secure#{settings["file_secure"]}#{str(grp_id)}#{settings["delete_time"]}')
                ],
                [
                    InlineKeyboardButton('Iᴍᴅʙ',
                                         callback_data=f'setgs#imdb#{settings["imdb"]}#{str(grp_id)}#{settings["delete_time"]}'),
                    InlineKeyboardButton('✅ Yᴇs' if settings["imdb"] else '❌ Nᴏ',
                                         callback_data=f'setgs#imdb#{settings["imdb"]}#{str(grp_id)}#{settings["delete_time"]}')
                ],
                [
                    InlineKeyboardButton('Sᴘᴇʟʟ Cʜᴇᴄᴋ',
                                         callback_data=f'setgs#spell_check#{settings["spell_check"]}#{str(grp_id)}#{settings["delete_time"]}'),
                    InlineKeyboardButton('✅ Yᴇs' if settings["spell_check"] else '❌ Nᴏ',
                                         callback_data=f'setgs#spell_check#{settings["spell_check"]}#{str(grp_id)}#{settings["delete_time"]}')
                ],
                [
                    InlineKeyboardButton('Aᴜᴛᴏ Dᴇʟᴇᴛᴇ',
                                         callback_data=f'setgs#delete#{settings["auto_delete"]}#{str(grp_id)}#{settings["delete_time"]}'),
                    InlineKeyboardButton(f'{settings["delete_time"]} Sᴇᴄ' if settings["auto_delete"] else '❌ Nᴏ',
                                         callback_data=f'setgs#delete#{settings["auto_delete"]}#{str(grp_id)}#{settings["delete_time"]}')
                ],
                [
                    InlineKeyboardButton('Wᴇʟᴄᴏᴍᴇ',
                                         callback_data=f'setgs#welcome#{settings["welcome"]}#{str(grp_id)}#{settings["delete_time"]}'),
                    InlineKeyboardButton('✅ Yᴇs' if settings["welcome"] else '❌ Nᴏ',
                                         callback_data=f'setgs#welcome#{settings["welcome"]}#{str(grp_id)}#{settings["delete_time"]}')
                ]
            ]
            reply_markup = InlineKeyboardMarkup(buttons)

            await message.reply_text(
                text=f"<b>Change Your Filter Settings As Your Wish ⚙\n\nThis Settings For Group</b> <code>{title}</code>",
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                reply_to_message_id=message.id
            )
    except Exception as e:
        await message.reply_text(str(e))
        return


@Client.on_message(filters.command('gbroadcast') & filters.private)
async def g_broadcast(client, message):
    try:
        userid: Optional[Any] = message.from_user.id if message.from_user else None
        if not userid:
            return await message.reply(f"You are anonymous admin. Use /connect {message.chat.id} in PM")
        chat_type = message.chat.type

        if chat_type == enums.ChatType.PRIVATE:
            grpid = await active_connection(str(userid))
            if grpid is not None:
                grp_id = grpid
                try:
                    chat = await client.get_chat(grpid)
                    title = chat.title
                except:
                    await message.reply_text("Make sure I'm present in your group!!", quote=True)
                    return
            else:
                await message.reply_text("I'm not connected to any groups!", quote=True)
                return

        elif chat_type.name in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            grp_id = message.chat.id
            title = message.chat.title

        else:
            return

        st = await client.get_chat_member(grp_id, userid)
        if (
                st.status != enums.ChatMemberStatus.ADMINISTRATOR
                and st.status != enums.ChatMemberStatus.OWNER
                and str(userid) not in ADMINS
        ):
            return

        msg = await message.reply('Getting List Of Chats..', quote=True)
        await asyncio.sleep(1)

        b_msg = message.reply_to_message

        start_time = time.time()
        await msg.edit_text(
            text='Please Wait, Broadcasting To Connected Chat Is Starting Soon...')
        await asyncio.sleep(1)

        userid = message.from_user.id
        groupids = await all_connections(str(userid))

        if groupids is None:
            await msg.edit_text(
                "There Are No Active Connections!! Connect To Some Groups First.")
            return

        i = 0
        done = 0
        success = 0
        totl_chats = len(groupids)
        try:
            for groupid in groupids:
                try:
                    text, data_type, content, buttons = get_msg_type(b_msg)
                    i += 1
                    ttl = await client.get_chat(str(groupid))
                    title = ttl.title
                    await msg.edit_text(f"**Broadcast Successfully Completed** `{title}: {i}/{totl_chats}`")
                    success += 1
                    await send_broadcast_message(groupid, text, data_type, content, buttons, client, message)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    await message.reply(str(e))
                    pass
        except Exception as e:
            await message.reply(str(e))
            return

        time_taken = datetime.timedelta(seconds=int(time.time() - start_time))
        await msg.edit_text(
            f"**Broadcast Completed:**\n**Completed in** `{time_taken} seconds.`\n\n**Total Chats** `{totl_chats}`\n"
            f"**Completed:** `{done} / {totl_chats}`\n**Success:** `{success}`")
    except Exception as e:
        await message.reply_text(f"{str(e)}")
        return


@Client.on_message(filters.command('gpbroadcast') & filters.private & filters.user(ADMINS))
async def gp_broadcast(client, message):
    try:
        userid: Optional[Any] = message.from_user.id if message.from_user else None
        if not userid:
            return await message.reply(f"You are anonymous admin. Use /connect {message.chat.id} in PM")
        chat_type = message.chat.type

        if chat_type == enums.ChatType.PRIVATE:
            grpid = await active_connection(str(userid))
            if grpid is not None:
                grp_id = grpid
                try:
                    chat = await client.get_chat(grpid)
                    title = chat.title
                except:
                    await message.reply_text("Make sure I'm present in your group!!", quote=True)
                    return
            else:
                await message.reply_text("I'm not connected to any groups!", quote=True)
                return

        elif chat_type.name in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            grp_id = message.chat.id
            title = message.chat.title

        else:
            return

        st = await client.get_chat_member(grp_id, userid)
        if (
                st.status != enums.ChatMemberStatus.ADMINISTRATOR
                and st.status != enums.ChatMemberStatus.OWNER
                and str(userid) not in ADMINS
        ):
            return

        msg = await message.reply('`Getting List Of Chats..`', quote=True)
        await asyncio.sleep(1)

        b_msg = message.reply_to_message

        start_time = time.time()
        await msg.edit_text(
            text='`Please Wait, Broadcasting To Connected Chat Is Starting Soon...`')
        await asyncio.sleep(1)

        userid = message.from_user.id
        chats = await db.get_all_chats()

        if chats is None:
            await msg.edit_text(
                "There Are No Groups!! Add To Some Groups First.")
            return

        i = 0
        done = 0
        success = 0
        # totl_chats = len(chats)
        try:
            async for chat in chats:
                try:
                    text, data_type, content, buttons = get_msg_type(b_msg)
                    i += 1
                    ttl = await client.get_chat(chat['id'])
                    title = ttl.title
                    await msg.edit_text(f"**Broadcast Successfully Completed** `{title}: {i}`")
                    success += 1
                    await send_broadcast_message(chat['id'], text, data_type, content, buttons, client, message)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    d_msg = await message.reply(str(e))
                    await asyncio.sleep(2)
                    await d_msg.delete()
                    pass
        except Exception as e:
            d_msg = await message.reply(str(e))
            await asyncio.sleep(2)
            await d_msg.delete()
            return

        time_taken = datetime.timedelta(seconds=int(time.time() - start_time))
        await msg.edit_text(
            f"**Broadcast Completed:**\n**Completed in** `{time_taken} seconds.`\n\n**Total Chats** ``\n"
            f"**Completed:** `{done} `\n**Success:** `{success}`")
    except Exception as e:
        d_msg = await message.reply_text(f"{str(e)}")
        await asyncio.sleep(2)
        await d_msg.delete()
        return
