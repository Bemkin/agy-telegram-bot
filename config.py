"""
Configuration for the Antigravity Telegram Bot.
Loads secrets from .env and provides sensible defaults.
"""

import os
import sys
from pathlib import Path

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass  # dotenv is optional; users can set env vars directly


class Config:
    """Central configuration. All values come from environment variables."""

    # ── Telegram ──────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    AUTHORIZED_USER_ID: int = int(os.getenv("AUTHORIZED_USER_ID", "0"))

    # ── Antigravity Agent ─────────────────────────────────────────────
    DEFAULT_PROJECT_DIR: str = os.getenv(
        "DEFAULT_PROJECT_DIR",
        str(Path.home() / "Documents"),
    )
    PROJECTS_ROOT: str = os.getenv(
        "PROJECTS_ROOT",
        str(Path(DEFAULT_PROJECT_DIR).parent if Path(DEFAULT_PROJECT_DIR).exists() else Path.home() / "Projects"),
    )
    AGENT_MODEL: str = os.getenv("AGENT_MODEL", "")  # Empty = SDK default

    # ── Telegram message limits ───────────────────────────────────────
    MAX_MESSAGE_LENGTH: int = 4096  # Telegram hard cap

    # ── Voice notes (optional) ────────────────────────────────────────
    VOICE_ENABLED: bool = os.getenv("VOICE_ENABLED", "false").lower() == "true"

    # ── Gemini API Key ────────────────────────────────────────────────
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    @classmethod
    def validate(cls) -> None:
        """Validate required configuration on startup."""
        errors: list[str] = []
        if not cls.TELEGRAM_BOT_TOKEN:
            errors.append(
                "TELEGRAM_BOT_TOKEN is not set. "
                "Create a bot via @BotFather and add the token to .env"
            )
        if cls.AUTHORIZED_USER_ID == 0:
            errors.append(
                "AUTHORIZED_USER_ID is not set. "
                "Get your Telegram user ID from @userinfobot and add it to .env"
            )
        if not Path(cls.DEFAULT_PROJECT_DIR).is_dir():
            errors.append(
                f"DEFAULT_PROJECT_DIR does not exist: {cls.DEFAULT_PROJECT_DIR}"
            )
        if errors:
            for e in errors:
                print(f"❌ {e}", file=sys.stderr)
            sys.exit(1)
