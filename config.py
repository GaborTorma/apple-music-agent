import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER_IDS = [int(uid.strip()) for uid in os.environ.get("ALLOWED_USER_IDS", "0").split(",")]

PLAYLIST_NAME = os.environ.get("PLAYLIST_NAME", "Futás")
MAX_BITRATE_KBPS = 192
MAX_FILE_SIZE_BYTES = 195 * 1024 * 1024  # 195 MB
MIN_BITRATE_KBPS = 64

ICLOUD_POLL_INTERVAL_SECONDS = 60
ICLOUD_POLL_TIMEOUT_SECONDS = 20 * 60  # 20 minutes
