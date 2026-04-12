import os
import tempfile
import shutil
from dataclasses import dataclass
from typing import Callable

MUSIC_DIR = "/Users/Shared/Music"

import config
import downloader
import converter
import apple_music


class PipelineError(Exception):
    pass


@dataclass
class PipelineResult:
    title: str
    artist: str
    bitrate_kbps: int
    icloud_synced: bool
    low_bitrate_warning: bool


def run(
    url: str,
    on_status: Callable[[str], None] | None = None,
) -> PipelineResult:
    """Run the full pipeline: download → convert → add to Apple Music → playlist."""
    def status(msg: str):
        if on_status:
            on_status(msg)

    tmp_dir = tempfile.mkdtemp(prefix="music_agent_")
    try:
        # Step 1: Download
        status("Letöltés indítása...")
        dl_result = downloader.download(url, tmp_dir)

        # Step 2: Convert
        status(f"Konvertálás m4a-ba ({dl_result.title})...")
        conv_result = converter.convert(
            audio_path=dl_result.audio_path,
            cover_path=dl_result.cover_path,
            title=dl_result.title,
            artist=dl_result.artist,
            duration_seconds=dl_result.duration_seconds,
            output_dir=tmp_dir,
        )

        if conv_result.low_bitrate_warning:
            status(
                f"Figyelmeztetés: alacsony bitráta ({conv_result.bitrate_kbps} kbps) "
                f"a hosszú időtartam miatt"
            )

        # Step 2.5: Move m4a to persistent location
        os.makedirs(MUSIC_DIR, exist_ok=True)
        final_m4a = os.path.join(MUSIC_DIR, os.path.basename(conv_result.m4a_path))
        shutil.move(conv_result.m4a_path, final_m4a)

        # Step 3: Add to Apple Music from persistent location
        status("Hozzáadás az Apple Music-hoz...")
        persistent_id = apple_music.add_to_library(final_m4a)

        # Step 4: Wait for iCloud sync
        status("iCloud Music Library szinkronizálás (max 20 perc)...")
        icloud_synced = apple_music.wait_for_icloud_sync(persistent_id)

        if not icloud_synced:
            status("Figyelmeztetés: iCloud szinkronizálás timeout, de folytatom...")

        # Step 5: Add to playlist
        status(f"Hozzáadás a '{config.PLAYLIST_NAME}' playlisthez...")
        apple_music.add_to_playlist(persistent_id, config.PLAYLIST_NAME)

        return PipelineResult(
            title=dl_result.title,
            artist=dl_result.artist,
            bitrate_kbps=conv_result.bitrate_kbps,
            icloud_synced=icloud_synced,
            low_bitrate_warning=conv_result.low_bitrate_warning,
        )

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
