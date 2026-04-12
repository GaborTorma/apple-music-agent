import logging
import re

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

    status_msg = await update.message.reply_text(f"Feldolgozás indítása ({platform})...")

    async def on_status(msg: str):
        try:
            await status_msg.edit_text(msg)
        except Exception:
            pass

    try:
        import asyncio
        import functools

        def sync_pipeline():
            statuses = []
            def collect_status(msg):
                statuses.append(msg)
            result = pipeline.run(url, on_status=collect_status)
            return result, statuses

        loop = asyncio.get_event_loop()
        result, statuses = await loop.run_in_executor(None, sync_pipeline)

        for s in statuses[:-1] if statuses else []:
            try:
                await status_msg.edit_text(s)
            except Exception:
                pass

        sync_icon = "" if result.icloud_synced else " (iCloud sync timeout)"
        await status_msg.edit_text(
            f"Kész! Hozzáadva a '{config.PLAYLIST_NAME}' playlisthez!\n"
            f"{result.title} - {result.artist}\n"
            f"Bitráta: {result.bitrate_kbps} kbps{sync_icon}"
        )

    except Exception as e:
        logger.exception("Pipeline failed")
        await status_msg.edit_text(f"Hiba: {e}")


def main():
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started, listening for messages...")
    app.run_polling()


if __name__ == "__main__":
    main()
