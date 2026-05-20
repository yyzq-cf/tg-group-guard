import os
import sqlite3
import hashlib
import secrets
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from app.database import get_conn, DB_PATH
from app.config import Config

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("WEB_SECRET", secrets.token_hex(32))

ADMIN_PASSWORD_HASH=os.getenv("ADMIN_PASSWORD", "admin")

def hash_pwd(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()[:32]

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if hash_pwd(pwd) == hash_pwd(ADMIN_PASSWORD_HASH):
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        flash("密码错误", "danger")
    return render_template("login.html")

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
    config_file = "/app/.env"
    if request.method == "POST":
        data = request.form
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
        flash("配置已保存（重启后生效）", "success")
        return redirect(url_for("settings"))

    return render_template("settings.html", config=Config, admin_password=ADMIN_PASSWORD_HASH)

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
