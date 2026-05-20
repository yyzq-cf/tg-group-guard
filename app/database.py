import sqlite3
import os

DB_PATH = os.getenv("DB_PATH", "/data/bot.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    # 启用 WAL 模式，支持 Bot 和 Web 并发读写
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS verification_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            question TEXT,
            answer TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'pending'
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            passed_verification INTEGER DEFAULT 0,
            warning_count INTEGER DEFAULT 0
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            message_text TEXT,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 违禁词表
    c.execute('''
        CREATE TABLE IF NOT EXISTS blocked_keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL UNIQUE,
            enabled INTEGER DEFAULT 1,
            hit_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    # 初始化默认违禁词（如果不存在）
    _init_default_keywords(c)
    # 登录尝试记录表（防暴力破解）
    c.execute('''
        CREATE TABLE IF NOT EXISTS login_attempts (
            ip TEXT PRIMARY KEY,
            attempts INTEGER DEFAULT 0,
            locked_until TIMESTAMP,
            last_attempt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 通用配置表
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 初始化默认欢迎语
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
              ("welcome_message", "🎉 欢迎 {mention} 加入群组！\n\n✅ 验证已通过，你现在可以正常发言了。\n\n请遵守群规，文明交流~"))
    conn.commit()
    conn.close()

def _init_default_keywords(c):
    defaults = [
        "博彩", "彩票", "投注", "兼职", "日赚", "月入", "刷单", "加微信", "加QQ", "qq号", "微信号",
        "推广", "引流", "代理", "包赚", "稳赚", "暴利", "杀猪盘", "资金盘", "空投", "薅羊毛",
        "casino", "bet", "gambling", "earn money", "make money fast", "investment opportunity",
        "porn", "sex", "dating site", "sugar daddy"
    ]
    for kw in defaults:
        c.execute("INSERT OR IGNORE INTO blocked_keywords (keyword) VALUES (?)", (kw,))

def get_setting(key: str, default="") -> str:
    """获取配置项"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    """设置配置项"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))",
              (key, value))
    conn.commit()
    conn.close()
