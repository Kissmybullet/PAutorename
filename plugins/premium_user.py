from pyrogram import Client, filters
import datetime
import pytz
from helper.database import codeflixbots
import logging
from config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Command to add premium user
@Client.on_message(filters.command("addpremium") & filters.user(Config.BOT_OWNER))
async def add_premium_command(client, message):
    """Add a user as premium for a given time period"""
    try:
        # Parse command format: /addpremium [reply/userid/username] [duration: Xm/Xh/Xd/Xmh]
        command_parts = message.text.split()
        
        # Handle reply case with only duration provided
        if message.reply_to_message and len(command_parts) == 2:
            user_id = message.reply_to_message.from_user.id
            duration = command_parts[1]
        # Handle direct command with both user and duration
        elif len(command_parts) == 3:
            user_identifier = command_parts[1]
            duration = command_parts[2]
            
            # Check if user_identifier is a numeric ID
            if user_identifier.isdigit():
                user_id = int(user_identifier)
            else:
                # Handle username
                if user_identifier.startswith("@"):
                    username = user_identifier[1:]  # Remove @ symbol
                else:
                    username = user_identifier
                    
                # Resolve username to user ID
                try:
                    user = await client.get_users(username)
                    user_id = user.id
                except Exception as e:
                    return await message.reply_text(f"Failed to find user: {e}")
        else:
            return await message.reply_text(
                "**Usage:** `/addpremium [reply/userid/username] [duration: Xm/Xh/Xd/Xmh]`\n\n"
                "**Examples:**\n"
                "- `/addpremium 123456789 30d` (30 days)\n"
                "- `/addpremium @username 2mh` (2 months)\n"
                "- Reply to message: `/addpremium 6h` (reply to add 6 hours)"
            )
        
        # Check if user exists in database, add if not
        if not await codeflixbots.is_user_exist(user_id):
            user = codeflixbots.new_user(user_id)
            await codeflixbots.col.insert_one(user)
        
        # Add user as premium
        success, result = await codeflixbots.add_premium_user(user_id, duration)
        
        if success:
            # Try to get username for notification message
            try:
                user_info = await client.get_users(user_id)
                username_text = f"@{user_info.username}" if user_info.username else f"[User](tg://user?id={user_id})"
            except:
                username_text = f"User ID: `{user_id}`"
                
            # Format expiry date for display in IST
            try:
                expiry_date = datetime.datetime.fromisoformat(result)
                ist_timezone = pytz.timezone('Asia/Kolkata')
                expiry_date_ist = expiry_date.astimezone(ist_timezone)
                formatted_expiry = expiry_date_ist.strftime("%d %b %Y, %H:%M:%S IST")
            except:
                formatted_expiry = result

            await message.reply_text(
                f"✅ Successfully added {username_text} as premium user!\n\n"
                f"Premium will expire on: `{formatted_expiry}`"
            )
        else:
            await message.reply_text(f"❌ Failed to add premium user: {result}")
    
    except Exception as e:
        logger.error(f"Error in add_premium_command: {e}")
        await message.reply_text(f"❌ An error occurred: {str(e)}")


# Command to check premium status
@Client.on_message(filters.command("myplan"))
async def check_premium_command(client, message):
    """Check premium status of a user"""
    user_id = message.from_user.id
    
    # Check if admin is checking another user's status
    command_parts = message.text.split()
    if len(command_parts) > 1 and message.from_user.id in Config.BOT_OWNER:
        try:
            check_user = command_parts[1]
            if check_user.isdigit():
                user_id = int(check_user)
            elif check_user.startswith("@"):
                user = await client.get_users(check_user[1:])
                user_id = user.id
            else:
                user = await client.get_users(check_user)
                user_id = user.id
        except Exception as e:
            return await message.reply_text(f"Failed to find user: {e}")
    
    # Get premium details
    is_premium = await codeflixbots.is_premium_user(user_id)
    premium_details = await codeflixbots.get_premium_details(user_id)
    
    if is_premium and premium_details:
        try:
            expiry_date = datetime.datetime.fromisoformat(premium_details["expiry_date"])
            ist_timezone = pytz.timezone('Asia/Kolkata')
            expiry_date_ist = expiry_date.astimezone(ist_timezone)
            remaining_time = expiry_date_ist - datetime.datetime.now(ist_timezone)
    
            # Format remaining time nicely
            days = remaining_time.days
            hours, remainder = divmod(remaining_time.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
    
            time_str = ""
            if days > 0:
                time_str += f"{days} days, "
            if hours > 0 or days > 0:
                time_str += f"{hours} hours, "
            time_str += f"{minutes} minutes"
    
            await message.reply_text(
        f"✨ **Premium Status: Active** ✨\n\n"
        f"**Expires on:** `{expiry_date_ist.strftime('%d %b %Y, %H:%M:%S IST')}`\n"
        f"**Time remaining:** `{time_str}`\n\n"
        f"You have access to all premium features including file renaming!"
    )
        except Exception as e:
            await message.reply_text(
        f"✨ **Premium Status: Active** ✨\n\n"
        f"**Expires on:** `{premium_details.get('expiry_date', 'Unknown')}`\n\n"
        f"You have access to all premium features including file renaming!"
    )
    else:
        await message.reply_text(
            "❌ **Premium Status: Inactive** ❌\n\n"
            "You don't have premium access. Contact @introvertsama to get premium and unlock file renaming features!"
        )


# Command to remove premium
@Client.on_message(filters.command("rmpremium") & filters.user(Config.BOT_OWNER))
async def remove_premium_command(client, message):
    """Remove premium status from a user"""
    try:
        # Parse command
        command_parts = message.text.split()
        
        if len(command_parts) != 2 and not message.reply_to_message:
            return await message.reply_text(
                "**Usage:** `/rmpremium [userid/username]` or reply to a user's message"
            )
        
        # Handle reply case
        if message.reply_to_message:
            user_id = message.reply_to_message.from_user.id
        else:
            user_identifier = command_parts[1]
            
            # Check if user_identifier is a numeric ID
            if user_identifier.isdigit():
                user_id = int(user_identifier)
            else:
                # Handle username
                if user_identifier.startswith("@"):
                    username = user_identifier[1:]
                else:
                    username = user_identifier
                    
                # Resolve username to user ID
                try:
                    user = await client.get_users(username)
                    user_id = user.id
                except Exception as e:
                    return await message.reply_text(f"Failed to find user: {e}")
        
        # Remove premium
        success = await codeflixbots.remove_premium(user_id)
        
        if success:
            try:
                user_info = await client.get_users(user_id)
                username_text = f"@{user_info.username}" if user_info.username else f"[User](tg://user?id={user_id})"
            except:
                username_text = f"User ID: `{user_id}`"
                
            await message.reply_text(f"✅ Successfully removed premium access from {username_text}")
        else:
            await message.reply_text("❌ Failed to remove premium access")
    
    except Exception as e:
        logger.error(f"Error in remove_premium_command: {e}")
        await message.reply_text(f"❌ An error occurred: {str(e)}")

# Add this at the end of the plugins/premium_user.py file

# Command to list all premium users
@Client.on_message(filters.command("premiumusers") & filters.user(Config.BOT_OWNER))
async def list_premium_users(client, message):
    """List all active premium users"""
    try:
        # Get all users from database
        all_users = await codeflixbots.get_all_users()
        
        # Counter for premium users
        premium_count = 0
        premium_users_list = []
        
        # Iterate through all users and check premium status
        async for user in all_users:
            user_id = user["_id"]
            
            # Skip if no premium info or not premium
            if "premium" not in user or not user["premium"].get("is_premium", False):
                continue
                
            # Check if premium has expired
            expiry = user["premium"].get("expiry_date")
            if not expiry:
                continue
                
            # Convert string to datetime
            try:
                expiry_date = datetime.datetime.fromisoformat(expiry)
                current_date = datetime.datetime.now(pytz.UTC)
                
                # Skip if premium has expired
                if current_date > expiry_date:
                    continue
                    
                # Premium is active
                premium_count += 1
                
                # Format expiry date
                ist_timezone = pytz.timezone('Asia/Kolkata')
                expiry_date_ist = expiry_date.astimezone(ist_timezone)
                formatted_expiry = expiry_date_ist.strftime("%d %b %Y")
                
                # Try to get user info
                try:
                    user_info = await client.get_users(user_id)
                    if user_info.username:
                        user_display = f"@{user_info.username}"
                    else:
                        user_display = f"{user_info.first_name} [{user_id}]"
                except:
                    user_display = f"User ID: {user_id}"
                    
                # Add to list
                premium_users_list.append(f"{premium_count}. {user_display} (Expires: {formatted_expiry})")
                
            except Exception as e:
                logger.error(f"Error processing user {user_id}: {e}")
                continue
        
        # Create message with pagination if needed
        if premium_count == 0:
            await message.reply_text("No active premium users found.")
            return
            
        # Split into chunks of 20 users each
        chunk_size = 20
        chunks = [premium_users_list[i:i + chunk_size] for i in range(0, len(premium_users_list), chunk_size)]
        
        # Send first page
        await message.reply_text(
            f"**Total Premium Users: {premium_count}**\n\n" + 
            "\n".join(chunks[0]) +
            (f"\n\nPage 1/{len(chunks)}" if len(chunks) > 1 else "")
        )
        
        # Send additional pages if needed
        for i, chunk in enumerate(chunks[1:], 2):
            await message.reply_text(
                "\n".join(chunk) +
                f"\n\nPage {i}/{len(chunks)}"
            )
    
    except Exception as e:
        logger.error(f"Error in list_premium_users: {e}")
        await message.reply_text(f"❌ An error occurred: {str(e)}")
