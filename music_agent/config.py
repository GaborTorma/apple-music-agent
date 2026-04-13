import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER_IDS = [int(uid.strip()) for uid in os.environ.get("ALLOWED_USER_IDS", "0").split(",")]

PLAYLIST_NAME = os.environ.get("PLAYLIST_NAME", "Futás")
MUSIC_DIR = os.environ.get("MUSIC_DIR", "")
MAX_BITRATE_KBPS = 192
MAX_FILE_SIZE_BYTES = 195 * 1024 * 1024  # 195 MB
MIN_BITRATE_KBPS = 64

ICLOUD_POLL_INTERVAL_SECONDS = 60
ICLOUD_POLL_TIMEOUT_SECONDS = 20 * 60  # 20 minutes

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:e2b")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
