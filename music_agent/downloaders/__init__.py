import json
import re
import subprocess
import os
import threading
from dataclasses import dataclass
from typing import Callable


class DownloadError(Exception):
    pass


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
    ) -> DownloadResult:
        meta = self._extract_metadata(url)
        title, artist, duration = self._parse_metadata(meta)

        audio_path = self._download_audio(url, output_dir, on_progress=on_progress, cancel_event=cancel_event)
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
        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            raise DownloadError(f"Nem sikerült a metaadatokat kinyerni: {e}") from e

    def _download_audio(
        self,
        url: str,
        output_dir: str,
        on_progress: Callable[[float], None] | None = None,
        cancel_event: threading.Event | None = None,
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
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            for line in proc.stdout:
                if cancel_event and cancel_event.is_set():
                    proc.terminate()
                    proc.wait()
                    raise DownloadError("Leállítva")
                if on_progress and "[download]" in line:
                    m = re.search(r"(\d+\.?\d*)%", line)
                    if m:
                        on_progress(float(m.group(1)))
            proc.wait()
            if proc.returncode != 0:
                raise DownloadError(f"yt-dlp hiba (exit code {proc.returncode})")
        except OSError as e:
            raise DownloadError(f"yt-dlp hiba: {e}") from e

        actual_audio = self._find_audio_file(output_dir)
        if not actual_audio:
            raise DownloadError("Az audiófájl nem található a letöltés után")
        return actual_audio

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
