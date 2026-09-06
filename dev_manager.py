"""
dev_manager.py — Manages background development servers for projects
(starting, stopping, restarting, log buffering, and status reporting).
"""

import asyncio
import collections
import json
import logging
import os
import signal
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def resolve_project_root(project_path: str) -> Path:
    """Find the real codebase root if nested in a subfolder (e.g. repo/frontend or repo/client)."""
    p = Path(project_path)
    if not p.exists():
        return p
    if (p / "package.json").exists() or (p / "index.html").exists() or (p / "app.json").exists() or (p / "manage.py").exists():
        return p
    for sub in ("project", "app", "web", "client", "frontend", "src", p.name.lower()):
        sub_dir = p / sub
        if sub_dir.is_dir() and ((sub_dir / "package.json").exists() or (sub_dir / "index.html").exists() or (sub_dir / "app.json").exists() or (sub_dir / "manage.py").exists()):
            return sub_dir
    return p


class DevServerManager:
    """Manages a background dev server process for the active workspace."""

    def __init__(self):
        self.process: Optional[asyncio.subprocess.Process] = None
        self.project_dir: Optional[str] = None
        self.command: Optional[str] = None
        self.start_time: Optional[datetime] = None
        self.logs: collections.deque[str] = collections.deque(maxlen=100)
        self._reader_task: Optional[asyncio.Task] = None

    def detect_dev_command(self, project_path: str) -> Optional[str]:
        """Inspect workspace files to guess the default dev server command."""
        path = resolve_project_root(project_path)

        # 1. Expo / React Native
        if (path / "app.json").exists():
            import socket
            open_port = 8081
            for p in [8081, 8082, 8083, 8084, 8085]:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.2)
                    if s.connect_ex(("127.0.0.1", p)) != 0:
                        open_port = p
                        break
            return f"npx expo start --web --port {open_port}"

        # 2. Node / Vite / Next.js
        pkg_json = path / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                scripts = data.get("scripts", {})
                if "dev" in scripts:
                    dev_script = scripts["dev"]
                    if "expo" in dev_script:
                        return "npx expo start --web"
                    return "npm run dev"
                if "start" in scripts:
                    return "npm start"
            except Exception:
                pass

        if (path / "manage.py").exists():
            return "python manage.py runserver"
        if (path / "app.py").exists():
            return "python app.py"
        if (path / "main.py").exists():
            return "python main.py"

        # Static HTML/JS project -> find an available port to avoid collisions with other projects
        if (path / "index.html").exists():
            import socket
            open_port = 5173
            for p in [5173, 3000, 8000, 8081, 5000, 8080]:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.2)
                    if s.connect_ex(("127.0.0.1", p)) != 0:
                        open_port = p
                        break
            return f"python -m http.server {open_port}"

        return "npm run dev"

    async def start(self, project_path: str, custom_cmd: Optional[str] = None) -> tuple[bool, str]:
        """Start the dev server for the given project directory."""
        if self.is_running():
            return False, f"A dev server is already running (PID: {self.process.pid}, command: `{self.command}`). Use `/dev stop` or `/dev restart` first."

        target_dir = resolve_project_root(project_path)
        cmd = custom_cmd or self.detect_dev_command(str(target_dir))
        if not cmd:
            return False, f"Could not determine dev command for `{project_path}`. Specify one via `/dev start <command>`."

        self.project_dir = str(target_dir)
        self.command = cmd
        self.logs.clear()
        self.start_time = datetime.now(timezone.utc)

        try:
            # Launch async subprocess
            self.process = await asyncio.create_subprocess_shell(
                cmd,
                cwd=str(target_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )

            # Start background task to consume and buffer logs
            async def _stream_logs():
                try:
                    while self.process and self.process.stdout:
                        line = await self.process.stdout.readline()
                        if not line:
                            break
                        decoded = line.decode("utf-8", errors="replace").rstrip()
                        if decoded:
                            self.logs.append(decoded)
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.debug("Log reader error: %s", e)

            self._reader_task = asyncio.create_task(_stream_logs())
            logger.info("Dev server started | dir=%s | cmd=%s | PID=%s", project_path, cmd, self.process.pid)
            return True, f"✅ Dev server started!\n• **Command:** `{cmd}`\n• **Directory:** `{project_path}`\n• **PID:** `{self.process.pid}`"
        except Exception as e:
            logger.error("Failed to start dev server: %s", e, exc_info=True)
            return False, f"❌ Failed to start dev server: {e}"

    async def stop(self) -> tuple[bool, str]:
        """Stop the running dev server."""
        if not self.is_running():
            return False, "No dev server is currently running."

        pid = self.process.pid
        cmd = self.command
        try:
            if self._reader_task:
                self._reader_task.cancel()

            if os.name == "nt":
                # On Windows, kill process tree
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    self.process.kill()

            self.process = None
            self.start_time = None
            logger.info("Dev server stopped (PID %s)", pid)
            return True, f"⏹️ Dev server stopped (`{cmd}`, PID: {pid})."
        except Exception as e:
            logger.error("Failed to stop dev server: %s", e, exc_info=True)
            self.process = None
            return False, f"❌ Error stopping dev server: {e}"

    async def restart(self, project_path: Optional[str] = None, custom_cmd: Optional[str] = None) -> tuple[bool, str]:
        """Restart the dev server."""
        target_dir = project_path or self.project_dir
        if not target_dir:
            return False, "No active project directory."
        if self.is_running():
            await self.stop()
            await asyncio.sleep(1.0)
        cmd = custom_cmd or self.detect_dev_command(target_dir)
        return await self.start(target_dir, cmd)

    def is_running(self) -> bool:
        """Check if dev server process is still alive."""
        return self.process is not None and self.process.returncode is None

    def get_port(self) -> Optional[int]:
        """Extract the exact port this dev server is running on."""
        if not self.is_running() or not self.command:
            return None
        import re
        m = re.search(r"(?:--port|-p|\bserver\b)\s+(\d+)", self.command)
        if m:
            return int(m.group(1))
        if self.project_dir:
            from preview_manager import find_project_port
            return find_project_port(self.project_dir)
        return None

    def get_status(self) -> dict:
        """Get status summary for the /dev command."""
        running = self.is_running()
        uptime_str = "None"
        if running and self.start_time:
            delta = datetime.now(timezone.utc) - self.start_time
            mins, secs = divmod(int(delta.total_seconds()), 60)
            hrs, mins = divmod(mins, 60)
            uptime_str = f"{hrs}h {mins}m {secs}s" if hrs else f"{mins}m {secs}s"

        return {
            "running": running,
            "pid": self.process.pid if running else None,
            "command": self.command if running else None,
            "port": self.get_port() if running else None,
            "project_dir": self.project_dir if running else None,
            "uptime": uptime_str,
            "log_count": len(self.logs),
        }

    def get_logs(self, lines: int = 30) -> list[str]:
        """Return the most recent lines of dev server output."""
        return list(self.logs)[-lines:]
