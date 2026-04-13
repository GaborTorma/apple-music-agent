#!/usr/bin/env bash
set -euo pipefail

# Apple Music Agent — Deploy (pull latest + restart service)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

# --- Helpers ---

info()  { echo "==> $*"; }
error() { echo "ERROR: $*" >&2; exit 1; }

# --- Local / Remote ---

if [[ "${1:-}" != "--local" ]]; then
    echo "Where to deploy?"
    echo "  1) Local (this machine)"
    echo "  2) Remote [${DEFAULT_REMOTE_HOST}]"
    read -rp "Choice [2]: " CHOICE
    CHOICE="${CHOICE:-2}"

    if [[ "$CHOICE" == "2" ]]; then
        read -rp "Remote host [${DEFAULT_REMOTE_HOST}]: " REMOTE_HOST
        REMOTE_HOST="${REMOTE_HOST:-$DEFAULT_REMOTE_HOST}"

        echo "==> Deploying to ${REMOTE_HOST}..."
        ssh -t "$REMOTE_HOST" "~/Agents/Music/scripts/deploy.sh --local"
        exit $?
    fi
fi

# --- Preflight ---

[[ -d "$INSTALL_DIR/.git" ]] || error "Install directory not found: $INSTALL_DIR. Run install.sh first."

if ! launchctl print "gui/$(id -u)/$SERVICE_LABEL" &>/dev/null; then
    error "Service not loaded. Run install.sh first."
fi

# --- Pull latest ---

info "Pulling latest code..."
git -C "$INSTALL_DIR" pull --ff-only

# --- Update dependencies ---

info "Updating Python dependencies..."
"$INSTALL_DIR/.venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

# --- Restart service ---

info "Restarting service..."
launchctl kickstart -k "gui/$(id -u)/$SERVICE_LABEL"

# --- Verify ---

sleep 2

if launchctl print "gui/$(id -u)/$SERVICE_LABEL" 2>&1 | grep -q '"pid"'; then
    PID=$(launchctl print "gui/$(id -u)/$SERVICE_LABEL" 2>&1 | grep '"pid"' | awk '{print $NF}')
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
