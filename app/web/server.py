import os
import sqlite3
import hashlib
import secrets
import logging
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from app.database import get_conn, get_setting, set_setting
from app.config import Config

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("WEB_SECRET", secrets.token_hex(32))

ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD", "admin")

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
    if request.method == "POST":
        data = request.form
        # 保存 .env 配置
        config_file = "/app/.env"
        content = f"""BOT_TOKEN={data.get('bot_token', Config.BOT_TOKEN)}
ADMIN_IDS={data.get('admin_ids', ','.join(map(str, Config.ADMIN_IDS)))}
VERIFY_TIMEOUT={data.get('verify_timeout', Config.VERIFY_TIMEOUT)}
MAX_WARNINGS={data.get('max_warnings', Config.MAX_WARNINGS)}
MUTE_DURATION={data.get('mute_duration', Config.MUTE_DURATION)}
DB_PATH={Config.DB_PATH}
ADMIN_PASSWORD={data.get('admin_password', ADMIN_PASSWORD_HASH)}
"""
        with open(config_file, "w") as f:
            f.write(content)
        # 保存欢迎语到数据库（即时生效）
        welcome_msg = data.get("welcome_message", "").strip()
        set_setting("welcome_message", welcome_msg)
        welcome_delete_delay = data.get("welcome_delete_delay", "60").strip()
        if welcome_delete_delay.isdigit():
            set_setting("welcome_delete_delay", welcome_delete_delay)
        flash("配置已保存", "success")
        return redirect(url_for("settings"))

    welcome_message = get_setting("welcome_message", "")
    welcome_delete_delay = get_setting("welcome_delete_delay", "60")
    return render_template("settings.html", config=Config, admin_password=ADMIN_PASSWORD_HASH, welcome_message=welcome_message, welcome_delete_delay=welcome_delete_delay)

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
