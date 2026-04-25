# CLAUDE.md

## Project overview

Telegram bot that downloads audio from YouTube, SoundCloud, and Mixcloud, converts to AAC m4a, adds to Apple Music, waits for iCloud sync, then adds to a playlist. macOS only.

## Tech stack

- Python 3.12+ with python-telegram-bot (async, long polling)
- yt-dlp (CLI) — YouTube, SoundCloud, Mixcloud download
- ffmpeg/ffprobe (CLI) — audio conversion
- osascript/AppleScript — Apple Music control
- OpenRouter (cloud LLM via HTTPS) — AI metadata enrichment (title, artist, year, filename)
- python-dotenv — env management

## Architecture

Package-based structure under `music_agent/`. Entry point: `run.py`.

Pipeline: `bot.py` → `downloaders/` (metadata) → `services/ai_metadata.py` (AI enrichment) → `pipeline.py` → `downloaders/` (download) → `converter.py` → `services/apple_music.py`

Downloaders use inheritance: `BaseDownloader` (common yt-dlp logic) with platform subclasses (`YouTubeDownloader`, `SoundCloudDownloader`, `MixcloudDownloader`). Factory function `get_downloader(url)` selects the right one based on URL.

## Project structure

```
music_agent/
├── __init__.py
├── config.py              — All settings from .env + constants
├── bot.py                 — Telegram bot, multi-platform URL matching
├── pipeline.py            — Orchestrator, temp dir, downloader routing
├── converter.py           — ffmpeg wrapper, dynamic bitrate, cover art
├── downloaders/
│   ├── __init__.py        — BaseDownloader, DownloadResult, get_downloader()
│   ├── youtube.py         — YouTubeDownloader
│   ├── soundcloud.py      — SoundCloudDownloader
│   └── mixcloud.py        — MixcloudDownloader
└── services/
    ├── __init__.py
    ├── apple_music.py     — AppleScript integration
    └── ai_metadata.py     — OpenRouter AI metadata enrichment
```

## Important patterns

- Dynamic bitrate: `min(192, floor(195MB * 8 * 0.95 / duration / 1000))` kbps
- `MUSIC_DIR` env var: if set, files persist there; if empty, files stay in temp dir
- `add POSIX file` returns track reference → persistent ID extracted directly (no name-based search)
- iCloud sync polling: 60s interval, 20 min timeout, continues on timeout
- Pipeline cleans up temp dir only when `MUSIC_DIR` is set (file already moved out)
- Bot runs sync pipeline in `run_in_executor` to avoid blocking event loop
- `get_downloader(url)` factory auto-selects downloader based on URL domain
- AI metadata: OpenRouter chat/completions API (OpenAI-compatible JSON), no SDK needed. Graceful fallback if API key missing or request fails
- Bot two-phase metadata: 1) yt-dlp extract → 2) AI enrichment → user confirmation with per-field edit buttons
- Metadata fields: title, artist, year, filename — all editable via inline keyboard buttons

## Gotchas

- Apple Music `add` only adds to local library. iCloud upload starts automatically but takes ~2 min
- JXA `duplicate` to user playlist fails. Use AppleScript `duplicate` within `tell library playlist 1`
- ffmpeg cover art must use `-c:v mjpeg` codec, not h264 (m4a container rejects h264)
- yt-dlp output template uses `%(ext)s` — actual file found by scanning directory
- Special chars in titles (& parentheses quotes) break AppleScript `whose name contains`. Avoid name-based search, use persistent ID instead
- Automation permission required: Python 3.14 → Music.app (granted in System Settings > Privacy & Security > Automation; prompts on first AppleScript call in an active GUI session)

## Commands

```bash
# Run bot
source .venv/bin/activate && python3 run.py

# Run bot with auto-reload (dev)
watchfiles "python run.py"

# Install deps
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# System deps
brew install yt-dlp ffmpeg
```

## Configuration

All in `.env`:

- `TELEGRAM_BOT_TOKEN` — bot API token (required)
- `ALLOWED_USER_IDS` — comma-separated user IDs
- `PLAYLIST_NAME` — target playlist (default: Futás)
- `MUSIC_DIR` — persistent music directory (default: empty = temp dir)
- `OPENROUTER_API_KEY` — OpenRouter API key (optional; if empty, AI enrichment is skipped)
- `OPENROUTER_MODEL` — OpenRouter model slug (default: `google/gemma-4-31b-it:free`)
- `OPENROUTER_APP_NAME` — app name for OpenRouter dashboard (default: `apple-music-agent`, sent as `X-Title`)
- `OPENROUTER_APP_URL` — app URL for OpenRouter rankings (default: GitHub repo, sent as `HTTP-Referer`)

Constants in `config.py`: max bitrate 192kbps, max file size 195MB, min bitrate 64kbps, poll interval 60s, poll timeout 20min.

## Deployment

Runs on Mac Mini (`macclaw.local`) as launchd LaunchAgent. Deploy: `git push` → `make deploy`.

- Config: `scripts/config.sh` (install dir, service label, repo URL — Makefile derives from this)
- Install dir: `~/Agents/Music`, service domain: `gui/$(id -u)` (user session, Apple Music needs GUI)
- Logs: `~/Library/Logs/apple-music-agent/{stdout,stderr}.log`
- `KeepAlive: true` + `ThrottleInterval: 10s` — auto-restart on crash
- `RunAtLoad: true` — starts on login

## Language

User-facing messages and error strings are in Hungarian.
