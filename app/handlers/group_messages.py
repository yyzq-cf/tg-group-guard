import re
import logging
from datetime import datetime, timezone, timedelta
from telegram import Update, ChatPermissions
from telegram.ext import ContextTypes, MessageHandler, filters
from app.database import get_conn
from app.config import Config

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r'https?://\S+|www\.\S+', re.IGNORECASE)
SHORT_URLS = ["bit.ly", "t.cn", "goo.gl", "tinyurl.com", "short.link", "dlvr.it", "t.me/+"]

WECHAT_PATTERN = re.compile(r'(微信|vx|wechat|薇信|威信)[:\s]*[a-zA-Z0-9_\-]+', re.IGNORECASE)
PHONE_PATTERN = re.compile(r'[\+]?\d{11,}')
QQ_PATTERN = re.compile(r'[Qq][Qq][:\s]*\d{5,}')

def get_blocked_keywords():
    """从数据库读取启用的违禁词"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT keyword FROM blocked_keywords WHERE enabled = 1")
    keywords = [row["keyword"] for row in c.fetchall()]
    conn.close()
    return keywords

def record_keyword_hit(keyword: str):
    """记录关键词命中次数"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE blocked_keywords SET hit_count = hit_count + 1 WHERE keyword = ?", (keyword,))
    conn.commit()
    conn.close()

def is_spam(text: str) -> tuple[bool, str]:
    if not text:
        return False, ""
    lower = text.lower()
    
    # 动态读取数据库中的违禁词
    blocked_keywords = get_blocked_keywords()
    for kw in blocked_keywords:
        if kw.lower() in lower:
            record_keyword_hit(kw)
            return True, f"关键词拦截: {kw}"
    
    urls = URL_PATTERN.findall(text)
    if urls:
        for url in urls:
            for short in SHORT_URLS:
                if short in url.lower():
                    return True, f"短链接/邀请链接: {url}"
        if len(urls) >= 3:
            return True, "消息包含过多链接"
    
    if WECHAT_PATTERN.search(text):
        return True, "包含微信号"
    if PHONE_PATTERN.search(text):
        return True, "包含手机号"
    if QQ_PATTERN.search(text):
        return True, "包含QQ号"
    
    return False, ""

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return
    if update.effective_chat.type not in ("group", "supergroup"):
        return
    
    chat_id = update.effective_chat.id
    user = update.effective_user
    if not user:
        return
    
    try:
        member = await update.effective_chat.get_member(user.id)
        if member.status in ("administrator", "creator"):
            return
    except Exception:
        pass
    
    text = update.message.text or update.message.caption or ""
    is_spam_flag, reason = is_spam(text)
    if not is_spam_flag:
        return
    
    logger.info(f"Spam from {user.id}: {reason}")
    
    try:
        await update.message.delete()
    except Exception as e:
        logger.error(f"Delete msg failed: {e}")
    
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO violations (user_id, chat_id, message_text, reason) VALUES (?, ?, ?, ?)",
              (user.id, chat_id, text[:500], reason))
    c.execute("SELECT warning_count FROM users WHERE user_id = ?", (user.id,))
    row = c.fetchone()
    warnings = (row["warning_count"] if row else 0) + 1
    c.execute("INSERT OR REPLACE INTO users (user_id, username, warning_count, passed_verification) VALUES (?, ?, ?, COALESCE((SELECT passed_verification FROM users WHERE user_id=?), 0))",
              (user.id, user.username, warnings, user.id))
    conn.commit()
    conn.close()
    
    mention = user.mention_html()
    
    if warnings >= Config.MAX_WARNINGS:
        try:
            await context.bot.ban_chat_member(chat_id, user.id)
            await context.bot.send_message(chat_id, f"🚫 用户 {mention} 因多次违规已被永久封禁。", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ban failed: {e}")
    else:
        try:
            until_date = datetime.now(timezone.utc) + timedelta(seconds=Config.MUTE_DURATION)
            await context.bot.restrict_chat_member(
                chat_id, user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date
            )
            await context.bot.send_message(
                chat_id,
                f"⚠️ {mention} 的违规消息已被删除。\n<b>原因:</b> {reason}\n<b>警告:</b> {warnings}/{Config.MAX_WARNINGS}\n再违规将被永久封禁。",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Restrict failed: {e}")

message_handler = MessageHandler(filters.TEXT | filters.CAPTION, handle_message)
