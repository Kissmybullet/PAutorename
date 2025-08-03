import os
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from pyrogram.errors import UserNotParticipant, UsernameNotOccupied
from config import Config

# List of channel usernames (without @)
FORCE_SUB_CHANNELS = Config.FORCE_SUB_CHANNELS

# Optional background image URL for prompts
IMAGE_URL = "https://i.ibb.co/gFQFknCN/d8a33273f73c.jpg"

# ✅ Safety check at startup to validate channel usernames
for ch in FORCE_SUB_CHANNELS:
    if not ch.isalnum():
        raise ValueError(f"❌ Invalid Telegram channel username in FORCE_SUB_CHANNELS: {ch}")

# 🔍 Check if the user is NOT subscribed to any required channels
async def not_subscribed(_, __, message):
    for channel in FORCE_SUB_CHANNELS:
        try:
            user = await message._client.get_chat_member(channel, message.from_user.id)
            if user.status in {"kicked", "left"}:
                return True
        except (UserNotParticipant, UsernameNotOccupied):
            return True
    return False

# 🚫 Force subscription message when user sends a private message
@Client.on_message(filters.private & filters.create(not_subscribed))
async def forces_sub(client, message):
    not_joined_channels = []

    for channel in FORCE_SUB_CHANNELS:
        try:
            user = await client.get_chat_member(channel, message.from_user.id)
            if user.status in {"kicked", "left"}:
                not_joined_channels.append(channel)
        except (UserNotParticipant, UsernameNotOccupied):
            not_joined_channels.append(channel)

    # ⬇️ Create join buttons dynamically
    buttons = [
        [InlineKeyboardButton(
            text=f"• ᴊᴏɪɴ {channel.capitalize()} •", url=f"https://t.me/{channel}"
        )]
        for channel in not_joined_channels
    ]
    buttons.append([
        InlineKeyboardButton("• ᴊᴏɪɴᴇᴅ •", callback_data="check_subscription")
    ])

    # 🧾 Message prompt
    text = (
        "**ʙᴀᴋᴋᴀ!!, ʏᴏᴜ'ʀᴇ ɴᴏᴛ ᴊᴏɪɴᴇᴅ ᴛᴏ ᴀʟʟ ʀᴇǫᴜɪʀᴇᴅ ᴄʜᴀɴɴᴇʟs, "
        "ᴊᴏɪɴ ᴛʜᴇ ᴜᴘᴅᴀᴛᴇ ᴄʜᴀɴɴᴇʟs ᴛᴏ ᴄᴏɴᴛɪɴᴜᴇ**"
    )

    await message.reply_photo(
        photo=IMAGE_URL,
        caption=text,
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ✅ Callback when user presses "JOINED" to recheck
@Client.on_callback_query(filters.regex("check_subscription"))
async def check_subscription(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    not_joined_channels = []

    for channel in FORCE_SUB_CHANNELS:
        try:
            user = await client.get_chat_member(channel, user_id)
            if user.status in {"kicked", "left"}:
                not_joined_channels.append(channel)
        except (UserNotParticipant, UsernameNotOccupied):
            not_joined_channels.append(channel)

    # ✅ If user joined all channels
    if not not_joined_channels:
        new_text = "**ʏᴏᴜ ʜᴀᴠᴇ ᴊᴏɪɴᴇᴅ ᴀʟʟ ᴛʜᴇ ʀᴇǫᴜɪʀᴇᴅ ᴄʜᴀɴɴᴇʟs. ɢᴏᴏᴅ ʙᴏʏ! 🔥 /start ɴᴏᴡ**"
        if callback_query.message.caption != new_text:
            await callback_query.message.edit_caption(
                caption=new_text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("• ɴᴏᴡ ᴄʟɪᴄᴋ ʜᴇʀᴇ •", callback_data='help')]
                ])
            )
    else:
        # 🚫 Still not joined all required channels
        buttons = [
            [InlineKeyboardButton(
                text=f"• ᴊᴏɪɴ {channel.capitalize()} •", url=f"https://t.me/{channel}"
            )]
            for channel in not_joined_channels
        ]
        buttons.append([
            InlineKeyboardButton("• ᴊᴏɪɴᴇᴅ •", callback_data="check_subscription")
        ])

        text = (
            "**ʏᴏᴜ ʜᴀᴠᴇ ɴᴏᴛ ᴊᴏɪɴᴇᴅ ᴀʟʟ ᴛʜᴇ ʀᴇǫᴜɪʀᴇᴅ ᴄʜᴀɴɴᴇʟs. "
            "ᴘʟᴇᴀsᴇ ᴊᴏɪɴ ᴛʜᴇ ᴜᴘᴅᴀᴛᴇ ᴄʜᴀɴɴᴇʟs ᴛᴏ ᴄᴏɴᴛɪɴᴜᴇ**"
        )
        if callback_query.message.caption != text:
            await callback_query.message.edit_caption(
                caption=text,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
