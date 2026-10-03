#!/usr/bin/env bash
# Pinned Python for the agent — sourced by install.sh and deploy.sh (needs INSTALL_DIR)
#
# Homebrew's Python is ad-hoc signed, so every rebuild (patch upgrade, new bottle after a
# macOS update) gets a new code identity and macOS drops its Automation grant for Music
# (AppleScript -1743). This interpreter is a uv-managed CPython inside INSTALL_DIR at the
# exact patch in .python-version: it changes only when that file is bumped.

ensure_venv() {
    eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null || true)"
    command -v uv &>/dev/null || brew install uv

    local version
    version="$(<"$INSTALL_DIR/.python-version")"
    export UV_PYTHON_INSTALL_DIR="$INSTALL_DIR/.python"
    uv python install --no-bin "$version"

    # An explicit patch version keeps uv from moving the venv to a newer patch on its own
    local home
    home="$(sed -n 's/^home = //p' "$INSTALL_DIR/.venv/pyvenv.cfg" 2>/dev/null || true)"
    if [[ "$home" != "$UV_PYTHON_INSTALL_DIR/cpython-$version-"* ]]; then
        echo "==> Creating virtual environment on Python $version (Music Automation must be granted again)"
        uv venv --clear --managed-python --python "$version" "$INSTALL_DIR/.venv"
    fi
    uv pip install --quiet --python "$INSTALL_DIR/.venv/bin/python" -r "$INSTALL_DIR/requirements.txt"
}
