"""
audit_logger.py — Logs all mobile interactions, prompts, and file modifications
to clean, human-readable Markdown files and structured JSON on your laptop for full auditability.
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Default global logs directory
LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_JSON = LOGS_DIR / "history.json"


def extract_files_from_text(text: str, project_dir: str = "") -> List[str]:
    """Extract code and config filenames referenced in prompt or response text."""
    # Pattern for common file paths like src/components/Header.tsx, vite.config.ts, etc.
    file_pattern = r"(?:[\w\-./\\]+\.(?:tsx|ts|jsx|js|py|json|css|scss|html|md|env|yml|yaml|sql))"
    matches = re.findall(file_pattern, text, re.IGNORECASE)
    
    unique_files = []
    for m in matches:
        cleaned = m.strip("`'\"(),:; ")
        # Filter out obvious false positives (e.g. node_modules or standard URLs)
        if (
            not cleaned.startswith("http")
            and not cleaned.startswith("npm")
            and len(cleaned) > 3
            and cleaned not in unique_files
        ):
            unique_files.append(cleaned)
    return unique_files[:8]


def log_interaction(
    prompt: str,
    response: str,
    project_dir: str,
    model_name: str,
    user_id: int | str,
    files_changed: Optional[List[str]] = None,
    mode: str = "act",
) -> Path:
    """
    Append an auditable record of the user's prompt and agent response to:
    1. Global daily log file: agy-telegram-bot/logs/audit_YYYY-MM-DD.md
    2. Project-level audit log: <project_dir>/.agent/audit.md
    3. Structured JSON timeline: agy-telegram-bot/logs/history.json
    """
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    rel_time = now.strftime("%H:%M")

    # Detect referenced files if not explicitly provided
    detected_files = files_changed or extract_files_from_text(f"{prompt}\n{response}", project_dir)

    files_md = "\n".join(f"  • `{f}`" for f in detected_files) if detected_files else "  • *(Exploratory / reasoning)*"

    log_entry = (
        f"## 📱 [{time_str}] Mobile Interaction\n\n"
        f"• **Workspace:** `{project_dir}`\n"
        f"• **Model:** `{model_name}`\n"
        f"• **Mode:** `{mode}`\n"
        f"• **Telegram User:** `{user_id}`\n"
        f"• **Files Touched/Targeted:**\n{files_md}\n\n"
        f"### 👤 Prompt\n"
        f"> {prompt.strip().replace(chr(10), chr(10) + '> ')}\n\n"
        f"### 🤖 Agent Execution & Output\n"
        f"{response.strip()}\n\n"
        f"---\n\n"
    )

    # 1. Write to global daily log file
    global_file = LOGS_DIR / f"audit_{date_str}.md"
    try:
        if not global_file.exists():
            global_file.write_text(
                f"# 📋 Antigravity Agent Audit Log — {date_str}\n\n"
                f"> Full record of all coding tasks, prompts, and actions executed remotely from Telegram.\n\n---\n\n",
                encoding="utf-8",
            )
        with open(global_file, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        logger.warning("Could not write to global audit log: %s", e)

    # 2. Write to project-specific .agent/audit.md
    try:
        proj_agent_dir = Path(project_dir) / ".agent"
        proj_agent_dir.mkdir(parents=True, exist_ok=True)
        proj_log = proj_agent_dir / "audit.md"
        if not proj_log.exists():
            proj_log.write_text(
                f"# 📋 Project Audit Trail — Remote Mobile Agent\n\n---\n\n",
                encoding="utf-8",
            )
        with open(proj_log, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        logger.debug("Could not write to project-level audit log: %s", e)

    # 3. Append to structured JSON history
    try:
        history_record = {
            "id": f"rec-{int(now.timestamp())}",
            "timestamp": time_str,
            "time_short": rel_time,
            "project": Path(project_dir).name if project_dir else "Workspace",
            "project_dir": project_dir,
            "model": model_name,
            "mode": mode,
            "prompt": prompt.strip(),
            "summary": response.strip()[:240] + ("..." if len(response) > 240 else ""),
            "full_response": response.strip(),
            "files": detected_files,
        }

        records = []
        if HISTORY_JSON.exists():
            try:
                records = json.loads(HISTORY_JSON.read_text(encoding="utf-8"))
            except Exception:
                records = []

        records.insert(0, history_record)
        # Keep recent 200 records
        records = records[:200]
        HISTORY_JSON.write_text(json.dumps(records, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("Could not write structured history JSON: %s", e)

    return global_file


def get_structured_history(project_dir: Optional[str] = None, limit: int = 50) -> List[dict]:
    """Retrieve structured list of all past mobile prompts, files changed, and actions."""
    if not HISTORY_JSON.exists():
        return []

    try:
        records = json.loads(HISTORY_JSON.read_text(encoding="utf-8"))
        if project_dir:
            proj_norm = project_dir.lower().replace("\\", "/")
            records = [
                r for r in records
                if r.get("project_dir", "").lower().replace("\\", "/") == proj_norm
                or not r.get("project_dir")
            ]
        return records[:limit]
    except Exception as e:
        logger.error("Error reading history JSON: %s", e)
        return []


def get_latest_audit_entries(count: int = 5) -> str:
    """Return the most recent audit log entries from the latest log file."""
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    global_file = LOGS_DIR / f"audit_{date_str}.md"

    if not global_file.exists():
        log_files = sorted(LOGS_DIR.glob("audit_*.md"), reverse=True)
        if not log_files:
            return "📋 No audit logs recorded yet."
        global_file = log_files[0]

    try:
        return global_file.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading audit log: {e}"
