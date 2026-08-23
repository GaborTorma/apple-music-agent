"""Keep the yt-dlp CLI current — YouTube breaks extraction faster than releases land."""

import logging
import shutil
import subprocess
import time

logger = logging.getLogger(__name__)

# An update is only worth trying after a failed download, and not more often than this
MIN_INTERVAL_SECONDS = 6 * 3600
COMMAND_TIMEOUT_SECONDS = 120

_last_attempt: float | None = None


def version() -> str:
    try:
        result = subprocess.run(
            ["yt-dlp", "--version"], capture_output=True, text=True, timeout=30,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _update_commands() -> list[list[str]]:
    # yt-dlp -U refuses to self-update a package manager install, so ask the package manager
    if shutil.which("brew"):
        return [["brew", "update", "--quiet"], ["brew", "upgrade", "yt-dlp"]]
    return [["yt-dlp", "-U"]]


def maybe_update() -> str | None:
    """Update yt-dlp unless it was tried recently. Returns the new version if it changed."""
    global _last_attempt

    now = time.monotonic()
    if _last_attempt is not None and now - _last_attempt < MIN_INTERVAL_SECONDS:
        logger.info("Skipping yt-dlp update check, last attempt was %.0fs ago", now - _last_attempt)
        return None
    _last_attempt = now

    before = version()
    for cmd in _update_commands():
        logger.info("Running %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning("yt-dlp update failed (%s): %s", " ".join(cmd), e)
            return None
        if result.returncode != 0:
            logger.warning(
                "%s exited %s: %s",
                " ".join(cmd), result.returncode, (result.stderr or result.stdout).strip()[-500:],
            )

    after = version()
    if after and after != before:
        logger.info("yt-dlp updated: %s → %s", before, after)
        return after

    logger.info("yt-dlp is already current (%s)", after or before)
    return None
