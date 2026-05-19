import logging
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes
from app.config import Config
from app.database import get_conn

logger = logging.getLogger(__name__)

def is_admin(user_id: int) -> bool:
    return user_id in Config.ADMIN_IDS

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 无权使用此命令。")
        return
    
    target_id = None
    if update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
    elif context.args:
        try:
            target_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("用法: /ban [用户ID] 或回复用户消息")
            return
    else:
        await update.message.reply_text("用法: /ban [用户ID] 或回复用户消息")
        return
    
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target_id)
        await update.message.reply_text(f"✅ 已封禁用户 {target_id}")
    except Exception as e:
        await update.message.reply_text(f"操作失败: {e}")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("用法: /unban [用户ID]")
        return
    try:
        user_id = int(context.args[0])
        await context.bot.unban_chat_member(update.effective_chat.id, user_id)
        await update.message.reply_text(f"✅ 已解封用户 {user_id}")
    except Exception as e:
        await update.message.reply_text(f"操作失败: {e}")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 无权使用此命令。")
        return
    
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE passed_verification = 1")
    verified = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM violations")
    violations = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM verification_sessions WHERE status = 'timeout'")
    timeouts = c.fetchone()[0]
    conn.close()
    
    text = (
        f"📊 <b>群组守护统计</b>\n\n"
        f"✅ 通过验证人数: {verified}\n"
        f"⚠️ 违规拦截次数: {violations}\n"
        f"⏰ 验证超时次数: {timeouts}"
    )
    await update.message.reply_text(text, parse_mode="HTML")

def get_admin_handlers():
    return [
        CommandHandler("ban", ban_command),
        CommandHandler("unban", unban_command),
        CommandHandler("stats", stats_command),
    ]
