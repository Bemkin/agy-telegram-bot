"""
Converts the Antigravity agent's rich Markdown responses into
Telegram-compatible HTML and splits them into ≤ 4096-char chunks.
"""

import re
import html as html_mod
from config import Config


# ── Markdown → Telegram HTML ─────────────────────────────────────────

def _extract_blocks(text: str) -> list[tuple[str, str]]:
    """
    Split *text* into a list of (kind, content) tuples.
    kind is 'code' for fenced code blocks or 'text' for everything else.
    """
    parts: list[tuple[str, str]] = []
    # Match fenced code blocks (``` ... ```)
    pattern = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
    last_end = 0
    for m in pattern.finditer(text):
        if m.start() > last_end:
            parts.append(("text", text[last_end : m.start()]))
        lang = m.group(1)
        code = m.group(2).rstrip("\n")
        if lang:
            parts.append(("code", f'<pre><code class="language-{html_mod.escape(lang)}">{html_mod.escape(code)}</code></pre>'))
        else:
            parts.append(("code", f"<pre>{html_mod.escape(code)}</pre>"))
        last_end = m.end()
    if last_end < len(text):
        parts.append(("text", text[last_end:]))
    return parts


def _convert_inline(text: str) -> str:
    """Convert inline Markdown formatting to Telegram HTML."""
    # Escape HTML entities first (outside code blocks)
    text = html_mod.escape(text)

    # Inline code: `code` → <code>code</code>
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # Italic: *text* or _text_  (but not inside words like file_name)
    text = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"<i>\1</i>", text)

    # Strikethrough: ~~text~~
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # Links: [text](url)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2">\1</a>',
        text,
    )

    # Headings: turn ### Heading into bold text
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Horizontal rules
    text = re.sub(r"^---+$", "─" * 20, text, flags=re.MULTILINE)

    # Bullet points: ensure they look clean
    text = re.sub(r"^(\s*)[*-]\s+", r"\1• ", text, flags=re.MULTILINE)

    return text


def format_for_telegram(markdown_text: str) -> str:
    """
    Convert a full Markdown response from the Antigravity agent
    into Telegram-compatible HTML.
    """
    blocks = _extract_blocks(markdown_text)
    result_parts: list[str] = []
    for kind, content in blocks:
        if kind == "code":
            result_parts.append(content)  # Already HTML-formatted
        else:
            result_parts.append(_convert_inline(content))
    return "".join(result_parts).strip()


# ── Message splitting ─────────────────────────────────────────────────

def split_message(html_text: str, max_len: int | None = None) -> list[str]:
    """
    Split an HTML string into chunks that fit within Telegram's
    4096-character message limit.

    Tries to split at paragraph boundaries first, then at newlines,
    then hard-cuts as a last resort.
    """
    max_len = max_len or Config.MAX_MESSAGE_LENGTH
    if len(html_text) <= max_len:
        return [html_text]

    chunks: list[str] = []
    remaining = html_text

    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining.strip())
            break

        # Try to split at a double-newline (paragraph break)
        cut = remaining.rfind("\n\n", 0, max_len)

        # Try single newline
        if cut <= 0:
            cut = remaining.rfind("\n", 0, max_len)

        # Try space
        if cut <= 0:
            cut = remaining.rfind(" ", 0, max_len)

        # Hard cut as last resort
        if cut <= 0:
            cut = max_len

        chunk = remaining[:cut].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut:].strip()

    return chunks if chunks else [html_text[:max_len]]
