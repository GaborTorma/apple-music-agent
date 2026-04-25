import json
import logging
import re
import urllib.request
import urllib.error

from music_agent import config

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a music metadata assistant. Given raw metadata from a music/video URL, extract clean metadata.

Rules:
- Artist: extract artist from title. The performing artist or DJ, NOT the YouTube channel name or uploader (unless they are the same person).
- Title: the name of the track, set, or mix. Remove clutter: (Official Video), (Official Music Video), (Full video set), [HD], (Lyric Video), (Audio), (Visualizer), etc. Keep it short as possible.
- For DJ sets/live sets: the artist is the DJ, and the title is ONLY the event/festival name + year. Remove everything else: "Full Live Set", "DJ Set", "@ ", "Live @", descriptions like "Psytrance Festival in Hungary", etc. Example: "Mad Maxx Full Live Set @ Ozora Festival 2024 - Psytrance Festival in Hungary" → title: "OZORA 2024"
- IMPORTANT: The artist name must NEVER appear in the title. Strip it out completely
- Festival name normalization (always use these exact forms, year is mandatory after them):
  - Ozora Festival, O.Z.O.R.A, OZORA Festival → "OZORA 2025"
  - BOOM Festival, Boom Festival → "BOOM 2025"
  - Manas Festival → "Manas 2025"
  - Do not convert all festival title to uppercase, keep them as is (exclude: OZORA, BOOM)
- Genre tags in parentheses like (Darkpsy, Forest) or (Progressive House) should be removed from both artist and title
- Year: the original release/recording year, NOT the upload year. If the video was uploaded in 2026 but the content is a 2024 festival recording, use 2024. For NYE or cross-year events like "2025/26", use the earlier year (2025). If unsure, use empty string
- Filename format: always "Artist - Title" (no year in filename)

Respond with ONLY a JSON object, no markdown, no explanation:
{"title": "...", "artist": "...", "year": "...", "filename": "..."}"""


def suggest_metadata(raw_meta: dict) -> dict | None:
    """Call OpenRouter to suggest clean metadata from raw yt-dlp metadata.

    Returns dict with keys: title, artist, year, filename.
    Returns None if OpenRouter is unavailable or fails.
    """
    if not config.OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY not set, skipping AI metadata suggestion")
        return None

    user_prompt = _build_prompt(raw_meta)

    try:
        result = _call_openrouter(user_prompt)
    except Exception:
        logger.warning("OpenRouter not available, skipping AI metadata suggestion")
        return None

    try:
        parsed = json.loads(_strip_code_fence(result))
        if not isinstance(parsed, dict):
            return None
        for key in ("title", "artist", "year", "filename"):
            if key not in parsed or not isinstance(parsed[key], str):
                return None
        return parsed
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse OpenRouter response: %s", result[:200])
        return None


def _strip_code_fence(text: str) -> str:
    """Strip ```json ... ``` or ``` ... ``` fences some models wrap JSON in."""
    m = re.match(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", text, re.DOTALL)
    return m.group(1) if m else text


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


_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _call_openrouter(prompt: str) -> str:
    """Make HTTP request to OpenRouter chat/completions API (OpenAI-compatible)."""
    payload = json.dumps({
        "model": config.OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "X-Title": config.OPENROUTER_APP_NAME,
        "HTTP-Referer": config.OPENROUTER_APP_URL,
    }

    req = urllib.request.Request(
        _OPENROUTER_URL,
        data=payload,
        headers=headers,
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]
