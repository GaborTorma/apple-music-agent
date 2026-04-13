#!/usr/bin/env bash
set -euo pipefail

# Apple Music Agent — Deploy (pull latest + restart service)
#
# Usage:
#   deploy.sh              — interactive menu (default: local)
#   deploy.sh --local      — local deploy, no questions
#   deploy.sh --remote user@host  — remote deploy, no questions

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

# --- Helpers ---

info()  { echo "==> $*"; }
error() { echo "ERROR: $*" >&2; exit 1; }

# --- Parse arguments ---

MODE=""
REMOTE_TARGET=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --local)
            MODE="local"
            shift
            ;;
        --remote)
            MODE="remote"
            REMOTE_TARGET="${2:?--remote requires user@host}"
            shift 2
            ;;
        *)
            error "Unknown argument: $1"
            ;;
    esac
done

# --- Interactive menu (if no mode specified) ---

if [[ -z "$MODE" ]]; then
    echo "Where to deploy?"
    echo "  1) Local (this machine)"
    echo "  2) Remote"
    read -rp "Choice [1]: " CHOICE
    CHOICE="${CHOICE:-1}"

    if [[ "$CHOICE" == "2" ]]; then
        if [[ -n "${DEFAULT_REMOTE_USER:-}" ]]; then
            read -rp "Remote user [${DEFAULT_REMOTE_USER}]: " REMOTE_USER
            REMOTE_USER="${REMOTE_USER:-$DEFAULT_REMOTE_USER}"
        else
            read -rp "Remote user: " REMOTE_USER
            [[ -n "$REMOTE_USER" ]] || { echo "ERROR: Remote user is required" >&2; exit 1; }
        fi

        if [[ -n "${DEFAULT_REMOTE_HOST:-}" ]]; then
            read -rp "Remote host [${DEFAULT_REMOTE_HOST}]: " REMOTE_HOST
            REMOTE_HOST="${REMOTE_HOST:-$DEFAULT_REMOTE_HOST}"
        else
            read -rp "Remote host: " REMOTE_HOST
            [[ -n "$REMOTE_HOST" ]] || { echo "ERROR: Remote host is required" >&2; exit 1; }
        fi

        REMOTE_TARGET="${REMOTE_USER}@${REMOTE_HOST}"
        MODE="remote"
    else
        MODE="local"
    fi
fi

# --- Remote deploy ---

if [[ "$MODE" == "remote" ]]; then
    info "Deploying to ${REMOTE_TARGET}..."
    ssh -t "$REMOTE_TARGET" "~/Agents/Music/scripts/deploy.sh --local"
    exit $?
fi

# --- Preflight ---

[[ -d "$INSTALL_DIR/.git" ]] || error "Install directory not found: $INSTALL_DIR. Run install.sh first."

if ! launchctl print "gui/$(id -u)/$SERVICE_LABEL" &>/dev/null; then
    error "Service not loaded. Run install.sh first."
fi

# --- Pull latest ---

info "Pulling latest code..."
git -C "$INSTALL_DIR" checkout -- .
git -C "$INSTALL_DIR" pull --ff-only

# --- Update dependencies ---

info "Updating Python dependencies..."
"$INSTALL_DIR/.venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

# --- Restart service ---

info "Restarting service..."
launchctl kickstart -k "gui/$(id -u)/$SERVICE_LABEL"

# --- Verify ---

sleep 2

if launchctl print "gui/$(id -u)/$SERVICE_LABEL" 2>&1 | grep -q 'pid = '; then
    PID=$(launchctl print "gui/$(id -u)/$SERVICE_LABEL" 2>&1 | grep 'pid = ' | awk '{print $NF}')
    info "Service running (PID: $PID)"
else
    echo ""
    error "Service failed to start. Recent logs:"
    tail -20 "$LOG_DIR/stderr.log"
    exit 1
fi

# --- Summary ---

echo ""
info "Deploy complete!"
echo "  Commit: $(git -C "$INSTALL_DIR" log -1 --format='%h %s')"
echo "  Time:   $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
echo "=== Recent logs ==="
tail -20 "$LOG_DIR/stderr.log"
