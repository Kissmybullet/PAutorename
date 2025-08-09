import os
import re
import time
import shutil
import asyncio
import logging
from datetime import datetime
from PIL import Image
from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import InputMediaDocument, Message
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
from plugins.antinsfw import check_anti_nsfw
from helper.utils import progress_for_pyrogram, humanbytes, convert
from helper.database import codeflixbots
from config import Config
from pymongo import MongoClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global dictionary to track ongoing operations
renaming_operations = {}

# Database connection for checking sequence mode
db_client = MongoClient(Config.DB_URL)
db = db_client[Config.DB_NAME]
sequence_collection = db["active_sequences"]

# Enhanced regex patterns for season and episode extraction
SEASON_EPISODE_PATTERNS = [
    # Standard patterns (S01E02, S01EP02)
    (re.compile(r'S(\d+)(?:E|EP)(\d+)'), ('season', 'episode')),
    # Patterns with spaces/dashes (S01 E02, S01-EP02)
    (re.compile(r'S(\d+)[\s-]*(?:E|EP)(\d+)'), ('season', 'episode')),
    # Full text patterns (Season 1 Episode 2)
    (re.compile(r'Season\s*(\d+)\s*Episode\s*(\d+)', re.IGNORECASE), ('season', 'episode')),
    # Patterns with brackets/parentheses ([S01][E02])
    (re.compile(r'\[S(\d+)\]\[E(\d+)\]'), ('season', 'episode')),
    # Fallback patterns (S01 13, Episode 13)
    (re.compile(r'S(\d+)[^\d]*(\d+)'), ('season', 'episode')),
    (re.compile(r'(?:E|EP|Episode)\s*(\d+)', re.IGNORECASE), (None, 'episode')),
    # Final fallback (standalone number)
    (re.compile(r'\b(\d+)\b'), (None, 'episode'))
]

# Quality detection patterns
QUALITY_PATTERNS = [
    (re.compile(r'\b(\d{3,4}[pi])\b', re.IGNORECASE), lambda m: m.groups()[0] if m.groups() else "Unknown"),
    (re.compile(r'\b(4k|2160p)\b', re.IGNORECASE), lambda m: "4k"),
    (re.compile(r'\b(2k|1440p)\b', re.IGNORECASE), lambda m: "2k"),
    (re.compile(r'\b(HDRip|HDTV)\b', re.IGNORECASE), lambda m: m.groups()[0] if m.groups() else "Unknown"),
    (re.compile(r'\b(4kX264|4kx265)\b', re.IGNORECASE), lambda m: m.groups()[0] if m.groups() else "Unknown"),
    (re.compile(r'\[(\d{3,4}[pi])\]', re.IGNORECASE), lambda m: m.groups()[0] if m.groups() else "Unknown")
]

# ✨ NEW: Enhanced title detection patterns
TITLE_PATTERNS = [
    # Show name before - E## pattern (e.g., "Serial Lain - E03")
    (re.compile(r'^(.+?)\s*-\s*E\d+', re.IGNORECASE), 'episode_dash'),
    # Show name before season/episode (e.g., "The Office S01E01")
    (re.compile(r'^(.+?)\s*[Ss]\d+[Ee]\d+', re.IGNORECASE), 'show'),
    # Show name in brackets before season (e.g., "[Attack on Titan] S01E01")
    (re.compile(r'\[(.+?)\](?=.*[Ss]\d+[Ee]\d+)', re.IGNORECASE), 'show'),
    # Movie with year (e.g., "Avengers Endgame (2019)")
    (re.compile(r'^(.+?)\s*\((\d{4})\)', re.IGNORECASE), 'movie'),
    # Title before quality indicators
    (re.compile(r'^(.+?)\s*(?=\d{3,4}[pi]|HDRip|BluRay|WEB-DL|x264|x265)', re.IGNORECASE), 'title'),
    # Title before episode number (e.g., "Naruto 001")
    (re.compile(r'^(.+?)\s*(?=\d{2,3}(?:\s|$))', re.IGNORECASE), 'series'),
    # Clean title from common separators
    (re.compile(r'^(.+?)(?=\s*[-._]\s*(?:\d|S\d|E\d))', re.IGNORECASE), 'generic'),
    # Fallback: everything before first number or special pattern
    (re.compile(r'^(.+?)(?=\s*\d)', re.IGNORECASE), 'fallback'),
]

# ✨ NEW: Audio detection patterns - ONLY for Sub/Dub/Dual content
AUDIO_PATTERNS = [
    # Primary audio type detection (Sub, Dub, Dual only)
    (re.compile(r'\b(Sub|Dub|Dual)\b', re.IGNORECASE), 'primary_type'),
    # Extended audio type patterns
    (re.compile(r'\b(Dubbed|Subtitle|Subtitled)\b', re.IGNORECASE), 'extended_type'),
    # Language with Sub/Dub/Dual context
    (re.compile(r'\b(Hindi|English|Tamil|Telugu|Malayalam|Kannada|Bengali|Gujarati|Punjabi|Marathi)\s*(Sub|Dub|Dual|Dubbed)\b', re.IGNORECASE), 'lang_with_type'),
    # Audio format indicators in brackets (only if contains Sub/Dub/Dual)
    (re.compile(r'\[([^]]*(?:Sub|Dub|Dual)[^]]*)\]', re.IGNORECASE), 'bracket_sub_dub'),
    # Parentheses with Sub/Dub/Dual
    (re.compile(r'\(([^)]*(?:Sub|Dub|Dual)[^)]*)\)', re.IGNORECASE), 'paren_sub_dub'),
]

def extract_title(filename):
    """Extract title from filename automatically"""
    logger.info(f"Attempting to extract title from: {filename}")
    
    for pattern, title_type in TITLE_PATTERNS:
        match = pattern.search(filename)
        if match:
            title = match.groups()[0].strip()
            
            # Clean up the title
            title = re.sub(r'[._-]', ' ', title)  # Replace dots, underscores, dashes with spaces
            title = re.sub(r'\s+', ' ', title).strip()  # Remove multiple spaces
            
            # Remove quality indicators from title
            title = re.sub(r'\b(720p|1080p|480p|4k|2k|HDRip|BluRay|WEB-DL|x264|x265|HEVC|H\.264|H\.265)\b', '', title, flags=re.IGNORECASE).strip()
            
            # Remove common release group patterns and brackets
            title = re.sub(r'\[.*?\]|\(.*?\)|\{.*?\}', '', title).strip()
            
            # Remove year from title if it's a movie pattern
            if title_type == 'movie':
                title = re.sub(r'\s*\d{4}\s*', '', title).strip()
            
            # Final cleanup - remove trailing separators
            title = re.sub(r'[-._\s]+$', '', title).strip()
            
            if len(title) > 2 and not title.isdigit():  # Ensure it's a valid title
                logger.info(f"Extracted {title_type} title: '{title}' from {filename}")
                return title
                
    logger.warning(f"No title pattern matched for {filename}")
    return "Unknown Title"


    
    # Build comprehensive audio description
    audio_parts = []
    
    # Add language first (most important)
    if 'language' in audio_info:
        audio_parts.append(audio_info['language'])
    elif 'lang_bracket' in audio_info:
        audio_parts.append(audio_info['lang_bracket'])
    
    # Add audio type
    if 'type' in audio_info:
        audio_parts.append(audio_info['type'])
    
    # Add codec
    if 'codec' in audio_info:
        audio_parts.append(audio_info['codec'])
    
    # Add surround sound info
    if 'surround' in audio_info:
        audio_parts.append(audio_info['surround'])
    elif 'channels' in audio_info:
        audio_parts.append(audio_info['channels'])
    
    # Add bitrate
    if 'bitrate' in audio_info:
        audio_parts.append(audio_info['bitrate'])
    
    final_audio = ' '.join(audio_parts) if audio_parts else "Unknown Audio"
    logger.info(f"Final audio description: '{final_audio}'")
    return final_audio

def is_in_sequence_mode(user_id):
    """Check if user is in sequence mode"""
    try:
        return sequence_collection.find_one({"user_id": user_id}) is not None
    except Exception as e:
        logger.error(f"Error checking sequence mode: {e}")
        return False

def extract_season_episode(filename):
    """Extract season and episode numbers from filename"""
    for pattern, (season_group, episode_group) in SEASON_EPISODE_PATTERNS:
        match = pattern.search(filename)
        if match:
            groups = match.groups()
            season = groups[0] if season_group and len(groups) > 0 else None
            episode = groups[1] if episode_group and len(groups) > 1 else (groups[0] if len(groups) > 0 else None)
            logger.info(f"Extracted season: {season}, episode: {episode} from {filename}")
            return season, episode
    logger.warning(f"No season/episode pattern matched for {filename}")
    return None, None

def extract_quality(filename):
    """Extract quality information from filename"""
    for pattern, extractor in QUALITY_PATTERNS:
        match = pattern.search(filename)
        if match:
            quality = extractor(match)
            logger.info(f"Extracted quality: {quality} from {filename}")
            return quality
    logger.warning(f"No quality pattern matched for {filename}")
    return "Unknown"

async def cleanup_files(*paths):
    """Safely remove files if they exist"""
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
                logger.info(f"Cleaned up file: {path}")
        except Exception as e:
            logger.error(f"Error removing {path}: {e}")

async def process_thumbnail(thumb_path):
    """Process and resize thumbnail image"""
    if not thumb_path or not os.path.exists(thumb_path):
        return None
    
    try:
        with Image.open(thumb_path) as img:
            img = img.convert("RGB").resize((320, 320))
            img.save(thumb_path, "JPEG")
        logger.info(f"Processed thumbnail: {thumb_path}")
        return thumb_path
    except Exception as e:
        logger.error(f"Thumbnail processing failed: {e}")
        await cleanup_files(thumb_path)
        return None

async def add_metadata(input_path, output_path, user_id):
    """Add metadata to media file using ffmpeg"""
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        logger.warning("FFmpeg not found in PATH, skipping metadata addition")
        # Just copy the file instead of adding metadata
        try:
            shutil.copy2(input_path, output_path)
            logger.info(f"Copied file from {input_path} to {output_path}")
            return
        except Exception as e:
            logger.error(f"Error copying file: {e}")
            raise RuntimeError(f"Failed to process file: {e}")
    
    try:
        metadata = {
            'title': await codeflixbots.get_title(user_id) or "Unknown",
            'artist': await codeflixbots.get_artist(user_id) or "Unknown",
            'author': await codeflixbots.get_author(user_id) or "Unknown",
            'video_title': await codeflixbots.get_video(user_id) or "Video",
            'audio_title': await codeflixbots.get_audio(user_id) or "Audio",
            'subtitle': await codeflixbots.get_subtitle(user_id) or "Subtitle"
        }
        
        cmd = [
            ffmpeg,
            '-i', input_path,
            '-metadata', f'title={metadata["title"]}',
            '-metadata', f'artist={metadata["artist"]}',
            '-metadata', f'author={metadata["author"]}',
            '-metadata:s:v', f'title={metadata["video_title"]}',
            '-metadata:s:a', f'title={metadata["audio_title"]}',
            '-metadata:s:s', f'title={metadata["subtitle"]}',
            '-map', '0',
            '-c', 'copy',
            '-loglevel', 'error',
            output_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg error: {stderr.decode()}")
        
        logger.info(f"Added metadata to {output_path}")
    except Exception as e:
        logger.error(f"Metadata addition failed: {e}")
        raise

def get_file_duration(file_path):
    """Get duration of media file"""
    try:
        metadata = extractMetadata(createParser(file_path))
        if metadata is not None and metadata.has("duration"):
            duration_seconds = int(metadata.get("duration").seconds)
            return str(datetime.timedelta(seconds=duration_seconds))
        return "00:00:00"
    except Exception as e:
        logger.error(f"Error getting duration: {e}")
        return "00:00:00"

def format_caption(caption_template, filename, filesize, duration):
    """Replace caption variables with actual values"""
    if not caption_template:
        return None
    
    try:
        # Convert filesize to human-readable format
        filesize_str = humanbytes(filesize)
        
        # Perform replacements
        caption = caption_template
        caption = caption.replace("{filename}", filename)
        caption = caption.replace("{filesize}", filesize_str)
        caption = caption.replace("{duration}", duration)
        
        return caption
    except Exception as e:
        logger.error(f"Error formatting caption: {e}")
        return f"**{filename}**"

@Client.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def auto_rename_files(client, message):
    """Main handler for auto-renaming files"""
    user_id = message.from_user.id
    
    try:
        # Check if user is premium
        is_premium = await codeflixbots.is_premium_user(user_id)
        
        if not is_premium:
            return await message.reply_text(
                "❌ **𝗣𝗿𝗲𝗺𝗶𝘂𝗺 𝗙𝗲𝗮𝘁𝘂𝗿𝗲** ❌\n\n"
                "File renaming is a 𝗣𝗿𝗲𝗺𝗶𝘂𝗺 𝗙𝗲𝗮𝘁𝘂𝗿𝗲.\n"
                "Contact @aaru_2075 to rename files."
            )
        
        # Skip if user is in sequence mode
        if is_in_sequence_mode(user_id):
            logger.info(f"User {user_id} is in sequence mode, skipping rename")
            return
        
        format_template = await codeflixbots.get_format_template(user_id)
        
        if not format_template:
            return await message.reply_text("Please set a rename format using /autorename")

        # Get file information
        if message.document:
            file_id = message.document.file_id
            file_name = message.document.file_name or "document"
            file_size = message.document.file_size
            media_type = "document"
        elif message.video:
            file_id = message.video.file_id
            file_name = message.video.file_name or "video"
            file_size = message.video.file_size
            media_type = "video"
        elif message.audio:
            file_id = message.audio.file_id
            file_name = message.audio.file_name or "audio"
            file_size = message.audio.file_size
            media_type = "audio"
        else:
            return await message.reply_text("Unsupported file type")

        logger.info(f"Processing {media_type}: {file_name} for user {user_id}")

        # NSFW check
        try:
            if await check_anti_nsfw(file_name, message):
                return await message.reply_text("NSFW content detected")
        except Exception as e:
            logger.error(f"NSFW check failed: {e}")

        # Prevent duplicate processing
        if file_id in renaming_operations:
            if (datetime.now() - renaming_operations[file_id]).seconds < 10:
                logger.info(f"Duplicate processing prevented for {file_id}")
                return
        renaming_operations[file_id] = datetime.now()

        # Initialize paths to None for proper cleanup handling
        download_path = None
        metadata_path = None
        thumb_path = None

        try:
            # ✨ ENHANCED: Extract metadata from filename
            season, episode = extract_season_episode(file_name)
            quality = extract_quality(file_name)
            title = extract_title(file_name)  # ✨ NEW: Auto-detect title
            audio_info = extract_audio_info(file_name)  # ✨ NEW: Auto-detect audio
            
            # ✨ Enhanced logging for debugging
            logger.info(f"""
Auto-detection results for {file_name}:
- Season: {season}
- Episode: {episode} 
- Quality: {quality}
- Title: {title}
- Audio: {audio_info}
""")
            
            # ✨ ENHANCED: Replace placeholders in template with new auto-detected values
            replacements = {
                '{season}': season or 'XX',
                '{episode}': episode or 'XX',
                '{quality}': quality,
                '{title}': title,                    # ✨ NEW: Auto-detected title
                '{audio}': audio_info,              # ✨ NEW: Auto-detected audio info (empty if no Sub/Dub/Dual)
                'Season': season or 'XX',
                'Episode': episode or 'XX',
                'QUALITY': quality,
                'Title': title,                     # ✨ NEW: Capitalized title
                'TITLE': title.upper() if title != "Unknown Title" else "UNKNOWN",  # ✨ NEW: Uppercase title
                'Audio': audio_info,                # ✨ NEW: Capitalized audio (empty if no Sub/Dub/Dual)
                'AUDIO': audio_info.upper() if audio_info else ""  # ✨ NEW: Uppercase audio (empty if no Sub/Dub/Dual)
            }
            
            # Clean up the template by removing empty audio placeholders if no audio detected
            if not audio_info:  # If audio_info is empty
                # Remove common audio placeholder patterns that would leave empty brackets/spaces
                format_template = re.sub(r'\s*\[{audio}\]\s*', '', format_template, flags=re.IGNORECASE)
                format_template = re.sub(r'\s*\[{Audio}\]\s*', '', format_template, flags=re.IGNORECASE) 
                format_template = re.sub(r'\s*\[{AUDIO}\]\s*', '', format_template, flags=re.IGNORECASE)
                format_template = re.sub(r'\s*-\s*{audio}\s*', '', format_template, flags=re.IGNORECASE)
                format_template = re.sub(r'\s*-\s*{Audio}\s*', '', format_template, flags=re.IGNORECASE)
                format_template = re.sub(r'\s*-\s*{AUDIO}\s*', '', format_template, flags=re.IGNORECASE)
                format_template = re.sub(r'\s*{audio}\s*-\s*', '', format_template, flags=re.IGNORECASE)
                format_template = re.sub(r'\s*{Audio}\s*-\s*', '', format_template, flags=re.IGNORECASE)
                format_template = re.sub(r'\s*{AUDIO}\s*-\s*', '', format_template, flags=re.IGNORECASE)
            
            for placeholder, value in replacements.items():
                format_template = format_template.replace(placeholder, value)

            # Show warning for missing season/episode only if title extraction also failed
            if season is None and episode is None and title == "Unknown Title":
                await message.reply_text(f"⚠️ Could not extract season/episode or title from: `{file_name}`\nProceeding with available data...")

            # Prepare file paths
            ext = os.path.splitext(file_name)[1] or ('.mp4' if media_type == 'video' else '.mp3')
            new_filename = f"{format_template}{ext}"
            
            # Create safe directory names
            downloads_dir = "downloads"
            metadata_dir = "metadata"
            
            # Ensure directories exist
            os.makedirs(downloads_dir, exist_ok=True)
            os.makedirs(metadata_dir, exist_ok=True)
            
            download_path = os.path.join(downloads_dir, new_filename)
            metadata_path = os.path.join(metadata_dir, new_filename)

            # Download file
            msg = await message.reply_text("**Downloading...**")
            try:
                file_path = await client.download_media(
                    message,
                    file_name=download_path,
                    progress=progress_for_pyrogram,
                    progress_args=("Downloading...", msg, time.time())
                )
                logger.info(f"Downloaded file to: {file_path}")
            except FloodWait as e:
                await asyncio.sleep(e.value)
                file_path = await client.download_media(
                    message,
                    file_name=download_path,
                    progress=progress_for_pyrogram,
                    progress_args=("Downloading...", msg, time.time())
                )
            except Exception as e:
                await msg.edit(f"Download failed: {str(e)}")
                logger.error(f"Download failed: {e}")
                raise

            # Process metadata
            await msg.edit("**Processing metadata...**")
            try:
                await add_metadata(file_path, metadata_path, user_id)
                file_path = metadata_path
            except Exception as e:
                await msg.edit(f"Metadata processing failed: {str(e)}")
                logger.error(f"Metadata processing failed: {e}")
                # Continue with original file if metadata processing fails
                file_path = download_path

            # Get duration for video/audio files
            duration = "00:00:00"
            if media_type in ["video", "audio"]:
                duration = get_file_duration(file_path)

            # Prepare for upload
            await msg.edit("**Preparing upload...**")
            
            # Get caption template and replace variables
            try:
                caption_template = await codeflixbots.get_caption(message.chat.id)
                if caption_template:
                    caption = format_caption(caption_template, new_filename, file_size, duration)
                else:
                    caption = f"**{new_filename}**"
            except Exception as e:
                logger.error(f"Caption processing failed: {e}")
                caption = f"**{new_filename}**"
                
            # Handle thumbnail
            try:
                thumb = await codeflixbots.get_thumbnail(message.chat.id)
                
                if thumb:
                    thumb_path = await client.download_media(thumb)
                elif media_type == "video" and message.video.thumbs:
                    thumb_path = await client.download_media(message.video.thumbs[0].file_id)
                
                # Only process if thumb_path was set
                if thumb_path:
                    thumb_path = await process_thumbnail(thumb_path)
            except Exception as e:
                logger.error(f"Thumbnail processing failed: {e}")
                thumb_path = None

            # Get user's media preference
            try:
                user_media_preference = await codeflixbots.get_media_preference(user_id)
                logger.info(f"User {user_id} media preference: {user_media_preference}")
                
                # If no preference set, use original media type
                if not user_media_preference:
                    user_media_preference = media_type
                    logger.info(f"No preference set, using original type: {media_type}")
                else:
                    # Convert to lowercase for consistent comparison
                    user_media_preference = user_media_preference.lower()
                    logger.info(f"Using user's preference: {user_media_preference}")
            except Exception as e:
                logger.error(f"Error getting media preference: {e}")
                user_media_preference = media_type

            # Upload file
            await msg.edit("**Uploading...**")
            try:
                upload_params = {
                    'chat_id': message.chat.id,
                    'caption': caption,
                    'progress': progress_for_pyrogram,
                    'progress_args': ("Uploading...", msg, time.time())
                }
                
                # Only add thumb to parameters if it exists
                if thumb_path:
                    upload_params['thumb'] = thumb_path

                # Use user's media preference for sending
                if user_media_preference == "document":
                    await client.send_document(document=file_path, **upload_params)
                elif user_media_preference == "video":
                    await client.send_video(video=file_path, **upload_params)
                elif user_media_preference == "audio":
                    await client.send_audio(audio=file_path, **upload_params)
                else:
                    # Fallback to original media type if preference is invalid
                    logger.warning(f"Invalid preference: {user_media_preference}, using original: {media_type}")
                    if media_type == "document":
                        await client.send_document(document=file_path, **upload_params)
                    elif media_type == "video":
                        await client.send_video(video=file_path, **upload_params)
                    elif media_type == "audio":
                        await client.send_audio(audio=file_path, **upload_params)

                await msg.delete()
                logger.info(f"Successfully processed and uploaded: {new_filename}")
                
            except FloodWait as e:
                await asyncio.sleep(e.value)
                # Retry upload after flood wait
                if user_media_preference == "document":
                    await client.send_document(document=file_path, **upload_params)
                elif user_media_preference == "video":
                    await client.send_video(video=file_path, **upload_params)
                elif user_media_preference == "audio":
                    await client.send_audio(audio=file_path, **upload_params)
                await msg.delete()
            except Exception as e:
                await msg.edit(f"Upload failed: {str(e)}")
                logger.error(f"Upload failed: {e}")
                raise

        except Exception as e:
            logger.error(f"Processing error for user {user_id}: {e}")
            try:
                await message.reply_text(f"Error processing file: {str(e)}")
            except:
                pass
        finally:
            # Clean up files - safe to pass None values
            await cleanup_files(download_path, metadata_path, thumb_path)
            renaming_operations.pop(file_id, None)
            logger.info(f"Cleanup completed for file: {file_id}")
            
    except Exception as e:
        logger.error(f"Handler error for user {user_id}: {e}")
        try:
            await message.reply_text("An unexpected error occurred. Please try again.")
        except:
            pass
