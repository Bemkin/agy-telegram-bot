#!/usr/bin/env bash
# agy-telegram-bot launcher for macOS and Linux

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export PYTHONIOENCODING=utf-8

if command -v python3 &>/dev/null; then
    python3 bot.py
elif command -v python &>/dev/null; then
    python bot.py
else
    echo "Error: Python is not installed or not in PATH."
    exit 1
fi
