"""
git_manager.py — Async helper functions for inspecting and managing Git repositories
(status, log, diff, push, pull).
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


async def _run_git(args: list[str], cwd: str) -> tuple[int, str, str]:
    """Execute a git command asynchronously in the specified directory."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await proc.communicate()
    stdout = stdout_b.decode("utf-8", errors="replace").strip()
    stderr = stderr_b.decode("utf-8", errors="replace").strip()
    return proc.returncode or 0, stdout, stderr


async def get_git_status(cwd: str) -> dict:
    """Return structured git status for the directory."""
    # Check if git repo
    code, branch, _ = await _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if code != 0:
        return {"is_git": False, "error": "Not a git repository."}

    # Short status
    _, status_out, _ = await _run_git(["status", "--short"], cwd)
    # Recent log
    _, log_out, _ = await _run_git(["log", "--oneline", "-n", "3"], cwd)

    # Count modified / untracked
    modified = []
    untracked = []
    for line in status_out.splitlines():
        if line.startswith("??"):
            untracked.append(line[3:])
        elif line.strip():
            modified.append(line.strip())

    return {
        "is_git": True,
        "branch": branch,
        "clean": len(status_out.strip()) == 0,
        "modified": modified,
        "untracked": untracked,
        "recent_log": log_out.splitlines() if log_out else [],
    }


async def get_git_diff(cwd: str, staged: bool = False) -> str:
    """Return diff or diff stat summary."""
    args = ["diff", "--stat"]
    if staged:
        args.append("--cached")
    code, out, err = await _run_git(args, cwd)
    if code != 0:
        return f"Git error: {err}"
    if not out.strip():
        return "No changes detected (working tree clean)."
    return out


async def git_push(cwd: str) -> tuple[bool, str]:
    """Push current branch to remote."""
    code, out, err = await _run_git(["push"], cwd)
    output = out or err or "Pushed successfully."
    return code == 0, output


async def git_pull(cwd: str) -> tuple[bool, str]:
    """Pull changes with rebase."""
    code, out, err = await _run_git(["pull", "--rebase"], cwd)
    output = out or err or "Pulled successfully."
    return code == 0, output


async def get_git_log(cwd: str, count: int = 5) -> str:
    """Get pretty git log."""
    code, out, err = await _run_git(
        ["log", f"-n{count}", "--pretty=format:%h - %an (%cr): %s"], cwd
    )
    if code != 0:
        return f"Git error: {err}"
    return out or "No commit history found."
