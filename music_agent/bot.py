import asyncio
import logging
import re
import threading
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from music_agent import config
from music_agent import pipeline
from music_agent.pipeline import PipelineCancelled
from music_agent.downloaders import MetadataResult, get_downloader
from music_agent.services.ai_metadata import suggest_metadata

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
_MIN_EDIT_INTERVAL = 1

def _stop_keyboard(msg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Leállítás", callback_data=f"cancel:{msg_id}")],
    ])


def _is_allowed(user_id: int) -> bool:
    return user_id in config.ALLOWED_USER_IDS



async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return

    text = update.message.text or ""

    url, platform = _find_url(text)

    # Check if user is editing a field for a pending request
    editing = context.chat_data.get("editing")
    if editing and not url:
        return await _handle_field_edit(update, context, text)
    if not url:
        await update.message.reply_text("Nem találtam támogatott linket az üzenetben.")
        return

    if not url.startswith("http"):
        url = "https://" + url

    status_msg = await update.message.reply_text(f"▸ Metaadatok lekérése ({platform})...")

    try:
        loop = asyncio.get_event_loop()

        # Phase 1: extract raw metadata from URL
        dl = get_downloader(url)
        raw_meta = await loop.run_in_executor(None, lambda: dl._extract_metadata(url))
        raw_title, raw_artist, duration = dl._parse_metadata(raw_meta)

        # Phase 2: AI enrichment
        await status_msg.edit_text("▸ AI feldolgozás...")
        ai = await loop.run_in_executor(None, lambda: suggest_metadata(raw_meta))

        if ai:
            title = ai.get("title") or raw_title
            artist = ai.get("artist") or raw_artist
            year = ai.get("year", "")
            filename = ai.get("filename", "")
        else:
            title, artist, year, filename = raw_title, raw_artist, "", ""

        if not filename:
            filename = f"{artist} - {title}"

        meta = MetadataResult(
            title=title, artist=artist, year=year,
            filename=filename, duration_seconds=duration,
        )
    except Exception as e:
        logger.exception("Metadata extraction failed")
        await status_msg.edit_text(f"❌ Hiba a metaadatok lekérésekor: {e}")
        return

    # Store pending request keyed by status message ID
    pending = {
        "url": url,
        "platform": platform,
        "title": meta.title,
        "artist": meta.artist,
        "year": meta.year,
        "filename": meta.filename,
        "status_msg": status_msg,
        "original_msg": update.message,
    }
    context.chat_data.setdefault("pendings", {})[status_msg.message_id] = pending

    await _show_confirmation(status_msg, pending)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all inline keyboard button presses."""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("cancel:"):
        msg_id = int(data.split(":")[1])
        cancel_events = context.chat_data.get("cancel_events", {})
        cancel_event = cancel_events.get(msg_id)
        if cancel_event:
            cancel_event.set()
            await query.edit_message_text("Leállítva")
        else:
            await query.edit_message_text("⚠️ Nincs futó folyamat.")
        return

    msg_id = query.message.message_id
    pendings = context.chat_data.get("pendings", {})
    pending = pendings.get(msg_id)
    if not pending:
        await query.edit_message_text("⚠️ Nincs függő kérés.")
        return

    if data == "cancel_pending":
        pendings.pop(msg_id, None)
        name = f"{pending['artist']} – {pending['title']}"
        await query.edit_message_text(f"Megszakítva: {name}")
        return

    if data == "confirm_metadata":
        pendings.pop(msg_id, None)
        await _run_with_metadata(
            context,
            pending["url"],
            pending["title"],
            pending["artist"],
            pending["year"],
            pending["filename"],
            pending["status_msg"],
            pending["original_msg"],
        )
    elif data.startswith("edit_"):
        field = data[5:]  # artist, title, year, filename
        context.chat_data["editing"] = {"field": field, "msg_id": msg_id}
        field_labels = {
            "artist": "Előadó",
            "title": "Cím",
            "year": "Év",
            "filename": "Fájlnév",
        }
        await query.edit_message_text(
            f"Írd be az új értéket ({field_labels.get(field, field)}):",
        )


async def _handle_field_edit(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle user typing a new value for a pending field edit."""
    editing = context.chat_data.pop("editing", None)
    if not editing:
        return

    field = editing["field"]
    msg_id = editing["msg_id"]
    pending = context.chat_data.get("pendings", {}).get(msg_id)
    if not pending:
        return

    text = text.strip()
    if field in ("artist", "title", "year", "filename"):
        pending[field] = text

    if field in ("artist", "title"):
        pending["filename"] = f"{pending['artist']} - {pending['title']}"

    await _show_confirmation(pending["status_msg"], pending)


async def _show_confirmation(status_msg, pending: dict):
    """Show metadata confirmation message with per-field edit buttons."""
    text = (
        f"🎵 Előadó: {pending['artist']}\n"
        f"📀 Cím: {pending['title']}\n"
        f"📅 Év: {pending.get('year') or '—'}\n"
        f"📁 Fájl: {pending.get('filename') or '—'}"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ OK", callback_data="confirm_metadata"),
            InlineKeyboardButton("❌ Mégsem", callback_data="cancel_pending"),
        ],
        [
            InlineKeyboardButton("✏️ Előadó", callback_data="edit_artist"),
            InlineKeyboardButton("✏️ Cím", callback_data="edit_title"),
        ],
        [
            InlineKeyboardButton("✏️ Év", callback_data="edit_year"),
            InlineKeyboardButton("✏️ Fájl", callback_data="edit_filename"),
        ],
    ])
    await status_msg.edit_text(text, reply_markup=keyboard)


async def _run_with_metadata(context, url, title, artist, year, filename, status_msg, original_msg):
    """Run the pipeline with confirmed metadata."""
    cancel_event = threading.Event()
    context.chat_data.setdefault("cancel_events", {})[status_msg.message_id] = cancel_event

    loop = asyncio.get_event_loop()
    last_edit_time = 0.0
    last_text = ""
    pending_text = ""

    def sync_status(msg: str):
        nonlocal last_edit_time, last_text, pending_text

        if cancel_event.is_set() or msg == last_text:
            return

        now = time.monotonic()
        if now - last_edit_time < _MIN_EDIT_INTERVAL:
            pending_text = msg
            return

        pending_text = ""
        last_text = msg
        last_edit_time = now
        future = asyncio.run_coroutine_threadsafe(
            status_msg.edit_text(msg, reply_markup=_stop_keyboard(status_msg.message_id)), loop,
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
            lambda: _run_pipeline(url, title, artist, year, filename, sync_status, flush_pending, cancel_event),
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

    except PipelineCancelled:
        logger.info("Pipeline cancelled by user")
        name = f"{artist} – {title}"
        await asyncio.sleep(0.5)
        try:
            await status_msg.edit_text(f"Leállítva: {name}")
        except Exception:
            pass

    except Exception as e:
        logger.exception("Pipeline failed")
        try:
            await status_msg.edit_text(f"❌ Hiba: {e}")
        except Exception:
            pass

    finally:
        context.chat_data.get("cancel_events", {}).pop(status_msg.message_id, None)


def _run_pipeline(url, title, artist, year, filename, sync_status, flush_pending, cancel_event):
    """Run pipeline in executor thread, flushing pending status at the end."""
    try:
        return pipeline.run(
            url,
            on_status=sync_status,
            title_override=title,
            artist_override=artist,
            year_override=year,
            filename_override=filename,
            cancel_event=cancel_event,
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
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).concurrent_updates(True).build()
    app.add_handler(CallbackQueryHandler(handle_callback, pattern=r"^(confirm_metadata|cancel_pending|cancel:\d+|edit_.+)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started, listening for messages...")
    app.run_polling()


if __name__ == "__main__":
    main()
