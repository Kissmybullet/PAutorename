from pyrogram import Client, filters
from pyrogram.types import Message
from config import ADMIN as AUTH_USERS
import os

@Client.on_message(filters.document | filters.video | filters.audio)
async def rename_handler(client: Client, message: Message):
    # Only allow users in AUTH_USERS
    if message.from_user.id not in AUTH_USERS:
        return await message.reply_text(
            text="❌ 𝗣𝗿𝗲𝗺𝗶𝘂𝗺 𝗙𝗲𝗮𝘁𝘂𝗿𝗲 ❌\n\nFile renaming is a 𝗣𝗿𝗲𝗺𝗶𝘂𝗺 𝗙𝗲𝗮𝘁𝘂𝗿𝗲.\nContact @aaru_2075 to rename files.",
            quote=True
        )

    # Extract file details
    media = message.document or message.video or message.audio
    file_name = media.file_name
    file_size = media.file_size
    file_id = media.file_id

    # Ask for new file name
    await message.reply_text(f"📁 Current file name:\n`{file_name}`\n\nSend me new file name (with extension):")

    # Listen for reply
    try:
        response = await client.listen(message.chat.id, timeout=60)
    except TimeoutError:
        return await message.reply_text("❗ Timed out. Please send the file again and respond quicker.")

    new_file_name = response.text.strip()
    if "." not in new_file_name:
        return await message.reply("❌ Invalid file name. Must include extension (e.g., `.mkv`, `.mp4`, `.zip`).")

    await message.reply_text("⏳ Downloading...")

    d_path = await client.download_media(message, file_name)
    new_path = os.path.join(os.path.dirname(d_path), new_file_name)
    os.rename(d_path, new_path)

    await message.reply_text("✅ Renamed! Uploading...")

    await client.send_document(
        chat_id=message.chat.id,
        document=new_path,
        caption=f"**Renamed to:** `{new_file_name}`"
    )

    os.remove(new_path)
