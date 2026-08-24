import os
import tempfile
import shutil
import threading
from dataclasses import dataclass
from typing import Callable

from music_agent import config
from music_agent import file_lock
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
    "Hozzáadás az Apple Music-hoz",
    "Szinkronizálás az iCloud Music-ba",
    "Hozzáadás a lejátszási listához",
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
        if lock:
            lock.refresh()
        step_detail = detail
        emit()

    tmp_dir = tempfile.mkdtemp(prefix="music_agent_")
    lock = None
    try:
        # Step 0: Download (auto-selects downloader based on URL)
        set_step(0)

        # MUSIC_DIR is shared with the other agent: the file may already be there,
        # or that agent may be downloading it right now.
        library_path = None
        if config.MUSIC_DIR and (filename_override or title_override):
            os.makedirs(config.MUSIC_DIR, exist_ok=True)
            library_path = converter.target_path(
                filename_override or title_override, config.MUSIC_DIR,
            )
            if not os.path.exists(library_path):
                lock = file_lock.TargetLock(library_path)
                if not lock.acquire():
                    file_lock.wait_for(
                        library_path,
                        on_wait=lambda who, waited: update_detail(
                            f"{who} tölti, várakozás {_format_time(waited)}"
                        ),
                        cancel_event=cancel_event,
                    )
                    check_cancel()
                    # The other run may have died without producing the file
                    if not os.path.exists(library_path):
                        lock.acquire()

        if library_path and os.path.exists(library_path):
            title = title_override or os.path.splitext(os.path.basename(library_path))[0]
            artist = artist_override or ""
            final_m4a = library_path
            bitrate_kbps = converter.probe_bitrate(final_m4a)
            low_bitrate_warning = 0 < bitrate_kbps < config.MIN_BITRATE_KBPS
            header = f"{artist} – {title}" if artist else title
            set_step(0, "kihagyva – a fájl már megvan")
            # download and convert are both done for us
            completed = 2
        else:
            dl = get_downloader(url)

            def on_dl_progress(pct: float):
                update_detail(f"{pct:.0f}%")

            try:
                dl_result = dl.download(
                    url, tmp_dir, on_progress=on_dl_progress, cancel_event=cancel_event,
                    on_notice=update_detail,
                )
            except Exception:
                if cancel_event and cancel_event.is_set():
                    raise PipelineCancelled("Leállítva")
                raise

            title = title_override or dl_result.title
            artist = artist_override or dl_result.artist
            header = f"{artist} – {title}"

            # Step 1: Convert
            set_step(1)

            def on_conv_progress(pct: float):
                update_detail(f"{pct:.0f}%")

            try:
                conv_result = converter.convert(
                    audio_path=dl_result.audio_path,
                    cover_path=dl_result.cover_path,
                    title=title,
                    artist=artist,
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

            bitrate_kbps = conv_result.bitrate_kbps
            low_bitrate_warning = conv_result.low_bitrate_warning
            if low_bitrate_warning:
                update_detail(f"⚠ {bitrate_kbps} kbps (alacsony)")

            # Step 1.5: Move m4a to persistent location (if configured)
            check_cancel()
            if config.MUSIC_DIR:
                os.makedirs(config.MUSIC_DIR, exist_ok=True)
                final_m4a = library_path or os.path.join(
                    config.MUSIC_DIR, os.path.basename(conv_result.m4a_path),
                )
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

        # Uploading can replace the track under a new persistent ID — keep the current one
        icloud_synced, persistent_id = apple_music.wait_for_icloud_sync(
            persistent_id, title, artist, on_progress=on_sync_progress, cancel_event=cancel_event,
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
            title=title,
            artist=artist,
            bitrate_kbps=bitrate_kbps,
            icloud_synced=icloud_synced,
            low_bitrate_warning=low_bitrate_warning,
        )

    finally:
        if lock:
            lock.release()
        if config.MUSIC_DIR:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        # If no MUSIC_DIR, keep temp dir — Apple Music references the file there
