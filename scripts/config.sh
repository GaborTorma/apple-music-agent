#!/usr/bin/env bash
# Shared configuration for install.sh and deploy.sh

INSTALL_DIR="$HOME/Agents/Music"
SERVICE_LABEL="ai.torma.apple-music-agent"
PLIST_NAME="ai.torma.apple-music-agent.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"
LOG_DIR="$HOME/Library/Logs/ai.torma.apple-music-agent"
REPO_URL="https://github.com/GaborTorma/apple-music-agent.git"
DEFAULT_REMOTE_HOST="macclaw.local"
