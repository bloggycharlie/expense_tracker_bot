"""Configuration and environment variables loader for Expense Tracker Telegram Bot."""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set
import pytz
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Base project directory
BASE_DIR = Path(__file__).resolve().parent

# Core Environment Variables
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# Whitelist Telegram User IDs
_raw_allowed_users = os.getenv("ALLOWED_TELEGRAM_USER_ID", "").strip()
ALLOWED_TELEGRAM_USER_IDS: Set[int] = set()
if _raw_allowed_users:
    for uid_str in _raw_allowed_users.split(","):
        uid_str = uid_str.strip()
        if uid_str.isdigit():
            ALLOWED_TELEGRAM_USER_IDS.add(int(uid_str))

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "expenses.db")).strip()

# Cloud server port (e.g. Render sets PORT)
PORT = int(os.getenv("PORT", "0"))

# Timezone configuration
TIMEZONE_NAME = os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh").strip()
try:
    LOCAL_TIMEZONE = pytz.timezone(TIMEZONE_NAME)
except pytz.UnknownTimeZoneError:
    LOCAL_TIMEZONE = pytz.timezone("Asia/Ho_Chi_Minh")

# =====================================================================
# Expense Categories & Visual Mappings
# =====================================================================
CATEGORIES: List[str] = [
    "Ăn uống",
    "Di chuyển",
    "Mua sắm",
    "Hóa đơn & Dịch vụ",
    "Giải trí",
    "Sức khỏe",
    "Giáo dục",
    "Khác",
]

CATEGORY_EMOJIS: Dict[str, str] = {
    "Ăn uống": "🍜",
    "Di chuyển": "🛵",
    "Mua sắm": "🛍️",
    "Hóa đơn & Dịch vụ": "💡",
    "Giải trí": "🎬",
    "Sức khỏe": "💊",
    "Giáo dục": "📚",
    "Khác": "📦",
}

DEFAULT_CATEGORY = "Khác"
DEFAULT_EMOJI = "📦"


def get_category_emoji(category: str) -> str:
    """Return the emoji icon for a given category name."""
    return CATEGORY_EMOJIS.get(category, DEFAULT_EMOJI)


def format_currency(amount: float | int) -> str:
    """Format numeric amount into Vietnamese currency representation (e.g. 50.000 ₫)."""
    # Round to nearest integer for VND
    rounded_val = int(round(amount))
    formatted = f"{rounded_val:,}".replace(",", ".")
    return f"{formatted} ₫"


def get_current_datetime() -> datetime:
    """Return current datetime localized to configured timezone."""
    return datetime.now(LOCAL_TIMEZONE)


def validate_config() -> None:
    """Validate that critical environment variables are set."""
    missing = []
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not ALLOWED_TELEGRAM_USER_IDS:
        missing.append("ALLOWED_TELEGRAM_USER_ID")

    if missing:
        print("\n" + "=" * 60, file=sys.stderr)
        print(" [!] Missing required environment variables:", file=sys.stderr)
        for var in missing:
            print(f"     - {var}", file=sys.stderr)
        print("\n Please copy .env.example to .env and fill in the values.", file=sys.stderr)
        print("=" * 60 + "\n", file=sys.stderr)
