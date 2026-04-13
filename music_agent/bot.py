import asyncio
import logging
import re
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from music_agent import config
from music_agent import pipeline
from music_agent.downloaders import get_metadata

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

    # Check if user is editing artist/title for a pending request
    pending = context.user_data.get("pending")
    if pending and not _find_url(text):
        return await _handle_metadata_edit(update, context, text)

    url, platform = _find_url(text)
    if not url:
        await update.message.reply_text("Nem találtam támogatott linket az üzenetben.")
        return

    if not url.startswith("http"):
        url = "https://" + url

    status_msg = await update.message.reply_text(f"▸ Metaadatok lekérése ({platform})...")

    try:
        loop = asyncio.get_event_loop()
        meta = await loop.run_in_executor(None, lambda: get_metadata(url))
    except Exception as e:
        logger.exception("Metadata extraction failed")
        await status_msg.edit_text(f"❌ Hiba a metaadatok lekérésekor: {e}")
        return

    # Store pending request
    context.user_data["pending"] = {
        "url": url,
        "platform": platform,
        "title": meta.title,
        "artist": meta.artist,
        "status_msg": status_msg,
        "original_msg": update.message,
    }

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ OK", callback_data="confirm_metadata")],
    ])

    await status_msg.edit_text(
        f"Előadó: {meta.artist}\n"
        f"Cím: {meta.title}\n\n"
        f"Írd át, ha módosítanád (Előadó – Cím):",
        reply_markup=keyboard,
    )


async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button press to confirm metadata."""
    query = update.callback_query
    await query.answer()

    pending = context.user_data.pop("pending", None)
    if not pending:
        await query.edit_message_text("⚠️ Nincs függő kérés.")
        return

    await _run_with_metadata(
        pending["url"],
        pending["title"],
        pending["artist"],
        pending["status_msg"],
        pending["original_msg"],
    )


async def _handle_metadata_edit(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle user typing override for artist/title."""
    pending = context.user_data.get("pending")
    if not pending:
        return

    text = text.strip()

    # Parse "Artist – Title" (em dash, en dash, or hyphen with spaces)
    parts = re.split(r'\s*[–—-]\s*', text, maxsplit=1)
    if len(parts) == 2 and parts[0] and parts[1]:
        artist, title = parts[0].strip(), parts[1].strip()
    else:
        await update.message.reply_text(
            "Formátum: Előadó – Cím\n"
            f"Példa: {pending['artist']} – {pending['title']}"
        )
        return

    context.user_data.pop("pending")

    # Remove the inline keyboard from the old message
    try:
        await pending["status_msg"].edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await _run_with_metadata(
        pending["url"],
        title,
        artist,
        pending["status_msg"],
        pending["original_msg"],
    )


async def _run_with_metadata(url, title, artist, status_msg, original_msg):
    """Run the pipeline with confirmed metadata."""
    loop = asyncio.get_event_loop()
    last_edit_time = 0.0
    last_text = ""
    pending_text = ""

    def sync_status(msg: str):
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
        nonlocal pending_text
        if pending_text and pending_text != last_text:
            msg = pending_text
            pending_text = ""
            sync_status(msg)

    try:
        result = await loop.run_in_executor(
            None,
            lambda: _run_pipeline(url, title, artist, sync_status, flush_pending),
        )

        try:
            await status_msg.delete()
        except Exception:
            pass

        sync_icon = "\n⚠️ iCloud sync timeout" if not result.icloud_synced else ""
        await original_msg.reply_text(
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


def _run_pipeline(url, title, artist, sync_status, flush_pending):
    """Run pipeline in executor thread, flushing pending status at the end."""
    try:
        return pipeline.run(
            url,
            on_status=sync_status,
            title_override=title,
            artist_override=artist,
        )
    finally:
        flush_pending()


def _find_url(text: str) -> tuple[str | None, str | None]:
    """Find a supported URL in the text. Returns (url, platform) or (None, None)."""
    for name, pattern in URL_PATTERNS.items():
        match = pattern.search(text)
        if match:
            return match.group(0), name
    return None, None


def main():
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(handle_confirm, pattern="^confirm_metadata$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started, listening for messages...")
    app.run_polling()


if __name__ == "__main__":
    main()
