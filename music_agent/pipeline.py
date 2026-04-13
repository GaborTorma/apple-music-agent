import os
import tempfile
import shutil
import threading
from dataclasses import dataclass
from typing import Callable

from music_agent import config
from music_agent.downloaders import get_downloader
from music_agent import converter
from music_agent.services import apple_music


class PipelineError(Exception):
    pass


class PipelineCancelled(Exception):
    pass


@dataclass
class PipelineResult:
    title: str
    artist: str
    bitrate_kbps: int
    icloud_synced: bool
    low_bitrate_warning: bool


STEPS = [
    "Letöltés",
    "Konvertálás",
    "Apple Music",
    "iCloud szinkronizálás",
    "Playlist",
]


def _format_status(
    header: str | None,
    current_step: int,
    step_detail: str,
    completed_steps: int,
) -> str:
    """Format the multi-line status message.

    completed_steps: all steps with index < this value are shown as done.
    """
    lines = []
    if header:
        lines.append(header)
        lines.append("")

    for i, name in enumerate(STEPS):
        if i < completed_steps:
            lines.append(f"✓ {name}")
        elif i == current_step:
            if step_detail:
                lines.append(f"▸ {name} {step_detail}")
            else:
                lines.append(f"▸ {name}...")
        else:
            lines.append(f"  {name}")

    return "\n".join(lines)


def _format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def run(
    url: str,
    on_status: Callable[[str], None] | None = None,
    title_override: str | None = None,
    artist_override: str | None = None,
    year_override: str | None = None,
    filename_override: str | None = None,
    cancel_event: threading.Event | None = None,
) -> PipelineResult:
    """Run the full pipeline: download → convert → add to Apple Music → playlist."""
    header = f"{artist_override} – {title_override}" if artist_override and title_override else None
    current_step = 0
    step_detail = ""
    completed = 0

    def check_cancel():
        if cancel_event and cancel_event.is_set():
            raise PipelineCancelled("Leállítva")

    def emit(force: bool = False):
        if on_status:
            on_status(_format_status(header, current_step, step_detail, completed))

    def set_step(index: int, detail: str = ""):
        nonlocal current_step, step_detail, completed
        check_cancel()
        completed = index
        current_step = index
        step_detail = detail
        emit()

    def update_detail(detail: str):
        nonlocal step_detail
        check_cancel()
        step_detail = detail
        emit()

    tmp_dir = tempfile.mkdtemp(prefix="music_agent_")
    try:
        # Step 0: Download (auto-selects downloader based on URL)
        set_step(0)
        dl = get_downloader(url)

        def on_dl_progress(pct: float):
            update_detail(f"{pct:.0f}%")

        try:
            dl_result = dl.download(url, tmp_dir, on_progress=on_dl_progress, cancel_event=cancel_event)
        except Exception:
            if cancel_event and cancel_event.is_set():
                raise PipelineCancelled("Leállítva")
            raise

        # Apply overrides
        if title_override:
            dl_result.title = title_override
        if artist_override:
            dl_result.artist = artist_override

        header = f"{dl_result.artist} – {dl_result.title}"

        # Step 1: Convert
        set_step(1)

        def on_conv_progress(pct: float):
            update_detail(f"{pct:.0f}%")

        try:
            conv_result = converter.convert(
                audio_path=dl_result.audio_path,
                cover_path=dl_result.cover_path,
                title=dl_result.title,
                artist=dl_result.artist,
                year=year_override or "",
                filename=filename_override or "",
                duration_seconds=dl_result.duration_seconds,
                output_dir=tmp_dir,
                on_progress=on_conv_progress,
                cancel_event=cancel_event,
            )
        except Exception:
            if cancel_event and cancel_event.is_set():
                raise PipelineCancelled("Leállítva")
            raise

        if conv_result.low_bitrate_warning:
            update_detail(f"⚠ {conv_result.bitrate_kbps} kbps (alacsony)")

        # Step 1.5: Move m4a to persistent location (if configured)
        check_cancel()
        if config.MUSIC_DIR:
            os.makedirs(config.MUSIC_DIR, exist_ok=True)
            final_m4a = os.path.join(config.MUSIC_DIR, os.path.basename(conv_result.m4a_path))
            shutil.move(conv_result.m4a_path, final_m4a)
        else:
            final_m4a = conv_result.m4a_path

        # Step 2: Add to Apple Music
        set_step(2)
        persistent_id = apple_music.add_to_library(final_m4a)

        # Step 3: Wait for iCloud sync
        set_step(3)

        def on_sync_progress(elapsed: float, timeout: float):
            update_detail(f"{_format_time(elapsed)} / {_format_time(timeout)}")

        icloud_synced = apple_music.wait_for_icloud_sync(
            persistent_id, on_progress=on_sync_progress, cancel_event=cancel_event,
        )

        # If cancelled during sync, remove the track from Apple Music
        if cancel_event and cancel_event.is_set():
            apple_music.remove_from_library(persistent_id)
            raise PipelineCancelled("Leállítva")

        if not icloud_synced:
            update_detail("⚠ timeout")

        # Step 4: Add to playlist
        set_step(4)
        apple_music.add_to_playlist(persistent_id, config.PLAYLIST_NAME)

        # Mark all done
        completed = len(STEPS)
        emit()

        return PipelineResult(
            title=dl_result.title,
            artist=dl_result.artist,
            bitrate_kbps=conv_result.bitrate_kbps,
            icloud_synced=icloud_synced,
            low_bitrate_warning=conv_result.low_bitrate_warning,
        )

    finally:
        if config.MUSIC_DIR:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        # If no MUSIC_DIR, keep temp dir — Apple Music references the file there
