import json
import logging
import re
import subprocess
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from music_agent.services import ytdlp_update

logger = logging.getLogger(__name__)

# How many non-progress yt-dlp output lines to keep for error reporting
ERROR_TAIL_LINES = 15

# YouTube intermittently answers 403 on the stream URL (~1 in 3 downloads). yt-dlp aborts
# immediately on 4xx — only 5xx/transport errors go through its own --retries — but a fresh
# invocation gets a new stream URL and resumes the .part file.
DOWNLOAD_ATTEMPTS = 4
RETRY_DELAY_SECONDS = 5  # multiplied by attempt number: 5s, 10s, 15s
RETRYABLE_ERROR_RE = re.compile(
    r"HTTP Error (403|429|5\d\d)|unable to download video data|timed out"
    r"|Connection reset|Remote end closed|Connection aborted",
    re.IGNORECASE,
)


class DownloadError(Exception):
    pass


def _tail(lines) -> str:
    """Pick the most informative output lines for a user-facing error message."""
    lines = [ln.rstrip() for ln in lines if ln.strip()]
    errors = [ln for ln in lines if "ERROR:" in ln]
    return "\n".join(errors[-3:] if errors else lines[-5:])


@dataclass
class DownloadResult:
    audio_path: str
    cover_path: str | None
    title: str
    artist: str
    duration_seconds: float


class BaseDownloader:
    """Common yt-dlp based downloader. Subclasses override _parse_metadata for platform-specific fields."""

    def download(
        self,
        url: str,
        output_dir: str,
        on_progress: Callable[[float], None] | None = None,
        cancel_event: threading.Event | None = None,
        on_notice: Callable[[str], None] | None = None,
    ) -> DownloadResult:
        meta = self._extract_metadata(url)
        title, artist, duration = self._parse_metadata(meta)

        audio_path = self._download_audio(
            url, output_dir, on_progress=on_progress, cancel_event=cancel_event, on_notice=on_notice,
        )
        cover_path = self._download_thumbnail(url, output_dir)

        return DownloadResult(
            audio_path=audio_path,
            cover_path=cover_path,
            title=title,
            artist=artist,
            duration_seconds=duration,
        )

    def _parse_metadata(self, meta: dict) -> tuple[str, str, float]:
        """Override in subclasses for platform-specific metadata field mapping."""
        title = meta.get("title", "Unknown")
        artist = meta.get("uploader", "Unknown")
        duration = float(meta.get("duration", 0))
        return title, artist, duration

    def _extract_metadata(self, url: str) -> dict:
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-j",
            "--no-download",
            url,
        ]
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            logger.error("yt-dlp metadata failed (exit %s):\n%s", e.returncode, e.stderr)
            raise DownloadError(
                f"Nem sikerült a metaadatokat kinyerni (exit code {e.returncode}):\n"
                f"{_tail(e.stderr.splitlines())}"
            ) from e
        except json.JSONDecodeError as e:
            raise DownloadError(f"Nem sikerült a metaadatokat kinyerni: {e}") from e

    def _download_audio(
        self,
        url: str,
        output_dir: str,
        on_progress: Callable[[float], None] | None = None,
        cancel_event: threading.Event | None = None,
        on_notice: Callable[[str], None] | None = None,
    ) -> str:
        audio_path = os.path.join(output_dir, "audio.%(ext)s")
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-x",
            "--audio-format", "best",
            "--newline",
            "-o", audio_path,
            "--no-post-overwrites",
            url,
        ]
        for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
            returncode, output_tail = self._run_yt_dlp(cmd, on_progress, cancel_event)
            if returncode == 0:
                break

            output = "\n".join(output_tail)
            logger.error(
                "yt-dlp download failed (attempt %s/%s, exit %s):\n%s",
                attempt, DOWNLOAD_ATTEMPTS, returncode, output,
            )
            if attempt == DOWNLOAD_ATTEMPTS or not RETRYABLE_ERROR_RE.search(output):
                raise DownloadError(
                    f"yt-dlp hiba (exit code {returncode}):\n{_tail(output_tail)}"
                )
            # A stale yt-dlp can 403 on every attempt for days, until a release catches up
            if on_notice:
                on_notice("yt-dlp frissítés keresése...")
            new_version = ytdlp_update.maybe_update()
            if new_version and on_notice:
                on_notice(f"yt-dlp {new_version}, újrapróbálom...")

            delay = 0 if new_version else RETRY_DELAY_SECONDS * attempt
            logger.info("Retrying download in %ss", delay)
            if cancel_event is not None:
                if cancel_event.wait(delay):
                    raise DownloadError("Leállítva")
            else:
                time.sleep(delay)

        actual_audio = self._find_audio_file(output_dir)
        if not actual_audio:
            raise DownloadError("Az audiófájl nem található a letöltés után")
        return actual_audio

    def _run_yt_dlp(
        self,
        cmd: list[str],
        on_progress: Callable[[float], None] | None,
        cancel_event: threading.Event | None,
    ) -> tuple[int, deque[str]]:
        """Run yt-dlp, forwarding progress. Returns (exit code, last non-progress output lines)."""
        output_tail: deque[str] = deque(maxlen=ERROR_TAIL_LINES)
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            for line in proc.stdout:
                if cancel_event and cancel_event.is_set():
                    proc.terminate()
                    proc.wait()
                    raise DownloadError("Leállítva")
                is_progress = "[download]" in line and "%" in line
                if not is_progress and line.strip():
                    output_tail.append(line.rstrip())
                if on_progress and is_progress:
                    m = re.search(r"(\d+\.?\d*)%", line)
                    if m:
                        on_progress(float(m.group(1)))
            proc.wait()
            return proc.returncode, output_tail
        except OSError as e:
            raise DownloadError(f"yt-dlp hiba: {e}") from e

    def _find_audio_file(self, output_dir: str) -> str | None:
        for f in os.listdir(output_dir):
            if f.startswith("audio.") and not f.endswith(".part"):
                return os.path.join(output_dir, f)
        return None

    def _download_thumbnail(self, url: str, output_dir: str) -> str | None:
        cover_path = os.path.join(output_dir, "cover.%(ext)s")
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "--write-thumbnail",
            "--skip-download",
            "--convert-thumbnails", "jpg",
            "-o", cover_path,
            url,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError:
            return None

        for f in os.listdir(output_dir):
            if f.startswith("cover.") and f.endswith(".jpg"):
                return os.path.join(output_dir, f)
        return None


@dataclass
class MetadataResult:
    title: str
    artist: str
    year: str
    filename: str
    duration_seconds: float


def get_metadata(url: str) -> MetadataResult:
    """Extract raw metadata from URL without downloading audio."""
    dl = get_downloader(url)
    meta = dl._extract_metadata(url)
    title, artist, duration = dl._parse_metadata(meta)
    return MetadataResult(
        title=title,
        artist=artist,
        year="",
        filename=f"{artist} - {title}",
        duration_seconds=duration,
    )


def get_downloader(url: str) -> BaseDownloader:
    """Factory: return the appropriate downloader based on URL."""
    from music_agent.downloaders.soundcloud import SoundCloudDownloader
    from music_agent.downloaders.mixcloud import MixcloudDownloader
    from music_agent.downloaders.youtube import YouTubeDownloader

    if "soundcloud.com" in url or "on.soundcloud.com" in url:
        return SoundCloudDownloader()
    elif "mixcloud.com" in url:
        return MixcloudDownloader()
    else:
        return YouTubeDownloader()
