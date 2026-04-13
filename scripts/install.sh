#!/usr/bin/env bash
set -euo pipefail

# Apple Music Agent — First-time install script
# Idempotent: safe to re-run

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Local / Remote ---

if [[ "${1:-}" != "--local" ]]; then
    # Source config for DEFAULT_REMOTE_HOST (only works when run from repo)
    if [[ -f "$SCRIPT_DIR/config.sh" ]]; then
        source "$SCRIPT_DIR/config.sh"
    else
        DEFAULT_REMOTE_HOST="macclaw.local"
        PLIST_NAME="com.torma.ai.apple-music-agent.plist"
    fi

    echo "Where to install?"
    echo "  1) Local (this machine)"
    echo "  2) Remote [${DEFAULT_REMOTE_HOST}]"
    read -rp "Choice [2]: " CHOICE
    CHOICE="${CHOICE:-2}"

    if [[ "$CHOICE" == "2" ]]; then
        read -rp "Remote host [${DEFAULT_REMOTE_HOST}]: " REMOTE_HOST
        REMOTE_HOST="${REMOTE_HOST:-$DEFAULT_REMOTE_HOST}"

        echo "==> Installing on ${REMOTE_HOST}..."
        # Copy scripts to remote /tmp (repo may not exist there yet)
        scp -q "$SCRIPT_DIR/config.sh" "$SCRIPT_DIR/install.sh" "$SCRIPT_DIR/$PLIST_NAME" "$SCRIPT_DIR/run-agent.sh" "${REMOTE_HOST}:/tmp/"
        ssh -t "$REMOTE_HOST" "bash /tmp/install.sh --local"
        exit $?
    fi
    # Choice 1: fall through to local install
fi

# --- Config ---

# When run from /tmp (remote), SCRIPT_DIR points to /tmp
if [[ -f "$SCRIPT_DIR/config.sh" ]]; then
    source "$SCRIPT_DIR/config.sh"
else
    error "config.sh nem található: $SCRIPT_DIR/config.sh"
fi

# --- Helpers ---

info()  { echo "==> $*"; }
error() { echo "ERROR: $*" >&2; exit 1; }

# --- Preflight ---

[[ "$(uname -s)" == "Darwin" ]] || error "This script only runs on macOS"

# --- Homebrew ---

# Ensure brew is in PATH (non-login SSH shells don't source profile)
eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null || true)"

if ! command -v brew &>/dev/null; then
    info "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null)"
fi

info "Checking system dependencies..."
for pkg in python3 yt-dlp ffmpeg ollama; do
    if command -v "$pkg" &>/dev/null; then
        info "$pkg already installed"
    else
        info "Installing $pkg..."
        brew install "$pkg"
    fi
done

# --- Clone or update repo ---

if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Repository already exists, pulling latest..."
    git -C "$INSTALL_DIR" checkout -- .
    git -C "$INSTALL_DIR" pull --ff-only
else
    info "Cloning repository..."
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

# --- Symlink for process name ---

RUN_SCRIPT="$INSTALL_DIR/scripts/run-agent.sh"
[[ -f "$RUN_SCRIPT" ]] || { cp /tmp/run-agent.sh "$INSTALL_DIR/scripts/"; RUN_SCRIPT="$INSTALL_DIR/scripts/run-agent.sh"; }
ln -sf "$RUN_SCRIPT" "$INSTALL_DIR/torma.ai.apple-music-agent"

# --- Python venv ---

info "Setting up Python virtual environment..."
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

# --- .env configuration ---

if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    info "Creating .env configuration..."
    echo ""

    read -rp "TELEGRAM_BOT_TOKEN: " BOT_TOKEN
    [[ -n "$BOT_TOKEN" ]] || error "TELEGRAM_BOT_TOKEN is required"

    read -rp "ALLOWED_USER_IDS (comma-separated): " USER_IDS
    [[ -n "$USER_IDS" ]] || error "ALLOWED_USER_IDS is required"

    read -rp "PLAYLIST_NAME [Futás]: " PLAYLIST
    PLAYLIST="${PLAYLIST:-Futás}"

    read -rp "MUSIC_DIR (leave empty for temp dir): " MUSIC_DIR_VAL

    read -rp "OLLAMA_HOST [http://localhost:11434]: " OLLAMA_HOST_VAL
    OLLAMA_HOST_VAL="${OLLAMA_HOST_VAL:-http://localhost:11434}"

    read -rp "OLLAMA_MODEL [gemma4:e2b]: " OLLAMA_MODEL_VAL
    OLLAMA_MODEL_VAL="${OLLAMA_MODEL_VAL:-gemma4:e2b}"

    read -rp "OLLAMA_API_KEY (leave empty if not needed): " OLLAMA_API_KEY_VAL

    cat > "$INSTALL_DIR/.env" <<EOF
TELEGRAM_BOT_TOKEN=$BOT_TOKEN
ALLOWED_USER_IDS=$USER_IDS
PLAYLIST_NAME=$PLAYLIST
MUSIC_DIR=$MUSIC_DIR_VAL
OLLAMA_HOST=$OLLAMA_HOST_VAL
OLLAMA_MODEL=$OLLAMA_MODEL_VAL
OLLAMA_API_KEY=$OLLAMA_API_KEY_VAL
EOF

    info ".env created"
else
    info ".env already exists, skipping configuration"
fi

# --- Log directory ---

mkdir -p "$LOG_DIR"

# --- LaunchAgent plist ---

info "Installing LaunchAgent..."
mkdir -p "$HOME/Library/LaunchAgents"

# Plist template: prefer repo copy, fallback to /tmp (first install before push)
PLIST_TEMPLATE="$INSTALL_DIR/scripts/$PLIST_NAME"
[[ -f "$PLIST_TEMPLATE" ]] || PLIST_TEMPLATE="/tmp/$PLIST_NAME"

sed -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
    -e "s|__HOME__|$HOME|g" \
    "$PLIST_TEMPLATE" > "$PLIST_PATH"

plutil -lint "$PLIST_PATH" || error "Plist validation failed"

# --- Load service ---

info "Loading service..."
launchctl bootout "gui/$(id -u)/$SERVICE_LABEL" 2>/dev/null || true
sleep 1
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"

# --- Status ---

echo ""
info "Installation complete!"
echo ""
echo "Service status:"
launchctl print "gui/$(id -u)/$SERVICE_LABEL" 2>&1 | head -15
echo ""
echo "Logs:"
echo "  stdout: $LOG_DIR/stdout.log"
echo "  stderr: $LOG_DIR/stderr.log"
echo ""
echo "IMPORTANT — Grant these permissions in System Settings > Privacy & Security:"
echo "  1. Accessibility: allow Terminal.app (or the shell running the bot)"
echo "  2. Automation: allow Terminal.app to control Music.app"
echo ""
echo "Manage the service:"
echo "  Restart: launchctl kickstart -k gui/$(id -u)/$SERVICE_LABEL"
echo "  Stop:    launchctl kill SIGTERM gui/$(id -u)/$SERVICE_LABEL"
echo "  Logs:    tail -f $LOG_DIR/stderr.log"
