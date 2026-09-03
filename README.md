# telegram-to-apple-music

Telegram bot that downloads audio from YouTube, SoundCloud, and Mixcloud links, converts to AAC m4a with dynamic bitrate (max 192kbps/195MB), adds to Apple Music library, waits for iCloud Music Library sync, and adds to a configured playlist. Uses OpenRouter (cloud LLM) to suggest clean metadata (artist, title, year, filename). Built for macOS with yt-dlp, ffmpeg, AppleScript, and OpenRouter.

## Requirements

- macOS with Apple Music app
- iCloud Music Library enabled
- Python 3.12+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [ffmpeg](https://ffmpeg.org/) (with AAC encoder)
- [OpenRouter](https://openrouter.ai/) API key (optional — AI metadata is skipped if not set)

### Install system dependencies

```bash
brew install yt-dlp ffmpeg
```

## Setup

```bash
# Clone
git clone https://github.com/gabortorma/apple-music-agent.git
cd apple-music-agent

# Virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configuration
cp .env.example .env
```

### macOS permissions

The bot uses AppleScript to control Apple Music. Grant the following permission in **System Settings → Privacy & Security**:

- **Automation**: Allow **Python 3.14** to control **Music**

The prompt appears automatically on first run — click "Allow".

Edit `.env`:

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
ALLOWED_USER_IDS=123456789
PLAYLIST_NAME=Futás
MUSIC_DIR=/Users/Shared/Music
OPENROUTER_API_KEY=your_openrouter_api_key_here
OPENROUTER_MODEL=google/gemma-4-31b-it:free
OPENROUTER_APP_NAME=apple-music-agent
OPENROUTER_APP_URL=https://github.com/gabortorma/apple-music-agent
```

### Get your Telegram user ID

1. Message [@userinfobot](https://t.me/userinfobot) on Telegram — it replies with your user ID
2. Add it to `ALLOWED_USER_IDS` in `.env`

### Create a Telegram bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the prompts
3. Copy the token to `.env`

## Usage

```bash
source .venv/bin/activate
python3 run.py
```

For development with auto-reload:

```bash
source .venv/bin/activate
watchfiles "python run.py"
```

Send a YouTube, SoundCloud, or Mixcloud link to your bot on Telegram. The bot will:

1. Extract metadata and use AI to suggest clean artist, title, year, and filename
2. Show confirmation with per-field edit buttons — accept with ✅ OK or edit individually
3. Reuse the file if `MUSIC_DIR` already has it — or wait for it if the other agent is downloading it right now (steps 4-5 are then skipped)
4. Download the audio (original format) — retries up to 4 times on transient errors (YouTube intermittently returns HTTP 403 on the stream URL). If a retry is needed, yt-dlp is upgraded first (`brew upgrade yt-dlp`, at most every 6 hours) — a persistent 403 usually means yt-dlp is behind a YouTube change
5. Convert to AAC m4a with dynamic bitrate calculation
6. Add to Apple Music library
7. Wait for iCloud Music Library sync (polls every 10s, max 20 min)
8. Add to the top of the configured playlist

Status updates are sent back via Telegram at each step.

### Commands

| Command | Description                                         |
| ------- | --------------------------------------------------- |
| `/stop` | Cancel the running pipeline or pending confirmation |

## Supported platforms

| Platform   | Example URL                                                                                        |
| ---------- | -------------------------------------------------------------------------------------------------- |
| YouTube    | `https://youtube.com/watch?v=...`, `https://youtu.be/...`, `https://music.youtube.com/watch?v=...` |
| SoundCloud | `https://soundcloud.com/artist/track`, `https://on.soundcloud.com/...`                             |
| Mixcloud   | `https://www.mixcloud.com/artist/mix-name/`                                                        |

## Dynamic bitrate

For long mixes (1-2+ hours), the bitrate is automatically reduced to keep the file under 195MB:

```
bitrate = min(192, floor(195MB × 8 × 0.95 / duration_seconds / 1000))
```

If the calculated bitrate drops below 64 kbps, a warning is sent.

## Configuration

| Variable             | Default                  | Description                                                  |
| -------------------- | ------------------------ | ------------------------------------------------------------ |
| `TELEGRAM_BOT_TOKEN` | —                        | Telegram Bot API token                                       |
| `ALLOWED_USER_IDS`   | —                        | Comma-separated Telegram user IDs                            |
| `PLAYLIST_NAME`      | `Futás`                  | Target Apple Music playlist name                             |
| `MUSIC_DIR`          | _(empty)_                | Persistent music directory. If empty, files stay in temp dir |
| `OPENROUTER_API_KEY` | _(empty)_                | OpenRouter API key (optional, skips AI if not set)           |
| `OPENROUTER_MODEL`   | `google/gemma-4-31b-it:free` | OpenRouter model slug for metadata suggestions           |
| `OPENROUTER_APP_NAME`| `apple-music-agent`      | App name shown in OpenRouter dashboard (X-Title header)      |
| `OPENROUTER_APP_URL` | GitHub repo URL          | App URL for OpenRouter rankings (HTTP-Referer header)        |

Additional settings in `music_agent/config.py`:

| Setting                        | Default | Description                  |
| ------------------------------ | ------- | ---------------------------- |
| `MAX_BITRATE_KBPS`             | 192     | Maximum audio bitrate        |
| `MAX_FILE_SIZE_BYTES`          | 195 MB  | Maximum output file size     |
| `ICLOUD_POLL_INTERVAL_SECONDS` | 10      | iCloud sync check interval   |
| `ICLOUD_POLL_TIMEOUT_SECONDS`  | 1200    | iCloud sync timeout (20 min) |

## Deployment (Mac Mini)

The bot is designed to run as a macOS service on a remote Mac Mini.

### First-time install

```bash
make install
```

This will SSH to the Mac Mini and:

- Install system dependencies (python3, yt-dlp, ffmpeg via Homebrew)
- Clone the repository to `~/Agents/Music`
- Create a Python virtual environment and install dependencies
- Prompt for `.env` values (bot token, user IDs, playlist name, OpenRouter config)
- Register and start a launchd LaunchAgent service

### Deploy updates

```bash
make deploy
```

Pulls the latest code from GitHub and restarts the service.

### Other commands

```bash
make logs        # Tail app log (real-time)
make status      # Show service status
make restart     # Restart service
make stop        # Stop service
make logs-stderr # Tail launchd stderr (crashes)
make tail N=100  # Last N lines of the app log
make env         # Edit .env on remote
make ssh         # SSH to Mac Mini
```

### Service details

- LaunchAgent: `ai.torma.apple-music-agent`
- Auto-restarts on crash (`KeepAlive`)
- Starts on login (`RunAtLoad`)
- Logs: `~/Library/Logs/ai.torma.apple-music-agent/` — `agent.log` (app log, rotates at 5 MB, 5 backups) plus launchd's `stdout.log` / `stderr.log`, which now only receive crash output

All settings — remote host included — come from `scripts/config.sh`; the `Makefile` derives its variables from it.

## Project structure

```
├── run.py                          # Entry point
├── music_agent/
│   ├── config.py                   # Configuration (.env + constants)
│   ├── bot.py                      # Telegram bot, multi-platform URL matching
│   ├── pipeline.py                 # Orchestrator, downloader routing
│   ├── converter.py                # ffmpeg wrapper, dynamic bitrate
│   ├── file_lock.py                # cross-agent claim on a MUSIC_DIR file
│   ├── downloaders/
│   │   ├── __init__.py             # BaseDownloader, DownloadResult, factory
│   │   ├── youtube.py              # YouTubeDownloader
│   │   ├── soundcloud.py           # SoundCloudDownloader
│   │   └── mixcloud.py             # MixcloudDownloader
│   └── services/
│       ├── apple_music.py          # AppleScript integration
│       ├── ai_metadata.py          # OpenRouter AI metadata enrichment
│       └── ytdlp_update.py         # yt-dlp upgrade after a failed download
├── .env.example
└── requirements.txt
```
