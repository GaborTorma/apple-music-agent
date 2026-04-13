import asyncio
import logging
import re
import time

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from music_agent import config
from music_agent import pipeline

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# URL path segment: word chars, hyphens, dots, percent-encoded sequences (%XX)
_PSEG = r'[\w\-%.~]+'

URL_PATTERNS = {
    "YouTube": re.compile(
        r'(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/|music\.youtube\.com/watch\?v=)[\w\-]+'
    ),
    "SoundCloud": re.compile(
        rf'(https?://)?(www\.|m\.)?(soundcloud\.com/{_PSEG}/{_PSEG}|on\.soundcloud\.com/{_PSEG})'
    ),
    "Mixcloud": re.compile(
        rf'(https?://)?(www\.)?mixcloud\.com/{_PSEG}/{_PSEG}/?'
    ),
}

# Minimum interval between Telegram message edits (seconds)
_MIN_EDIT_INTERVAL = 1.5


def _is_allowed(user_id: int) -> bool:
    return user_id in config.ALLOWED_USER_IDS


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        await update.message.reply_text(f"A te user ID-d: {user_id}\nAdd hozzá az ALLOWED_USER_IDS-hez a .env fájlban.")
        return
    await update.message.reply_text(
        "Küldj egy YouTube, SoundCloud vagy Mixcloud linket és hozzáadom a Futás playlisthez!"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return

    text = update.message.text or ""

    url = None
    platform = None
    for name, pattern in URL_PATTERNS.items():
        match = pattern.search(text)
        if match:
            url = match.group(0)
            platform = name
            break

    if not url:
        await update.message.reply_text("Nem találtam támogatott linket az üzenetben.")
        return

    if not url.startswith("http"):
        url = "https://" + url

    status_msg = await update.message.reply_text(f"▸ Feldolgozás indítása ({platform})...")

    loop = asyncio.get_event_loop()
    last_edit_time = 0.0
    last_text = ""
    pending_text = ""

    def sync_status(msg: str):
        """Called from the pipeline thread. Bridges to async Telegram edit with rate limiting."""
        nonlocal last_edit_time, last_text, pending_text

        if msg == last_text:
            return

        now = time.monotonic()
        if now - last_edit_time < _MIN_EDIT_INTERVAL:
            pending_text = msg
            return

        pending_text = ""
        last_text = msg
        last_edit_time = now
        future = asyncio.run_coroutine_threadsafe(
            status_msg.edit_text(msg), loop,
        )
        try:
            future.result(timeout=5)
        except Exception:
            pass

    def flush_pending():
        """Send the last pending status update that was rate-limited."""
        nonlocal pending_text
        if pending_text and pending_text != last_text:
            msg = pending_text
            pending_text = ""
            sync_status(msg)

    try:
        result = await loop.run_in_executor(
            None,
            lambda: _run_pipeline(url, sync_status, flush_pending),
        )

        # Delete the progress message
        try:
            await status_msg.delete()
        except Exception:
            pass

        # Send final result as a new message (triggers notification)
        sync_icon = "\n⚠️ iCloud sync timeout" if not result.icloud_synced else ""
        await update.message.reply_text(
            f"✅ {result.artist} – {result.title}\n"
            f"Hozzáadva: {config.PLAYLIST_NAME} | {result.bitrate_kbps} kbps"
            f"{sync_icon}"
        )

    except Exception as e:
        logger.exception("Pipeline failed")
        try:
            await status_msg.edit_text(f"❌ Hiba: {e}")
        except Exception:
            pass


def _run_pipeline(url: str, sync_status, flush_pending):
    """Run pipeline in executor thread, flushing pending status at the end."""
    try:
        return pipeline.run(url, on_status=sync_status)
    finally:
        flush_pending()


def main():
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started, listening for messages...")
    app.run_polling()


if __name__ == "__main__":
    main()
