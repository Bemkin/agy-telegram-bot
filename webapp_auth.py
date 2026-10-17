"""
webapp_auth.py — Verifies Telegram Mini App launch data (initData).

The Mission Control API is reachable through a public Cloudflare tunnel, so every
/api request must prove it comes from the bot owner's Telegram client. Telegram
signs initData with a key derived from the bot token; we recompute that signature,
reject stale data, and check the user against AUTHORIZED_USER_ID.

Spec: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
import time
from typing import Optional
from urllib.parse import parse_qsl

INIT_DATA_HEADER = "X-Telegram-Init-Data"
DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60


class InitDataError(Exception):
    """Raised when initData is missing, forged, expired or from another user."""


def validate_init_data(
    init_data: Optional[str],
    bot_token: str,
    authorized_user_id: int,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    now: Optional[float] = None,
) -> dict:
    """Return the Telegram user dict if init_data is valid for the authorized user."""
    if not init_data:
        raise InitDataError("missing initData")
    if not bot_token or not authorized_user_id:
        raise InitDataError("server is not configured for Mini App auth")

    fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    received_hash = fields.pop("hash", None)
    if not received_hash:
        raise InitDataError("initData has no hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise InitDataError("initData signature mismatch")

    try:
        auth_date = int(fields.get("auth_date", "0"))
    except ValueError:
        raise InitDataError("initData auth_date is invalid")
    current = time.time() if now is None else now
    if auth_date <= 0 or current - auth_date > max_age_seconds:
        raise InitDataError("initData has expired")

    try:
        user = json.loads(fields.get("user", ""))
    except json.JSONDecodeError:
        raise InitDataError("initData user is invalid")
    if not isinstance(user, dict) or user.get("id") != authorized_user_id:
        raise InitDataError("user is not authorized")

    return user


def sign_init_data(fields: dict, bot_token: str) -> str:
    """Build a signed initData query string. Used by tests to simulate Telegram."""
    from urllib.parse import urlencode

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": signature})
