import json
import logging
import urllib.request
import urllib.error

from music_agent import config

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a music metadata assistant. Given raw metadata from a music/video URL, extract clean metadata.

Rules:
- Artist: the performing artist or DJ, NOT the YouTube channel name or uploader (unless they are the same person)
- Title: the name of the track, set, or mix. Remove clutter: (Official Video), (Official Music Video), (Full video set), [HD], (Lyric Video), (Audio), (Visualizer), etc. Keep it short as possible.
- For DJ sets/live sets: the artist is the DJ, and the title is ONLY the event/festival name + year. Remove everything else: "Full Live Set", "DJ Set", "@ ", "Live @", descriptions like "Psytrance Festival in Hungary", etc. Example: "Mad Maxx Full Live Set @ Ozora Festival 2024 - Psytrance Festival in Hungary" → title: "OZORA 2024"
- IMPORTANT: The artist name must NEVER appear in the title. Strip it out completely
- Festival name normalization (always use these exact forms, year is mandatory after them):
  - Ozora Festival, O.Z.O.R.A, OZORA Festival → "OZORA 2025"
  - BOOM Festival, Boom Festival → "BOOM 2025"
  - Manas Festival → "Manas 2025"
- Genre tags in parentheses like (Darkpsy, Forest) or (Progressive House) should be removed from both artist and title
- Year: the original release/recording year, NOT the upload year. If the video was uploaded in 2026 but the content is a 2024 festival recording, use 2024. For NYE or cross-year events like "2025/26", use the earlier year (2025). If unsure, use empty string
- Filename format: always "Artist - Title" (no year in filename)

Respond with ONLY a JSON object, no markdown, no explanation:
{"title": "...", "artist": "...", "year": "...", "filename": "..."}"""


def suggest_metadata(raw_meta: dict) -> dict | None:
    """Call Ollama to suggest clean metadata from raw yt-dlp metadata.

    Returns dict with keys: title, artist, year, filename.
    Returns None if Ollama is unavailable or fails.
    """
    user_prompt = _build_prompt(raw_meta)

    try:
        result = _call_ollama(user_prompt)
    except Exception:
        logger.warning("Ollama not available, skipping AI metadata suggestion")
        return None

    try:
        parsed = json.loads(result)
        if not isinstance(parsed, dict):
            return None
        # Validate required keys
        for key in ("title", "artist", "year", "filename"):
            if key not in parsed or not isinstance(parsed[key], str):
                return None
        return parsed
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse Ollama response: %s", result[:200])
        return None


def _build_prompt(meta: dict) -> str:
    """Extract key fields from yt-dlp JSON for the AI prompt."""
    fields = {}
    for key in ("title", "uploader", "channel", "artist", "album",
                 "upload_date", "release_date", "release_year"):
        if meta.get(key):
            fields[key] = meta[key]

    description = meta.get("description", "")
    if description:
        fields["description"] = description[:500]

    return json.dumps(fields, ensure_ascii=False)


def _call_ollama(prompt: str) -> str:
    """Make HTTP request to Ollama generate API."""
    url = f"{config.OLLAMA_HOST}/api/generate"
    payload = json.dumps({
        "model": config.OLLAMA_MODEL,
        "prompt": prompt,
        "system": _SYSTEM_PROMPT,
        "stream": False,
        "options": {
            "temperature": 0.1,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        return body.get("response", "")
