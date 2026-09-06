"""Sanity check for all bot modules and managers."""
import sys
import os

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

from config import Config
print("[OK] config.py")

from message_formatter import format_for_telegram, split_message
print("[OK] message_formatter.py")

from preview_manager import detect_open_port, capture_screenshot
print("[OK] preview_manager.py")

from tunnel_manager import TunnelManager
print("[OK] tunnel_manager.py")

from dev_manager import DevServerManager
print("[OK] dev_manager.py")

from git_manager import get_git_status, get_git_diff
print("[OK] git_manager.py")

from agent_bridge import AgentBridge
print("[OK] agent_bridge.py")

from bot import main
print("[OK] bot.py")

print("\n🎉 All 8 modules import cleanly!")
