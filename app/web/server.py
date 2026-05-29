import os
import sqlite3
import hashlib
import secrets
import logging
import base64
import io
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from app.database import get_conn, get_setting, set_setting
from app.config import Config

import pyotp
import qrcode

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("WEB_SECRET", secrets.token_hex(32))

def _load_admin_password():
    """优先从数据库 settings 读取密码，没有再读环境变量"""
    pwd = get_setting("admin_password", "")
    if pwd:
        return pwd
    return os.getenv("ADMIN_PASSWORD", "admin")

ADMIN_PASSWORD_HASH = _load_admin_password()

# 防暴力破解配置
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

logger = logging.getLogger(__name__)

def hash_pwd(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()[:32]

def get_client_ip():
    """获取真实客户端 IP（支持反向代理）"""
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    if request.headers.get("X-Real-Ip"):
        return request.headers.get("X-Real-Ip").strip()
    return request.remote_addr

def get_login_attempt(ip: str):
    """获取某 IP 的登录尝试记录"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM login_attempts WHERE ip = ?", (ip,))
    row = c.fetchone()
    conn.close()
    return row

def record_login_attempt(ip: str, success: bool = False):
    """记录登录尝试"""
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now()

    if success:
        # 登录成功，清除记录
        c.execute("DELETE FROM login_attempts WHERE ip = ?", (ip,))
    else:
        row = get_login_attempt(ip)
        if row:
            new_attempts = row["attempts"] + 1
            locked_until = None
            if new_attempts >= MAX_LOGIN_ATTEMPTS:
                locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
                logger.warning(f"IP {ip} locked until {locked_until} after {new_attempts} failed attempts")
            c.execute("""
                UPDATE login_attempts
                SET attempts = ?, locked_until = ?, last_attempt = ?
                WHERE ip = ?
            """, (new_attempts, locked_until, now, ip))
        else:
            c.execute("""
                INSERT INTO login_attempts (ip, attempts, last_attempt)
                VALUES (?, 1, ?)
            """, (ip, now))
    conn.commit()
    conn.close()

def is_ip_locked(ip: str):
    """检查 IP 是否被锁定"""
    row = get_login_attempt(ip)
    if not row or not row["locked_until"]:
        return False, 0
    locked_until = datetime.fromisoformat(row["locked_until"]) if isinstance(row["locked_until"], str) else row["locked_until"]
    if datetime.now() < locked_until:
        remaining = int((locked_until - datetime.now()).total_seconds())
        return True, remaining
    return False, 0

def get_remaining_attempts(ip: str):
    """获取剩余尝试次数"""
    row = get_login_attempt(ip)
    if not row:
        return MAX_LOGIN_ATTEMPTS
    return max(0, MAX_LOGIN_ATTEMPTS - row["attempts"])

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/login", methods=["GET", "POST"])
def login():
    ip = get_client_ip()
    locked, remaining_seconds = is_ip_locked(ip)

    if locked:
        flash(f"登录过于频繁，请 {remaining_seconds // 60} 分 {remaining_seconds % 60} 秒后再试", "danger")
        return render_template("login.html", locked=True, remaining_seconds=remaining_seconds)

    remaining = get_remaining_attempts(ip)

    if request.method == "POST":
        pwd = request.form.get("password", "")
        if hash_pwd(pwd) == hash_pwd(ADMIN_PASSWORD_HASH):
            # 检查是否启用 TOTP 二步验证（需已确认）
            totp_secret = get_setting("totp_secret", "")
            totp_confirmed = get_setting("totp_confirmed", "0")
            if totp_secret and totp_confirmed == "1":
                session["pending_2fa"] = True
                return redirect(url_for("verify_2fa"))
            # 未启用 TOTP，直接登录
            record_login_attempt(ip, success=True)
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        else:
            record_login_attempt(ip, success=False)
            remaining = get_remaining_attempts(ip)
            if remaining == 0:
                locked, remaining_seconds = is_ip_locked(ip)
                flash(f"密码错误。登录过于频繁，已锁定 {LOCKOUT_MINUTES} 分钟", "danger")
                return render_template("login.html", locked=True, remaining_seconds=remaining_seconds)
            else:
                flash(f"密码错误，还剩 {remaining} 次机会", "warning")

    return render_template("login.html", locked=False, remaining_attempts=remaining)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/login/verify-2fa", methods=["GET", "POST"])
def verify_2fa():
    if not session.get("pending_2fa"):
        return redirect(url_for("login"))
    
    ip = get_client_ip()
    totp_secret = get_setting("totp_secret", "")
    if not totp_secret:
        session.clear()
        return redirect(url_for("login"))
    
    totp = pyotp.TOTP(totp_secret)
    
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        if totp.verify(code):
            record_login_attempt(ip, success=True)
            session.pop("pending_2fa", None)
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        else:
            flash("验证码错误，请重试", "danger")
    
    return render_template("verify_2fa.html")

@app.route("/")
@login_required
def dashboard():
    conn = get_conn()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM users WHERE passed_verification = 1")
    verified = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM violations")
    violations = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM verification_sessions WHERE status = 'timeout'")
    timeouts = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM verification_sessions WHERE status = 'passed'")
    verify_passed = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM verification_sessions WHERE status = 'failed'")
    verify_failed = c.fetchone()[0]

    c.execute("""
        SELECT reason, COUNT(*) as cnt FROM violations
        GROUP BY reason ORDER BY cnt DESC LIMIT 8
    """)
    top_reasons = c.fetchall()

    c.execute("""
        SELECT user_id, username, warning_count, passed_verification
        FROM users ORDER BY warning_count DESC LIMIT 10
    """)
    top_users = c.fetchall()

    c.execute("""
        SELECT strftime('%Y-%m-%d', created_at) as day, COUNT(*) as cnt
        FROM violations GROUP BY day ORDER BY day DESC LIMIT 7
    """)
    daily_violations = c.fetchall()

    conn.close()
    return render_template("dashboard.html",
        verified=verified,
        violations=violations,
        timeouts=timeouts,
        verify_passed=verify_passed,
        verify_failed=verify_failed,
        top_reasons=top_reasons,
        top_users=top_users,
        daily_violations=daily_violations,
    )

@app.route("/violations")
@login_required
def violations():
    page = request.args.get("page", 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    search = request.args.get("search", "")

    conn = get_conn()
    c = conn.cursor()

    if search:
        c.execute("""
            SELECT v.*, u.username FROM violations v
            LEFT JOIN users u ON v.user_id = u.user_id
            WHERE v.reason LIKE ? OR v.message_text LIKE ?
            ORDER BY v.created_at DESC LIMIT ? OFFSET ?
        """, (f"%{search}%", f"%{search}%", per_page, offset))
        rows = c.fetchall()
        c.execute("""
            SELECT COUNT(*) FROM violations
            WHERE reason LIKE ? OR message_text LIKE ?
        """, (f"%{search}%", f"%{search}%"))
        total = c.fetchone()[0]
    else:
        c.execute("""
            SELECT v.*, u.username FROM violations v
            LEFT JOIN users u ON v.user_id = u.user_id
            ORDER BY v.created_at DESC LIMIT ? OFFSET ?
        """, (per_page, offset))
        rows = c.fetchall()
        c.execute("SELECT COUNT(*) FROM violations")
        total = c.fetchone()[0]

    conn.close()
    total_pages = (total + per_page - 1) // per_page
    return render_template("violations.html", rows=rows, page=page, total_pages=total_pages, search=search, total=total)

@app.route("/users")
@login_required
def users():
    page = request.args.get("page", 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM users ORDER BY first_seen DESC LIMIT ? OFFSET ?
    """, (per_page, offset))
    rows = c.fetchall()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    conn.close()
    total_pages = (total + per_page - 1) // per_page
    return render_template("users.html", rows=rows, page=page, total_pages=total_pages, total=total)

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    global ADMIN_PASSWORD_HASH
    if request.method == "POST":
        data = request.form
        # 处理密码：留空则不修改
        new_password = data.get("admin_password", "").strip()
        if new_password:
            ADMIN_PASSWORD_HASH = new_password
            set_setting("admin_password", new_password)  # ← 持久化到数据库
        # 保存 .env 配置
        config_file = "/app/.env"
        content = f"""BOT_TOKEN={data.get('bot_token', Config.BOT_TOKEN)}
ADMIN_IDS={data.get('admin_ids', ','.join(map(str, Config.ADMIN_IDS)))}
VERIFY_TIMEOUT={data.get('verify_timeout', Config.VERIFY_TIMEOUT)}
MAX_WARNINGS={data.get('max_warnings', Config.MAX_WARNINGS)}
MUTE_DURATION={data.get('mute_duration', Config.MUTE_DURATION)}
DB_PATH={Config.DB_PATH}
ADMIN_PASSWORD={ADMIN_PASSWORD_HASH}
"""
        with open(config_file, "w") as f:
            f.write(content)
        # 保存欢迎语到数据库（即时生效）
        welcome_msg = data.get("welcome_message", "").strip()
        set_setting("welcome_message", welcome_msg)
        welcome_delete_delay = data.get("welcome_delete_delay", "60").strip()
        if welcome_delete_delay.isdigit():
            set_setting("welcome_delete_delay", welcome_delete_delay)

        # 保存链接过滤设置
        set_setting("link_filter_enabled", "1" if data.get("link_filter_enabled") else "0")
        set_setting("link_filter_tg_invite", "1" if data.get("link_filter_tg_invite") else "0")
        set_setting("link_filter_short_url", "1" if data.get("link_filter_short_url") else "0")
        set_setting("link_filter_all_url", "1" if data.get("link_filter_all_url") else "0")

        # 保存防刷屏设置
        set_setting("antiflood_enabled", "1" if data.get("antiflood_enabled") else "0")
        antiflood_seconds = data.get("antiflood_seconds", "10").strip()
        if antiflood_seconds.isdigit():
            set_setting("antiflood_seconds", str(max(3, min(300, int(antiflood_seconds)))))
        antiflood_count = data.get("antiflood_count", "5").strip()
        if antiflood_count.isdigit():
            set_setting("antiflood_count", str(max(2, min(50, int(antiflood_count)))))
        set_setting("antiflood_action", data.get("antiflood_action", "mute"))

        # 保存白名单群
        allowed_chat_ids = data.get("allowed_chat_ids", "").strip()
        set_setting("allowed_chat_ids", allowed_chat_ids)

        # 保存机器人白名单
        bot_whitelist = data.get("bot_whitelist", "").strip()
        set_setting("bot_whitelist", bot_whitelist)

        flash("配置已保存", "success")
        return redirect(url_for("settings"))

    welcome_message = get_setting("welcome_message", "")
    welcome_delete_delay = get_setting("welcome_delete_delay", "60")
    link_settings = {
        "enabled": get_setting("link_filter_enabled", "1") == "1",
        "tg_invite": get_setting("link_filter_tg_invite", "1") == "1",
        "short_url": get_setting("link_filter_short_url", "1") == "1",
        "all_url": get_setting("link_filter_all_url", "0") == "1",
    }
    antiflood_settings = {
        "enabled": get_setting("antiflood_enabled", "1") == "1",
        "seconds": get_setting("antiflood_seconds", "10"),
        "count": get_setting("antiflood_count", "5"),
        "action": get_setting("antiflood_action", "mute"),
    }
    allowed_chat_ids = get_setting("allowed_chat_ids", "")
    bot_whitelist = get_setting("bot_whitelist", "")
    totp_secret = get_setting("totp_secret", "")
    totp_confirmed = get_setting("totp_confirmed", "0")
    totp_enabled = bool(totp_secret and totp_confirmed == "1")
    totp_pending = bool(totp_secret and totp_confirmed != "1")
    totp_qr = ""
    totp_secret_display = ""
    if totp_pending:
        totp_obj = pyotp.TOTP(totp_secret)
        uri = totp_obj.provisioning_uri(name="admin", issuer_name="TG-Group-Guard")
        img = qrcode.make(uri)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        totp_qr = f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"
        totp_secret_display = totp_secret
    return render_template("settings.html", config=Config, admin_password=ADMIN_PASSWORD_HASH,
                           welcome_message=welcome_message, welcome_delete_delay=welcome_delete_delay,
                           link_settings=link_settings, antiflood_settings=antiflood_settings,
                           allowed_chat_ids=allowed_chat_ids, bot_whitelist=bot_whitelist,
                           totp_enabled=totp_enabled, totp_pending=totp_pending,
                           totp_qr=totp_qr, totp_secret_display=totp_secret_display)

# ==================== TOTP 二步验证 ====================

@app.route("/settings/2fa/enable", methods=["POST"])
@login_required
def enable_2fa():
    """启用 TOTP：生成密钥，返回 QR 码"""
    secret = pyotp.random_base32()
    set_setting("totp_secret", secret)
    set_setting("totp_confirmed", "0")  # 待确认
    # 生成 provisioning URI
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name="admin", issuer_name="TG-Group-Guard")
    # 生成 QR 码为 base64 data URL
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    qr_b64 = base64.b64encode(buf.getvalue()).decode()
    return jsonify({"success": True, "secret": secret, "qr": f"data:image/png;base64,{qr_b64}"})

@app.route("/settings/2fa/confirm", methods=["POST"])
@login_required
def confirm_2fa():
    """确认 TOTP 设置：验证用户能用当前 secret 生成正确验证码"""
    code = request.form.get("code", "").strip()
    secret = get_setting("totp_secret", "")
    if not secret:
        return jsonify({"success": False, "error": "2FA 未启用，请先点击启用"}), 400
    totp = pyotp.TOTP(secret)
    if not totp.verify(code):
        return jsonify({"success": False, "error": "验证码错误"}), 400
    set_setting("totp_confirmed", "1")
    return jsonify({"success": True, "message": "验证码正确，2FA 已确认启用"})

@app.route("/settings/2fa/disable", methods=["POST"])
@login_required
def disable_2fa():
    """禁用 TOTP：需要输入当前验证码确认"""
    code = request.form.get("code", "").strip()
    secret = get_setting("totp_secret", "")
    if not secret:
        return jsonify({"success": False, "error": "2FA 未启用"}), 400
    totp = pyotp.TOTP(secret)
    if not totp.verify(code):
        return jsonify({"success": False, "error": "验证码错误"}), 400
    set_setting("totp_secret", "")
    set_setting("totp_confirmed", "")
    return jsonify({"success": True, "message": "2FA 已禁用"})

@app.route("/settings/2fa/cancel", methods=["POST"])
@login_required
def cancel_2fa():
    """取消待确认的 TOTP 设置"""
    set_setting("totp_secret", "")
    set_setting("totp_confirmed", "")
    return jsonify({"success": True, "message": "2FA 设置已取消"})

# ==================== 安全日志 ====================

@app.route("/security")
@login_required
def security_log():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT ip, attempts, locked_until, last_attempt
        FROM login_attempts
        ORDER BY last_attempt DESC
    """)
    raw_rows = c.fetchall()
    conn.close()

    # 在 Python 中计算锁定状态（避免 SQLite 与 Python 时区差异）
    rows = []
    now = datetime.now()
    for row in raw_rows:
        is_locked = False
        if row["locked_until"]:
            locked_until = datetime.fromisoformat(row["locked_until"]) if isinstance(row["locked_until"], str) else row["locked_until"]
            is_locked = now < locked_until
        rows.append({
            "ip": row["ip"],
            "attempts": row["attempts"],
            "is_locked": is_locked,
            "locked_until": row["locked_until"],
            "last_attempt": row["last_attempt"],
        })

    return render_template("security.html", rows=rows, max_attempts=MAX_LOGIN_ATTEMPTS, lockout_minutes=LOCKOUT_MINUTES)

@app.route("/api/security/unlock/<ip>", methods=["POST"])
@login_required
def unlock_ip(ip):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM login_attempts WHERE ip = ?", (ip,))
    conn.commit()
    conn.close()
    flash(f"已解锁 IP: {ip}", "success")
    return redirect(url_for("security_log"))

# ==================== 违禁词管理 ====================

@app.route("/keywords")
@login_required
def keywords():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM blocked_keywords ORDER BY hit_count DESC, created_at DESC")
    rows = c.fetchall()
    c.execute("SELECT COUNT(*) FROM blocked_keywords WHERE enabled = 1")
    enabled_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM blocked_keywords")
    total_count = c.fetchone()[0]
    conn.close()
    return render_template("keywords.html", rows=rows, enabled_count=enabled_count, total_count=total_count)

@app.route("/api/keywords", methods=["POST"])
@login_required
def api_add_keyword():
    data = request.get_json() or request.form
    keyword = (data.get("keyword") or "").strip()
    if not keyword:
        return jsonify({"success": False, "error": "关键词不能为空"}), 400
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO blocked_keywords (keyword) VALUES (?)", (keyword,))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": f"已添加违禁词: {keyword}"})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"success": False, "error": "该关键词已存在"}), 409

@app.route("/api/keywords/<int:kid>", methods=["DELETE"])
@login_required
def api_delete_keyword(kid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM blocked_keywords WHERE id = ?", (kid,))
    conn.commit()
    deleted = c.rowcount
    conn.close()
    if deleted:
        return jsonify({"success": True, "message": "已删除"})
    return jsonify({"success": False, "error": "关键词不存在"}), 404

@app.route("/api/keywords/<int:kid>/toggle", methods=["POST"])
@login_required
def api_toggle_keyword(kid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE blocked_keywords SET enabled = CASE WHEN enabled = 1 THEN 0 ELSE 1 END WHERE id = ?", (kid,))
    conn.commit()
    updated = c.rowcount
    c.execute("SELECT enabled, keyword FROM blocked_keywords WHERE id = ?", (kid,))
    row = c.fetchone()
    conn.close()
    if updated and row:
        status = "启用" if row["enabled"] else "禁用"
        return jsonify({"success": True, "enabled": bool(row["enabled"]), "keyword": row["keyword"], "message": f"已{status}: {row['keyword']}"})
    return jsonify({"success": False, "error": "关键词不存在"}), 404

# ==================== 自动回复管理 ====================

@app.route("/auto_replies")
@login_required
def auto_replies():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM auto_replies ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return render_template("auto_replies.html", rows=rows)

@app.route("/api/auto_replies", methods=["POST"])
@login_required
def api_add_auto_reply():
    data = request.get_json() or request.form
    keyword = (data.get("keyword") or "").strip()
    reply_text = (data.get("reply_text") or "").strip()
    if not keyword or not reply_text:
        return jsonify({"success": False, "error": "关键词和回复内容不能为空"}), 400
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO auto_replies (keyword, reply_text) VALUES (?, ?)", (keyword, reply_text))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"已添加自动回复: {keyword}"})

@app.route("/api/auto_replies/<int:rid>", methods=["DELETE"])
@login_required
def api_delete_auto_reply(rid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM auto_replies WHERE id = ?", (rid,))
    conn.commit()
    deleted = c.rowcount
    conn.close()
    if deleted:
        return jsonify({"success": True, "message": "已删除"})
    return jsonify({"success": False, "error": "规则不存在"}), 404

@app.route("/api/auto_replies/<int:rid>/toggle", methods=["POST"])
@login_required
def api_toggle_auto_reply(rid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE auto_replies SET enabled = CASE WHEN enabled = 1 THEN 0 ELSE 1 END WHERE id = ?", (rid,))
    conn.commit()
    updated = c.rowcount
    c.execute("SELECT enabled, keyword FROM auto_replies WHERE id = ?", (rid,))
    row = c.fetchone()
    conn.close()
    if updated and row:
        status = "启用" if row["enabled"] else "禁用"
        return jsonify({"success": True, "enabled": bool(row["enabled"]), "keyword": row["keyword"], "message": f"已{status}: {row['keyword']}"})
    return jsonify({"success": False, "error": "规则不存在"}), 404

@app.route("/api/stats")
@login_required
def api_stats():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE passed_verification = 1")
    verified = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM violations")
    violations = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM verification_sessions WHERE status = 'pending'")
    pending = c.fetchone()[0]
    conn.close()
    return {"verified": verified, "violations": violations, "pending_verify": pending}

def run_web(host="0.0.0.0", port=8080):
    app.run(host=host, port=port, debug=False, use_reloader=False)
