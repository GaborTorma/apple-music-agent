import math
import subprocess
import os
import threading
from dataclasses import dataclass
from typing import Callable

from music_agent import config


class ConversionError(Exception):
    pass


@dataclass
class ConversionResult:
    m4a_path: str
    bitrate_kbps: int
    low_bitrate_warning: bool


def convert(
    audio_path: str,
    cover_path: str | None,
    title: str,
    artist: str,
    duration_seconds: float,
    output_dir: str,
    on_progress: Callable[[float], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> ConversionResult:
    """Convert audio to AAC m4a with dynamic bitrate to stay under size limit."""
    bitrate_kbps = _calculate_bitrate(duration_seconds)
    low_bitrate_warning = bitrate_kbps < config.MIN_BITRATE_KBPS

    if low_bitrate_warning:
        bitrate_kbps = config.MIN_BITRATE_KBPS

    output_path = os.path.join(output_dir, f"{_safe_filename(title)}.m4a")

    cmd = [
        "ffmpeg", "-y",
        "-i", audio_path,
    ]

    # Add cover art if available
    if cover_path and os.path.exists(cover_path):
        cmd.extend(["-i", cover_path])
        cmd.extend([
            "-map", "0:a",
            "-map", "1:v",
            "-c:v", "mjpeg",
            "-disposition:v:0", "attached_pic",
        ])

    cmd.extend([
        "-c:a", "aac",
        "-b:a", f"{bitrate_kbps}k",
        "-metadata", f"title={title}",
        "-metadata", f"artist={artist}",
        "-metadata", f"album={title}",
        "-metadata", f"album_artist={artist}",
        "-metadata", f"composer={artist}",
        "-progress", "pipe:1",
        output_path,
    ])

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for line in proc.stdout:
            if cancel_event and cancel_event.is_set():
                proc.terminate()
                proc.wait()
                raise ConversionError("Leállítva")
            if on_progress and line.startswith("out_time_us="):
                try:
                    us = int(line.split("=")[1])
                    if duration_seconds > 0:
                        pct = min(99.0, us / (duration_seconds * 1_000_000) * 100)
                        on_progress(pct)
                except (ValueError, IndexError):
                    pass
        proc.wait()
        if proc.returncode != 0:
            stderr = proc.stderr.read()
            raise ConversionError(f"ffmpeg hiba: {stderr}")
    except OSError as e:
        raise ConversionError(f"ffmpeg hiba: {e}") from e

    # Verify file size
    file_size = os.path.getsize(output_path)
    if file_size > config.MAX_FILE_SIZE_BYTES:
        raise ConversionError(
            f"A kimeneti fájl ({file_size / 1024 / 1024:.1f}MB) meghaladja "
            f"a {config.MAX_FILE_SIZE_BYTES / 1024 / 1024:.0f}MB limitet"
        )

    return ConversionResult(
        m4a_path=output_path,
        bitrate_kbps=bitrate_kbps,
        low_bitrate_warning=low_bitrate_warning,
    )


def _calculate_bitrate(duration_seconds: float) -> int:
    """Calculate max bitrate to keep file under size limit."""
    if duration_seconds <= 0:
        return config.MAX_BITRATE_KBPS

    max_bits = config.MAX_FILE_SIZE_BYTES * 8
    # Leave 5% headroom for container overhead
    usable_bits = max_bits * 0.95
    calculated_kbps = int(math.floor(usable_bits / duration_seconds / 1000))

    return min(calculated_kbps, config.MAX_BITRATE_KBPS)


def _safe_filename(title: str) -> str:
    """Sanitize title for use as filename."""
    keepchars = " -_.()"
    return "".join(c for c in title if c.isalnum() or c in keepchars).strip()[:200]
