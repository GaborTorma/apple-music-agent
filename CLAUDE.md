# CLAUDE.md

## Project overview

Telegram bot that downloads YouTube audio, converts to AAC m4a, adds to Apple Music, waits for iCloud sync, then adds to a playlist. macOS only.

## Tech stack

- Python 3.12+ with python-telegram-bot (async, long polling)
- yt-dlp (CLI) — YouTube download
- ffmpeg/ffprobe (CLI) — audio conversion
- osascript/AppleScript — Apple Music control
- python-dotenv — env management

## Architecture

Modular pipeline: `bot.py` → `pipeline.py` → `downloader.py` → `converter.py` → `apple_music.py`

Each module returns a dataclass result. Pipeline orchestrates steps with status callbacks.

## Key files

- `bot.py` — Telegram bot entry point, async handler, YouTube URL regex
- `pipeline.py` — Orchestrator, temp dir management, calls modules in sequence
- `downloader.py` — yt-dlp wrapper, downloads audio + thumbnail + metadata
- `converter.py` — ffmpeg wrapper, dynamic bitrate calculation, cover art embedding
- `apple_music.py` — AppleScript integration (add to library, iCloud poll, playlist add)
- `config.py` — All settings from .env + constants

## Important patterns

- Dynamic bitrate: `min(192, floor(195MB * 8 * 0.95 / duration / 1000))` kbps
- Converted files persist in `/Users/Shared/Music/` (not temp) — Apple Music needs the file to stay
- `add POSIX file` returns track reference → persistent ID extracted directly (no name-based search)
- iCloud sync polling: 60s interval, 20 min timeout, continues on timeout
- Pipeline always cleans up temp dir in `finally` block
- Bot runs sync pipeline in `run_in_executor` to avoid blocking event loop

## Gotchas

- Apple Music `add` only adds to local library. iCloud upload starts automatically but takes ~2 min
- JXA `duplicate` to user playlist fails. Use AppleScript `duplicate` within `tell library playlist 1`
- ffmpeg cover art must use `-c:v mjpeg` codec, not h264 (m4a container rejects h264)
- yt-dlp output template uses `%(ext)s` — actual file found by scanning directory
- Special chars in titles (& parentheses quotes) break AppleScript `whose name contains`. Avoid name-based search, use persistent ID instead
- System Events (menu clicks) requires Accessibility permission for Terminal.app

## Commands

```bash
# Run bot
source .venv/bin/activate && python3 bot.py

# Install deps
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# System deps
brew install yt-dlp ffmpeg
```

## Configuration

All in `.env`: `TELEGRAM_BOT_TOKEN`, `ALLOWED_USER_IDS`, `PLAYLIST_NAME` (default: Futás)

Constants in `config.py`: max bitrate 192kbps, max file size 195MB, min bitrate 64kbps, poll interval 60s, poll timeout 20min.

## Language

User-facing messages and error strings are in Hungarian.
