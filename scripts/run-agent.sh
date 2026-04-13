#!/usr/bin/env bash
# Wrapper script for launchd — its filename appears in macOS background items
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$(dirname "$SCRIPT_DIR")"
exec "$INSTALL_DIR/.venv/bin/python3" "$INSTALL_DIR/run.py"
