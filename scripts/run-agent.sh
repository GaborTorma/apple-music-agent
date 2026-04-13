#!/usr/bin/env bash
# Wrapper script for launchd — its filename appears in macOS background items
# Resolve symlink so SCRIPT_DIR points to scripts/, not the symlink's directory
SCRIPT="${BASH_SOURCE[0]}"
[ -L "$SCRIPT" ] && SCRIPT="$(readlink "$SCRIPT")"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT")" && pwd)"
INSTALL_DIR="$(dirname "$SCRIPT_DIR")"
exec "$INSTALL_DIR/.venv/bin/python3" "$INSTALL_DIR/run.py"
