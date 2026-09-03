import logging
import subprocess
import threading
import time

from music_agent import config

logger = logging.getLogger(__name__)


class AppleMusicError(Exception):
    pass


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def add_to_library(m4a_path: str) -> str:
    """Add an m4a file to Apple Music library. Returns the persistent ID of the track."""
    escaped_path = _escape(m4a_path)
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


def find_track_id(name: str, artist: str) -> str | None:
    """Persistent ID of the most recently added track with this name and artist."""
    if not name:
        return None
    script = f'''
    tell application "Music"
        set matches to (every track of library playlist 1 whose name is "{_escape(name)}" and artist is "{_escape(artist)}")
        if (count of matches) is 0 then return ""
        set newest to item 1 of matches
        repeat with t in matches
            if (date added of t) > (date added of newest) then set newest to t
        end repeat
        return persistent ID of newest
    end tell
    '''
    try:
        return _run_applescript(script).strip() or None
    except AppleMusicError as e:
        logger.warning("Could not look up track '%s' by name: %s", name, e)
        return None


def wait_for_icloud_sync(
    persistent_id: str,
    name: str = "",
    artist: str = "",
    on_progress: 'Callable[[float, float], None] | None' = None,
    cancel_event: 'threading.Event | None' = None,
) -> tuple[bool, str]:
    """Poll iCloud Music Library status.

    Returns (synced, persistent_id). Uploading replaces the local file track with a
    shared track under a new persistent ID, so the ID is re-resolved by name when the
    original disappears — the returned one is what later steps must use.

    on_progress(elapsed_seconds, timeout_seconds) is called each poll cycle.
    """
    start = time.time()
    synced_statuses = {"matched", "uploaded", "purchased", "loaded"}

    while time.time() - start < config.ICLOUD_POLL_TIMEOUT_SECONDS:
        if cancel_event and cancel_event.is_set():
            return False, persistent_id
        elapsed = time.time() - start
        if on_progress:
            on_progress(elapsed, config.ICLOUD_POLL_TIMEOUT_SECONDS)

        status = _get_cloud_status(persistent_id)
        if status == "not_found":
            new_id = find_track_id(name, artist)
            if new_id and new_id != persistent_id:
                logger.info("Track %s was replaced by %s (iCloud upload)", persistent_id, new_id)
                persistent_id = new_id
                status = _get_cloud_status(persistent_id)

        if status and status.lower() in synced_statuses:
            return True, persistent_id
        # Sleep in small increments so cancel is responsive
        for _ in range(config.ICLOUD_POLL_INTERVAL_SECONDS):
            if cancel_event and cancel_event.is_set():
                return False, persistent_id
            time.sleep(1)

    return False, persistent_id


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


# Two pipelines may run at once (the bot handles updates concurrently); their
# rotations below would interleave inside Music and leave the new tracks mid-list
_playlist_lock = threading.Lock()


def add_to_playlist(persistent_id: str, playlist_name: str) -> None:
    """Add a track to the top of a named playlist."""
    escaped_name = _escape(playlist_name)
    # A playlist entry keeps the library track's persistent ID, so this stays a no-op
    # when the track is already on the playlist.
    # `duplicate` always appends: Music ignores `to beginning of`, and `move` only
    # honours `to end of` on playlist tracks (`index` is read-only). So the new entry
    # is brought to the top by moving every earlier entry behind it, one by one.
    # `move` never removes anything — a failure midway leaves the playlist rotated.
    # `fixed indexing` makes `track N` follow the playlist's own order rather than
    # the column the Music window happens to be sorted by. Music silently ignores
    # unsupported locations, so the result is checked instead of trusted.
    script = f'''
    tell application "Music"
        set thePlaylist to (first user playlist whose name is "{escaped_name}")
        set fixed indexing to true
        set atTop to true
        if (count of (every track of thePlaylist whose persistent ID is "{persistent_id}")) is 0 then
            set earlier to count of tracks of thePlaylist
            tell library playlist 1
                duplicate (first track whose persistent ID is "{persistent_id}") to thePlaylist
            end tell
            repeat earlier times
                move (track 1 of thePlaylist) to end of thePlaylist
            end repeat
            set atTop to (persistent ID of track 1 of thePlaylist) is "{persistent_id}"
        end if
        set fixed indexing to false
        return atTop
    end tell
    '''
    try:
        with _playlist_lock:
            at_top = _run_applescript(script).strip()
    except AppleMusicError as e:
        raise AppleMusicError(
            f"Nem sikerült hozzáadni a(z) '{playlist_name}' lejátszási listához: {e}"
        ) from e
    if at_top != "true":
        raise AppleMusicError(
            f"A szám felkerült a(z) '{playlist_name}' lejátszási listára, de nem a tetejére"
        )


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
