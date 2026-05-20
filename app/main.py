import logging
import threading
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder
from app.config import Config
from app.database import init_db
from app.handlers.join_request import chat_member_handler, verification_callback_handler
from app.handlers.group_messages import message_handler
from app.handlers.admin_commands import get_admin_handlers

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def run_web():
    from app.web.server import run_web as _run_web
    _run_web(host="0.0.0.0", port=8080)

def main():
    init_db()

    # 启动 Web 管理后台（守护线程）
    web_thread = threading.Thread(target=run_web, name="web", daemon=True)
    web_thread.start()
    logger.info("Web admin panel started on http://0.0.0.0:8080")

    # 在主线程启动 Telegram Bot（需要信号处理器）
    application = ApplicationBuilder().token(Config.BOT_TOKEN).build()
    application.add_handler(chat_member_handler)
    application.add_handler(verification_callback_handler)
    application.add_handler(message_handler)
    for handler in get_admin_handlers():
        application.add_handler(handler)

    logger.info("Bot started. Polling for updates...")
    application.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
