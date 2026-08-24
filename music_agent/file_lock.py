"""Cross-agent claim on a target file in the shared MUSIC_DIR.

Both agents on the Mac Mini write to the same MUSIC_DIR, so the same URL can be
requested from both. A lock file next to the target lets the second one wait for
the first instead of downloading the same audio again.
"""

import getpass
import json
import logging
import os
import socket
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

# The holder refreshes its lock while it works; anything older crashed mid-run
STALE_SECONDS = 10 * 60
REFRESH_SECONDS = 5
POLL_SECONDS = 5
WAIT_TIMEOUT_SECONDS = 30 * 60


def lock_path(target_path: str) -> str:
    directory, name = os.path.split(target_path)
    return os.path.join(directory, f".{name}.lock")


def holder(target_path: str) -> str | None:
    """Who is working on this target right now, or None if free (or the lock is stale)."""
    path = lock_path(target_path)
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        return None
    if age > STALE_SECONDS:
        logger.warning("Ignoring stale lock %s (%.0f min old)", path, age / 60)
        return None
    try:
        with open(path) as f:
            info = json.load(f)
        return f"{info.get('user', '?')}@{info.get('host', '?')}"
    except (OSError, ValueError):
        return "másik ügynök"


class TargetLock:
    """Claim on one target file. acquire() → work → release(); refresh() while working."""

    def __init__(self, target_path: str):
        self.target_path = target_path
        self.path = lock_path(target_path)
        self._fd: int | None = None
        self._last_refresh = 0.0

    def acquire(self) -> bool:
        for attempt in (1, 2):
            try:
                self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                break
            except FileExistsError:
                if holder(self.target_path) or attempt == 2:
                    return False
                # Stale lock from a crashed run — drop it and try once more
                try:
                    os.unlink(self.path)
                except OSError:
                    return False
            except OSError as e:
                logger.warning("Could not create lock %s: %s", self.path, e)
                return False

        info = {"pid": os.getpid(), "user": _user(), "host": socket.gethostname(), "started": time.time()}
        os.write(self._fd, json.dumps(info).encode())
        self._last_refresh = time.monotonic()
        return True

    def refresh(self) -> None:
        """Keep the lock from going stale. Cheap enough to call on every progress tick."""
        if self._fd is None:
            return
        now = time.monotonic()
        if now - self._last_refresh < REFRESH_SECONDS:
            return
        self._last_refresh = now
        try:
            os.utime(self.path, None)
        except OSError:
            pass

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            os.close(self._fd)
        finally:
            self._fd = None
            try:
                os.unlink(self.path)
            except OSError:
                pass


def wait_for(
    target_path: str,
    on_wait: Callable[[str, float], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    """Block until the target file appears, its lock is released, or we give up waiting."""
    start = time.monotonic()
    while True:
        if os.path.exists(target_path):
            return
        who = holder(target_path)
        if not who:
            return

        waited = time.monotonic() - start
        if waited > WAIT_TIMEOUT_SECONDS:
            logger.warning("Gave up waiting for %s after %.0f min", who, waited / 60)
            return
        if on_wait:
            on_wait(who, waited)
        if cancel_event is not None:
            if cancel_event.wait(POLL_SECONDS):
                return
        else:
            time.sleep(POLL_SECONDS)


def _user() -> str:
    # getlogin() reports the terminal owner, which is not the process user under launchd
    try:
        return getpass.getuser()
    except (OSError, KeyError):
        return "?"
