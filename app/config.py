import os

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS = []
    _admin_ids_str = os.getenv("ADMIN_IDS", "")
    if _admin_ids_str:
        ADMIN_IDS = [int(x.strip()) for x in _admin_ids_str.split(",") if x.strip().isdigit()]
    
    VERIFY_TIMEOUT = int(os.getenv("VERIFY_TIMEOUT", "60"))
    MAX_WARNINGS = int(os.getenv("MAX_WARNINGS", "3"))
    MUTE_DURATION = int(os.getenv("MUTE_DURATION", "300"))
    DB_PATH = os.getenv("DB_PATH", "/data/bot.db")
