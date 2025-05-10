import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
import re
from collections import defaultdict
from pymongo import MongoClient
from datetime import datetime
from config import Config

# Use the existing database connection from the main bot
db_client = MongoClient(Config.DB_URL)
db = db_client[Config.DB_NAME]
users_collection = db["users_sequence"]

# We'll use MongoDB for persistent storage instead of in-memory dictionary
# Collection to track user sequence data and sequence mode status
sequence_data_collection = db["sequence_data"]

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

@Client.on_message(filters.command("startsequence"))
async def start_sequence(client, message):
    user_id = message.from_user.id
    
    # Check if user already has an active sequence
    user_data = sequence_data_collection.find_one({"user_id": user_id, "active": True})
    
    if not user_data:
        # Create new sequence entry in database
        sequence_data_collection.update_one(
            {"user_id": user_id},
            {"$set": {"active": True, "files": [], "started_at": datetime.now()}},
            upsert=True
        )
        await message.reply_text("✅ Sequence mode started! Send your files now.")
    else:
        await message.reply_text("⚠️ Sequence mode is already active. Send your files or use /endsequence.")

@Client.on_message(filters.command("endsequence"))
async def end_sequence(client, message):
    user_id = message.from_user.id
    
    # Get user's sequence data from database
    user_data = sequence_data_collection.find_one({"user_id": user_id, "active": True})
    
    if not user_data or not user_data.get("files", []):
        await message.reply_text("❌ No files in sequence!")
        return
    
    # Send progress message
    progress = await message.reply_text("⏳ Processing and sorting your files...")
    
    # Get files from database
    files = user_data.get("files", [])
    
    # Sort files by episode number
    sorted_files = sorted(files, key=lambda x: extract_episode_number(x["filename"]))
    total = len(sorted_files)
    
    await progress.edit_text(f"📤 Sending {total} files in sequence...")
    
    for i, file in enumerate(sorted_files, 1):
        # Forward the file
        await client.copy_message(
            chat_id=message.chat.id, 
            from_chat_id=file["chat_id"], 
            message_id=file["msg_id"]
        )
        
        # Update progress every 5 files
        if i % 5 == 0:
            await progress.edit_text(f"📤 Sent {i}/{total} files...")
        
        await asyncio.sleep(0.5)  # Add delay to prevent flooding

    # Update user stats in database
    users_collection.update_one(
        {"user_id": user_id},
        {"$inc": {"files_sequenced": len(files)}, 
         "$set": {"username": message.from_user.first_name}},
        upsert=True
    )

    # Deactivate sequence mode in database
    sequence_data_collection.update_one(
        {"user_id": user_id},
        {"$set": {"active": False, "completed_at": datetime.now()}}
    )
    
    await progress.edit_text("✅ All files have been sequenced successfully!")

# Modified handler with specific filter to prevent conflict with auto_rename
@Client.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def store_file(client, message):
    user_id = message.from_user.id
    
    # Check if user is in sequence mode from database
    user_data = sequence_data_collection.find_one({"user_id": user_id, "active": True})
    
    # Only process if user is in sequence mode
    if user_data:
        # Get file name based on message type
        file_name = (
            message.document.file_name if message.document else
            message.video.file_name if message.video else
            message.audio.file_name if message.audio else
            "Unknown"
        )
        
        # File info to store
        file_info = {
            "filename": file_name, 
            "msg_id": message.id, 
            "chat_id": message.chat.id,
            "added_at": datetime.now()
        }
        
        # Add to database
        sequence_data_collection.update_one(
            {"user_id": user_id, "active": True},
            {"$push": {"files": file_info}}
        )
        
        # Add a flag to indicate this message has been handled by sequence
        # The file_rename plugin can check for this flag
        setattr(message, "_sequence_handled", True)
        
        await message.reply_text(f"📂 Added to sequence: {file_name}")
    
@Client.on_message(filters.command("leaderboard"))
async def leaderboard(client, message):
    top_users = list(users_collection.find().sort("files_sequenced", -1).limit(5))
    
    if not top_users:
        await message.reply_text("No data available in the leaderboard yet!")
        return
        
    leaderboard_text = "**🏆 Top Users - File Sequencing 🏆**\n\n"

    for index, user in enumerate(top_users, start=1):
        username = user.get('username', 'Unknown User')
        files_count = user.get('files_sequenced', 0)
        leaderboard_text += f"**{index}. {username}** - {files_count} files\n"

    await message.reply_text(leaderboard_text)

@Client.on_message(filters.command("cancelsequence"))
async def cancel_sequence(client, message):
    user_id = message.from_user.id
    
    # Check if user has an active sequence
    result = sequence_data_collection.update_one(
        {"user_id": user_id, "active": True},
        {"$set": {"active": False, "cancelled_at": datetime.now()}}
    )
    
    if result.modified_count > 0:
        await message.reply_text("❌ Sequence mode cancelled. All queued files have been cleared.")
    else:
        await message.reply_text("❓ No active sequence found to cancel.")
