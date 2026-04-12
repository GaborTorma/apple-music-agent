import json
import subprocess
import os
from dataclasses import dataclass


class DownloadError(Exception):
    pass


@dataclass
class DownloadResult:
    audio_path: str
    cover_path: str | None
    title: str
    artist: str
    duration_seconds: float


def download(url: str, output_dir: str) -> DownloadResult:
    """Download audio and metadata from a YouTube URL."""
    # First, extract metadata
    meta = _extract_metadata(url)
    title = meta.get("title", "Unknown")
    artist = meta.get("channel", meta.get("uploader", "Unknown"))
    duration = float(meta.get("duration", 0))

    # Download audio in best original format (vorbis/opus)
    audio_path = os.path.join(output_dir, "audio.%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-x",  # extract audio
        "--audio-format", "best",  # keep original format
        "-o", audio_path,
        "--no-post-overwrites",
        url,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise DownloadError(f"yt-dlp hiba: {e.stderr}") from e

    # Find the downloaded audio file
    actual_audio = _find_audio_file(output_dir)
    if not actual_audio:
        raise DownloadError("Az audiófájl nem található a letöltés után")

    # Download thumbnail
    cover_path = _download_thumbnail(url, output_dir)

    return DownloadResult(
        audio_path=actual_audio,
        cover_path=cover_path,
        title=title,
        artist=artist,
        duration_seconds=duration,
    )


def _extract_metadata(url: str) -> dict:
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-j",  # JSON output
        "--no-download",
        url,
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        raise DownloadError(f"Nem sikerült a metaadatokat kinyerni: {e}") from e


def _find_audio_file(output_dir: str) -> str | None:
    for f in os.listdir(output_dir):
        if f.startswith("audio.") and not f.endswith(".part"):
            return os.path.join(output_dir, f)
    return None


def _download_thumbnail(url: str, output_dir: str) -> str | None:
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
