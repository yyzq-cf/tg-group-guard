import random
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import ContextTypes, ChatMemberHandler, CallbackQueryHandler
from app.database import get_conn, get_setting
from app.config import Config

def _get_verify_timeout():
    val = get_setting("verify_timeout", "")
    return int(val) if val and val.isdigit() else Config.VERIFY_TIMEOUT

logger = logging.getLogger(__name__)

VERIFYING_USERS = {}

def generate_question(session_id: int):
    a = random.randint(1, 10)
    b = random.randint(1, 10)
    answer = a + b
    wrong1 = answer + random.randint(1, 5)
    wrong2 = abs(answer - random.randint(1, 5))
    while wrong2 == answer:
        wrong2 = abs(answer - random.randint(1, 5))
    options = [(str(answer), str(answer)), (str(wrong1), str(wrong1)), (str(wrong2), str(wrong2))]
    random.shuffle(options)
    
    text = f"🛡️ 入群验证\n\n为了确认你不是机器人，请回答：\n{a} + {b} = ?"
    keyboard = [[InlineKeyboardButton(opt[0], callback_data=f"verify:{session_id}:{answer}:{opt[1]}")] for opt in options]
    return text, str(answer), keyboard

async def restrict_new_member(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
            )
        )
    except Exception as e:
        logger.warning(f"Restrict new member failed: {e}")

async def unrestrict_member(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_invite_users=True,
            )
        )
    except Exception as e:
        logger.warning(f"Unrestrict member failed: {e}")

async def kick_member(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        await context.bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
    except Exception as e:
        logger.warning(f"Kick member failed: {e}")

def format_welcome_message(template: str, user) -> str:
    """替换欢迎语中的变量"""
    return template.replace("{mention}", user.mention_html()) \
                   .replace("{name}", user.full_name or "用户") \
                   .replace("{first_name}", user.first_name or "用户") \
                   .replace("{username}", f"@{user.username}" if user.username else user.full_name or "用户") \
                   .replace("{user_id}", str(user.id))

async def send_welcome(chat_id: int, user, context: ContextTypes.DEFAULT_TYPE):
    """发送群内欢迎语，并在 60 秒后自动删除"""
    try:
        template = get_setting("welcome_message", "")
        if not template or not template.strip():
            return
        text = format_welcome_message(template, user)
        msg = await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        # 60 秒后自动删除欢迎语
        delete_delay = int(get_setting("welcome_delete_delay", "60"))
        context.job_queue.run_once(
            auto_delete_welcome,
            when=delete_delay,
            data={"chat_id": chat_id, "message_id": msg.message_id},
            name=f"del_welcome_{msg.message_id}"
        )
    except Exception as e:
        logger.warning(f"Send welcome message failed: {e}")

async def auto_delete_welcome(context: ContextTypes.DEFAULT_TYPE):
    """定时删除欢迎语消息"""
    job = context.job
    data = job.data
    chat_id = data["chat_id"]
    message_id = data["message_id"]
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Auto-deleted welcome message {message_id} in chat {chat_id}")
    except Exception as e:
        logger.warning(f"Failed to auto-delete welcome message {message_id}: {e}")

async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.chat_member:
        return
    
    old = update.chat_member.old_chat_member
    new = update.chat_member.new_chat_member
    
    chat = update.chat_member.chat
    from app.database import is_chat_allowed
    if not is_chat_allowed(chat.id):
        # 如果 Bot 自己被加入非白名单群，自动离开
        if new.user.id == context.bot.id:
            try:
                await context.bot.leave_chat(chat.id)
                logger.warning(f"Left unauthorized chat: {chat.id}")
            except Exception as e:
                logger.warning(f"Failed to leave chat {chat.id}: {e}")
        return
    
    # 只处理真正新加入的（从 left/kicked 变为 member）
    if new.status != "member" or old.status not in ("left", "kicked"):
        return
    
    user = new.user
    chat = update.chat_member.chat
    
    if user.is_bot:
        # 保留群管机器人自身
        if user.id == context.bot.id:
            return
        # 检查白名单
        from app.database import get_setting
        whitelist_str = get_setting("bot_whitelist", "")
        whitelist_ids = {int(x.strip()) for x in whitelist_str.split(",") if x.strip().isdigit()}
        if user.id in whitelist_ids:
            logger.info(f"Whitelisted bot joined: {user.id} ({user.username})")
            return
        # 自动踢出其他机器人
        try:
            await kick_member(chat.id, user.id, context)
            logger.info(f"Auto-kicked bot: {user.id} ({user.username}) from chat {chat.id}")
            await context.bot.send_message(
                chat_id=chat.id,
                text=f"🚫 机器人 @{user.username} 已被自动移出群组。",
            )
        except Exception as e:
            logger.warning(f"Failed to kick bot {user.id}: {e}")
        return
    
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status in ("administrator", "creator"):
            return
    except Exception:
        pass
    
    logger.info(f"New member joined: user={user.id} chat={chat.id}")
    
    # 先限制权限（禁言）
    await restrict_new_member(chat.id, user.id, context)
    
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO verification_sessions (user_id, chat_id, question, answer) VALUES (?, ?, ?, ?)",
              (user.id, chat.id, "", ""))
    conn.commit()
    session_id = c.lastrowid
    conn.close()
    
    VERIFYING_USERS[(chat.id, user.id)] = session_id
    
    text, answer, keyboard = generate_question(session_id)
    markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await context.bot.send_message(chat_id=user.id, text=text, reply_markup=markup)
        context.job_queue.run_once(
            auto_kick,
            when=_get_verify_timeout(),
            data={"user_id": user.id, "chat_id": chat.id, "session_id": session_id},
            name=f"verify_{session_id}"
        )
    except Exception as e:
        logger.error(f"Cannot send verification PM to {user.id}: {e}")
        try:
            msg = await context.bot.send_message(
                chat_id=chat.id,
                text=f"⚠️ {user.mention_html()} 请先私聊我完成验证，否则将被移出群组。",
                parse_mode="HTML"
            )
            # 定时自动删除该提示消息
            delete_delay = int(get_setting("pm_warning_delete_delay", "90"))
            context.job_queue.run_once(
                auto_delete_welcome,
                when=delete_delay,
                data={"chat_id": chat.id, "message_id": msg.message_id},
                name=f"del_pm_warn_{msg.message_id}"
            )
        except Exception:
            pass

async def auto_kick(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data
    user_id = data["user_id"]
    chat_id = data["chat_id"]
    session_id = data["session_id"]
    
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT status FROM verification_sessions WHERE id = ?", (session_id,))
    row = c.fetchone()
    
    if row and row["status"] == "pending":
        c.execute("UPDATE verification_sessions SET status = 'timeout' WHERE id = ?", (session_id,))
        conn.commit()
        
        await kick_member(chat_id, user_id, context)
        
        try:
            await context.bot.send_message(user_id, "⏰ 验证超时，你已被移出群组。可以重新申请加入。")
        except Exception:
            pass
        try:
            await context.bot.send_message(chat_id, f"⏰ 用户验证超时，已被移出群组。")
        except Exception:
            pass
        
        VERIFYING_USERS.pop((chat_id, user_id), None)
    
    conn.close()

async def verification_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split(":")
    if len(data) != 4 or data[0] != "verify":
        return
    
    try:
        session_id = int(data[1])
    except ValueError:
        return
    correct_answer = data[2]
    selected = data[3]
    user_id = query.from_user.id
    
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM verification_sessions WHERE id = ? AND status = 'pending'", (session_id,))
    session = c.fetchone()
    
    if not session:
        await query.edit_message_text("⚠️ 验证已过期或不存在，请重新加入群组。")
        conn.close()
        return
    
    chat_id = session["chat_id"]
    
    if selected == correct_answer:
        c.execute("UPDATE verification_sessions SET status = 'passed' WHERE id = ?", (session_id,))
        c.execute("INSERT OR REPLACE INTO users (user_id, username, passed_verification) VALUES (?, ?, 1)",
                  (user_id, update.effective_user.username))
        conn.commit()
        conn.close()
        
        await query.edit_message_text("✅ 验证通过！你现在可以在群里正常发言了。")
        await unrestrict_member(chat_id, user_id, context)
        # 发送群内欢迎语
        await send_welcome(chat_id, update.effective_user, context)
        VERIFYING_USERS.pop((chat_id, user_id), None)
    else:
        c.execute("UPDATE verification_sessions SET status = 'failed' WHERE id = ?", (session_id,))
        conn.commit()
        conn.close()
        
        await query.edit_message_text("❌ 答案错误，验证失败。你已被移出群组，可以重新加入再试。")
        await kick_member(chat_id, user_id, context)
        VERIFYING_USERS.pop((chat_id, user_id), None)

chat_member_handler = ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER)
verification_callback_handler = CallbackQueryHandler(verification_callback, pattern=r"^verify:")
