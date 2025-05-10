import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
import re
from collections import defaultdict
from pymongo import MongoClient
from config import *
from config import Config

mongo_client = MongoClient(Config.DB_URL)
db = mongo_client["sequence_bot"]
users_collection = db["users_sequence"]

app = Client("sequence_bot")
user_sequences = {} 

# Patterns for extracting episode numbers
patterns = [
    re.compile(r'\b(?:EP|E)\s*-\s*(\d{1,3})\b', re.IGNORECASE),  # "Ep - 06" format fix
    re.compile(r'\b(?:EP|E)\s*(\d{1,3})\b', re.IGNORECASE),  # "EP06" or "E 06"
    re.compile(r'S(\d+)(?:E|EP)(\d+)', re.IGNORECASE),  # "S1E06" / "S01EP06"
    re.compile(r'S(\d+)\s*(?:E|EP|-\s*EP)\s*(\d+)', re.IGNORECASE),  # "S 1 Ep 06"
    re.compile(r'(?:[([<{]?\s*(?:E|EP)\s*(\d+)\s*[)\]>}]?)', re.IGNORECASE),  # "E(06)"
    re.compile(r'(?:EP|E)?\s*[-]?\s*(\d{1,3})', re.IGNORECASE),  # "E - 06" / "- 06"
    re.compile(r'S(\d+)[^\d]*(\d+)', re.IGNORECASE),  # "S1 - 06"
    re.compile(r'(\d+)')  # Simple fallback (last resort)
]
def extract_episode_number(filename):
    for pattern in patterns:
        match = pattern.search(filename)
        if match:
            return int(match.groups()[-1])
    return float('inf')  

@app.on_message(filters.command("startsequence"))
def start_sequence(client, message):
    user_id = message.from_user.id
    if user_id not in user_sequences: 
        user_sequences[user_id] = []
        message.reply_text("✅ Sequence mode started! Send your files now.")

@app.on_message(filters.command("endsequence"))
async def end_sequence(client, message):
    user_id = message.from_user.id
    if user_id not in user_sequences or not user_sequences[user_id]: 
        await message.reply_text("❌ No files in sequence!")
        return
    
    sorted_files = sorted(user_sequences[user_id], key=lambda x: extract_episode_number(x["filename"]))
    
    for file in sorted_files:
        await client.copy_message(message.chat.id, from_chat_id=file["chat_id"], message_id=file["msg_id"])
        await asyncio.sleep(0.1)  # 500 milliseconds delay (adjust if needed)

    users_collection.update_one(
        {"user_id": user_id},
        {"$inc": {"files_sequenced": len(user_sequences[user_id])}, "$set": {"username": message.from_user.first_name}},
        upsert=True
    )

    del user_sequences[user_id] 
    await message.reply_text("✅ All files have been sequenced!")

@app.on_message(filters.document | filters.video | filters.audio)
def store_file(client, message):
    user_id = message.from_user.id
    if user_id in user_sequences: 
        file_name = (
            message.document.file_name if message.document else
            message.video.file_name if message.video else
            message.audio.file_name if message.audio else
            "Unknown"
        )
        user_sequences[user_id].append({"filename": file_name, "msg_id": message.id, "chat_id": message.chat.id})
        message.reply_text("📂 Your file has been added to the sequence!")
    
@app.on_message(filters.command("leaderboard"))
async def leaderboard(client, message):
    top_users = users_collection.find().sort("files_sequenced", -1).limit(5) 
    leaderboard_text = "**🏆 Top Users 🏆**\n\n"

    for index, user in enumerate(top_users, start=1):
        leaderboard_text += f"**{index}. {user['username']}** - {user['files_sequenced']} files\n"

    if not leaderboard_text.strip():
        leaderboard_text = "No data available!"

    await message.reply_text(leaderboard_text)

