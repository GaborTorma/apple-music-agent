import subprocess
import time

from music_agent import config


class AppleMusicError(Exception):
    pass


def add_to_library(m4a_path: str) -> str:
    """Add an m4a file to Apple Music library. Returns the persistent ID of the track."""
    escaped_path = m4a_path.replace("\\", "\\\\").replace('"', '\\"')
    # Step 1: Add file and get persistent ID
    add_script = f'''
    tell application "Music"
        set addedTrack to (add POSIX file "{escaped_path}")
        delay 3
        persistent ID of addedTrack
    end tell
    '''
    result = _run_applescript(add_script, timeout=120)
    persistent_id = result.strip()
    if not persistent_id:
        raise AppleMusicError("Nem sikerült a hozzáadott szám azonosítóját lekérni")

    return persistent_id


def wait_for_icloud_sync(
    persistent_id: str,
    on_progress: 'Callable[[float, float], None] | None' = None,
    cancel_event: 'threading.Event | None' = None,
) -> bool:
    """Poll iCloud Music Library status. Returns True if synced, False if timed out.

    on_progress(elapsed_seconds, timeout_seconds) is called each poll cycle.
    """
    import threading
    start = time.time()
    synced_statuses = {"matched", "uploaded", "purchased", "loaded"}

    while time.time() - start < config.ICLOUD_POLL_TIMEOUT_SECONDS:
        if cancel_event and cancel_event.is_set():
            return False
        elapsed = time.time() - start
        if on_progress:
            on_progress(elapsed, config.ICLOUD_POLL_TIMEOUT_SECONDS)
        status = _get_cloud_status(persistent_id)
        if status and status.lower() in synced_statuses:
            return True
        # Sleep in small increments so cancel is responsive
        for _ in range(config.ICLOUD_POLL_INTERVAL_SECONDS):
            if cancel_event and cancel_event.is_set():
                return False
            time.sleep(1)

    return False


def remove_from_library(persistent_id: str) -> None:
    """Remove a track from Apple Music library by persistent ID."""
    script = f'''
    tell application "Music"
        set matchingTracks to (every track whose persistent ID is "{persistent_id}")
        if (count of matchingTracks) > 0 then
            delete (first item of matchingTracks)
        end if
    end tell
    '''
    _run_applescript(script)


def add_to_playlist(persistent_id: str, playlist_name: str) -> None:
    """Add a track to a named playlist."""
    escaped_name = playlist_name.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
    tell application "Music"
        set thePlaylist to (first user playlist whose name is "{escaped_name}")
        tell library playlist 1
            set libTrack to (first file track whose persistent ID is "{persistent_id}")
            duplicate libTrack to thePlaylist
        end tell
    end tell
    '''
    try:
        _run_applescript(script)
    except AppleMusicError as e:
        raise AppleMusicError(
            f"Nem sikerült hozzáadni a(z) '{playlist_name}' lejátszási listához: {e}"
        ) from e


def _get_cloud_status(persistent_id: str) -> str | None:
    script = f'''
    tell application "Music"
        set matchingTracks to (every track whose persistent ID is "{persistent_id}")
        if (count of matchingTracks) is 0 then
            return "not_found"
        end if
        set theTrack to first item of matchingTracks
        return cloud status of theTrack as text
    end tell
    '''
    try:
        result = _run_applescript(script)
        return result.strip()
    except AppleMusicError:
        return None


def _run_applescript(script: str, timeout: int = 60) -> str:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        raise AppleMusicError(f"AppleScript hiba: {e.stderr}") from e
    except subprocess.TimeoutExpired as e:
        raise AppleMusicError("AppleScript időtúllépés") from e
