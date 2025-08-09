import os
import time
from datetime import datetime, timedelta
from pytz import timezone
from pyrogram import Client
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web
from flask import Flask, jsonify
from config import Config
from route import web_server
import pyrogram.utils

pyrogram.utils.MIN_CHANNEL_ID = -1002826558276

flask_app = Flask(__name__)

@flask_app.route('/uptime', methods=['GET'])
def uptime():
    return jsonify({"status": "ok"}), 200

def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("FLASK_PORT", 5000)))

SUPPORT_CHAT = int(os.environ.get("SUPPORT_CHAT", "-1002826558276"))
PORT = Config.PORT

class Bot(Client):
    def __init__(self):
        super().__init__(
            name="codeflixbots",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            bot_token=Config.BOT_TOKEN,
            workers=200,
            plugins={"root": "plugins"},
            sleep_threshold=15,
        )
        self.start_time = time.time()

    async def start(self, *args, **kwargs):
        await super().start(*args, **kwargs)
        me = await self.get_me()
        self.mention = me.mention
        self.username = me.username  
        self.uptime = Config.BOT_UPTIME     

        if Config.WEBHOOK:
            app = web.AppRunner(await web_server())
            await app.setup()       
            await web.TCPSite(app, "0.0.0.0", PORT).start()     

        uptime_seconds = int(time.time() - self.start_time)
        uptime_string = str(timedelta(seconds=uptime_seconds))

        for chat_id in [Config.LOG_CHANNEL, SUPPORT_CHAT]:
            try:
                curr = datetime.now(timezone("Asia/Kolkata"))
                await self.send_photo(
                    chat_id=chat_id,
                    photo=Config.START_PIC,
                    caption=(
                        "**Dᴇɴᴊɪ ɪs ʀᴇsᴛᴀʀᴛᴇᴅ ᴀɢᴀɪɴ  !**\n\n"
                        f"ɪ ᴅɪᴅɴ'ᴛ sʟᴇᴘᴛ sɪɴᴄᴇ​: `{uptime_string}`"
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("ᴜᴘᴅᴀᴛᴇs", url="https://t.me/manga_Campus_chat")]]
                    )
                )
            except Exception as e:
                print(f"Failed to send message in chat {chat_id}: {e}")

Bot().run()
