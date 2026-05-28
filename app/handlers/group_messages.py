import re
import logging
from datetime import datetime, timezone, timedelta
from telegram import Update, ChatPermissions
from telegram.ext import ContextTypes, MessageHandler, filters
from app.database import get_conn
from app.config import Config

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r'https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+', re.IGNORECASE)
TG_INVITE_PATTERN = re.compile(r't\.me/\+?[a-zA-Z0-9_]+|telegram\.me/\+?[a-zA-Z0-9_]+', re.IGNORECASE)
SHORT_URLS = ["bit.ly", "t.cn", "goo.gl", "tinyurl.com", "short.link", "dlvr.it"]

def get_link_filter_settings():
    """读取链接过滤配置"""
    from app.database import get_setting
    return {
        "enabled": get_setting("link_filter_enabled", "1") == "1",
        "tg_invite": get_setting("link_filter_tg_invite", "1") == "1",
        "short_url": get_setting("link_filter_short_url", "1") == "1",
        "all_url": get_setting("link_filter_all_url", "0") == "1",
    }

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
    
    # 链接过滤
    link_settings = get_link_filter_settings()
    if link_settings["enabled"]:
        urls = URL_PATTERN.findall(text)
        if urls:
            for url in urls:
                # TG 邀请链接
                if link_settings["tg_invite"] and TG_INVITE_PATTERN.search(url):
                    return True, f"TG邀请链接: {url}"
                # 短链接
                if link_settings["short_url"]:
                    for short in SHORT_URLS:
                        if short in url.lower():
                            return True, f"短链接: {url}"
            # 过滤所有链接
            if link_settings["all_url"]:
                return True, f"包含链接: {urls[0]}"
            if len(urls) >= 3:
                return True, "消息包含过多链接"
    
    if WECHAT_PATTERN.search(text):
        return True, "包含微信号"
    if PHONE_PATTERN.search(text):
        return True, "包含手机号"
    if QQ_PATTERN.search(text):
        return True, "包含QQ号"
    
    return False, ""

# ========== 防刷屏 ==========
# 内存中记录用户最近消息时间 { (chat_id, user_id): [timestamp1, timestamp2, ...] }
_USER_MESSAGE_LOGS = {}

def get_antiflood_settings():
    """读取防刷屏配置"""
    from app.database import get_setting
    return {
        "enabled": get_setting("antiflood_enabled", "1") == "1",
        "seconds": int(get_setting("antiflood_seconds", "10")),
        "count": int(get_setting("antiflood_count", "5")),
        "action": get_setting("antiflood_action", "mute"),
    }

def check_antiflood(chat_id: int, user_id: int) -> tuple[bool, str]:
    """检查用户是否刷屏，返回 (是否刷屏, 原因)"""
    settings = get_antiflood_settings()
    if not settings["enabled"]:
        return False, ""
    import time
    key = (chat_id, user_id)
    now = time.time()
    window = settings["seconds"]
    limit = settings["count"]
    if key not in _USER_MESSAGE_LOGS:
        _USER_MESSAGE_LOGS[key] = []
    _USER_MESSAGE_LOGS[key] = [t for t in _USER_MESSAGE_LOGS[key] if now - t < window]
    _USER_MESSAGE_LOGS[key].append(now)
    if len(_USER_MESSAGE_LOGS[key]) >= limit:
        return True, f"防刷屏: {settings['seconds']}秒内发送{len(_USER_MESSAGE_LOGS[key])}条消息"
    return False, ""

def get_auto_replies():
    """从数据库读取启用的自动回复"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT keyword, reply_text FROM auto_replies WHERE enabled = 1")
    rows = c.fetchall()
    conn.close()
    return [(row["keyword"], row["reply_text"]) for row in rows]

def match_auto_reply(text: str) -> str:
    """匹配自动回复，返回回复内容或空字符串"""
    if not text:
        return ""
    replies = get_auto_replies()
    for keyword, reply in replies:
        if keyword.lower() in text.lower():
            return reply
    return ""

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return
    if update.effective_chat.type not in ("group", "supergroup"):
        return
    
    from app.database import is_chat_allowed
    if not is_chat_allowed(update.effective_chat.id):
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
    
    # 防刷屏检查
    flood_flag, flood_reason = check_antiflood(chat_id, user.id)
    if flood_flag:
        await handle_flood_violation(update, context, chat_id, user, flood_reason)
        return
    
    is_spam_flag, reason = is_spam(text)
    if not is_spam_flag:
        # 检查自动回复
        reply = match_auto_reply(text)
        if reply and update.message:
            try:
                await context.bot.send_message(chat_id=chat_id, text=reply, reply_to_message_id=update.message.message_id)
            except Exception as e:
                logger.warning(f"Auto reply failed: {e}")
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

async def handle_flood_violation(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, user, reason: str):
    """处理刷屏违规"""
    logger.info(f"Antiflood triggered by {user.id}: {reason}")
    try:
        await update.message.delete()
    except Exception as e:
        logger.error(f"Delete flood msg failed: {e}")
    mention = user.mention_html()
    settings = get_antiflood_settings()
    action = settings["action"]
    if action == "kick":
        try:
            await context.bot.ban_chat_member(chat_id, user.id)
            await context.bot.unban_chat_member(chat_id, user.id)
            await context.bot.send_message(chat_id, f"🚫 {mention} 因刷屏已被移出群组。", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Kick flood user failed: {e}")
    elif action == "mute":
        try:
            until_date = datetime.now(timezone.utc) + timedelta(seconds=Config.MUTE_DURATION)
            await context.bot.restrict_chat_member(
                chat_id, user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date
            )
            await context.bot.send_message(
                chat_id,
                f"⚠️ {mention} 因刷屏消息已被删除并禁言 {Config.MUTE_DURATION // 60} 分钟。",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Mute flood user failed: {e}")
    else:
        try:
            await context.bot.send_message(
                chat_id,
                f"⚠️ {mention} 请注意，不要刷屏！",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Warn flood user failed: {e}")

message_handler = MessageHandler(filters.TEXT | filters.CAPTION, handle_message)
