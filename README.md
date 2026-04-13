# telegram-to-apple-music

Telegram bot that downloads audio from YouTube, SoundCloud, and Mixcloud links, converts to AAC m4a with dynamic bitrate (max 192kbps/195MB), adds to Apple Music library, waits for iCloud Music Library sync, and adds to a configured playlist. Built for macOS with yt-dlp, ffmpeg, and AppleScript.

## Requirements

- macOS with Apple Music app
- iCloud Music Library enabled
- Python 3.12+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [ffmpeg](https://ffmpeg.org/) (with AAC encoder)

### Install system dependencies

```bash
brew install yt-dlp ffmpeg
```

## Setup

```bash
# Clone
git clone https://github.com/youruser/telegram-to-apple-music.git
cd telegram-to-apple-music

# Virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configuration
cp .env.example .env
```

### macOS permissions

The bot uses AppleScript to control Apple Music. Grant the following permissions in **System Settings → Privacy & Security**:

- **Accessibility**: Add Terminal.app (or the app running the bot)
- **Automation**: Allow Terminal.app to control **Music**

These prompts may appear automatically on first run — click "Allow".

Edit `.env`:

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
ALLOWED_USER_IDS=123456789
PLAYLIST_NAME=Futás
MUSIC_DIR=/Users/Shared/Music
```

### Get your Telegram user ID

1. Set any value for `ALLOWED_USER_IDS`
2. Start the bot and send `/start`
3. The bot replies with your user ID
4. Update `.env` and restart

### Create a Telegram bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the prompts
3. Copy the token to `.env`

## Usage

```bash
source .venv/bin/activate
python3 run.py
```

Send a YouTube, SoundCloud, or Mixcloud link to your bot on Telegram. The bot will:

1. Download the audio (original format)
2. Convert to AAC m4a with dynamic bitrate calculation
3. Add to Apple Music library
4. Wait for iCloud Music Library sync (polls every 60s, max 20 min)
5. Add to the configured playlist

Status updates are sent back via Telegram at each step.

## Supported platforms

| Platform | Example URL |
|---|---|
| YouTube | `https://youtube.com/watch?v=...`, `https://youtu.be/...`, `https://music.youtube.com/watch?v=...` |
| SoundCloud | `https://soundcloud.com/artist/track`, `https://on.soundcloud.com/...` |
| Mixcloud | `https://www.mixcloud.com/artist/mix-name/` |

## Dynamic bitrate

For long mixes (1-2+ hours), the bitrate is automatically reduced to keep the file under 195MB:

```
bitrate = min(192, floor(195MB × 8 × 0.95 / duration_seconds / 1000))
```

If the calculated bitrate drops below 64 kbps, a warning is sent.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | Telegram Bot API token |
| `ALLOWED_USER_IDS` | — | Comma-separated Telegram user IDs |
| `PLAYLIST_NAME` | `Futás` | Target Apple Music playlist name |
| `MUSIC_DIR` | *(empty)* | Persistent music directory. If empty, files stay in temp dir |

Additional settings in `music_agent/config.py`:

| Setting | Default | Description |
|---|---|---|
| `MAX_BITRATE_KBPS` | 192 | Maximum audio bitrate |
| `MAX_FILE_SIZE_BYTES` | 195 MB | Maximum output file size |
| `ICLOUD_POLL_INTERVAL_SECONDS` | 60 | iCloud sync check interval |
| `ICLOUD_POLL_TIMEOUT_SECONDS` | 1200 | iCloud sync timeout (20 min) |

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
- Prompt for `.env` values (bot token, user IDs, playlist name)
- Register and start a launchd LaunchAgent service

### Deploy updates

```bash
make deploy
```

Pulls the latest code from GitHub and restarts the service.

### Other commands

```bash
make logs        # Tail stderr logs (real-time)
make status      # Show service status
make restart     # Restart service
make stop        # Stop service
make tail N=100  # Last N lines of logs
make env         # Edit .env on remote
make ssh         # SSH to Mac Mini
```

### Service details

- LaunchAgent: `com.torma.ai.apple-music-agent`
- Auto-restarts on crash (`KeepAlive`)
- Starts on login (`RunAtLoad`)
- Logs: `~/Library/Logs/apple-music-agent/{stdout,stderr}.log`

Remote host is configured in `Makefile` (`REMOTE_HOST`), all other settings in `scripts/config.sh`.

## Project structure

```
├── run.py                          # Entry point
├── music_agent/
│   ├── config.py                   # Configuration (.env + constants)
│   ├── bot.py                      # Telegram bot, multi-platform URL matching
│   ├── pipeline.py                 # Orchestrator, downloader routing
│   ├── converter.py                # ffmpeg wrapper, dynamic bitrate
│   ├── downloaders/
│   │   ├── __init__.py             # BaseDownloader, DownloadResult, factory
│   │   ├── youtube.py              # YouTubeDownloader
│   │   ├── soundcloud.py           # SoundCloudDownloader
│   │   └── mixcloud.py             # MixcloudDownloader
│   └── services/
│       └── apple_music.py          # AppleScript integration
├── .env.example
└── requirements.txt
```
