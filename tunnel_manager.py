"""
tunnel_manager.py — Manages Cloudflare quick tunnels (trycloudflare.com)
using the local cloudflared binary to expose local development servers.
"""

import asyncio
import logging
import os
import re
import signal
import subprocess
from pathlib import Path
from typing import Optional

from preview_manager import detect_open_port

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")


def _find_cloudflared_bin() -> str:
    """Find the downloaded cloudflared.exe binary path."""
    # Check pycloudflared package directory
    try:
        import pycloudflared.util as pcf_util
        exe = pcf_util.get_info().executable
        if Path(exe).exists():
            return exe
    except Exception:
        pass

    # Check local bot directory
    local_cf = Path(__file__).parent / "cloudflared.exe"
    if local_cf.exists():
        return str(local_cf)

    return "cloudflared"


class TunnelManager:
    """Manages active Cloudflare tunnels."""

    def __init__(self):
        self.active_port: Optional[int] = None
        self.active_url: Optional[str] = None
        self.process: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None

    async def start_tunnel(
        self,
        port: Optional[int] = None,
        project_path: Optional[str] = None,
        dev_mgr: Optional[object] = None,
    ) -> tuple[str, int]:
        """
        Start a Cloudflare tunnel pointing to http://localhost:{port}.
        """
        if port is None:
            # 1. If dev_mgr has a running server for this project, use its exact port
            if dev_mgr and getattr(dev_mgr, "is_running", lambda: False)():
                mgr_proj = getattr(dev_mgr, "project_dir", "")
                if not project_path or str(mgr_proj).lower() == str(project_path).lower():
                    port = getattr(dev_mgr, "get_port", lambda: None)()

            # 2. If port is still None, detect configured port for project
            if port is None:
                detected = detect_open_port(project_path=project_path)
                if not detected:
                    proj_name = Path(project_path).name if project_path else "active project"
                    raise RuntimeError(
                        f"No running dev server detected for '{proj_name}'. "
                        f"Please start the dev server first via the [⚡ Dev Server] button or by running `/dev start`."
                    )
                port = detected

        # If already running on this port, return existing
        if self.active_port == port and self.active_url and self.process:
            return self.active_url, port

        # Stop existing tunnel if port changed or restarting
        if self.active_port:
            await self.stop_tunnel()

        cloudflared_exe = _find_cloudflared_bin()
        # Use http://localhost:{port} so it correctly routes to Node/Vite (IPv6 or IPv4)
        target_url = f"http://localhost:{port}"

        args = [
            cloudflared_exe,
            "tunnel",
            "--url",
            target_url,
            "--no-autoupdate",
        ]

        logger.info("Spawning cloudflared: %s on %s", cloudflared_exe, target_url)

        self.process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )

        tunnel_url = None
        # Read stderr lines to find the trycloudflare.com URL
        for _ in range(60):
            if not self.process or not self.process.stderr:
                break
            line_bytes = await self.process.stderr.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace")
            m = URL_PATTERN.search(line)
            if m:
                tunnel_url = m.group(0)
                break

        if not tunnel_url:
            await self.stop_tunnel()
            raise RuntimeError("Cloudflare tunnel started but did not return a public URL.")

        self.active_port = port
        self.active_url = tunnel_url
        logger.info("Tunnel active on port %d -> %s", port, self.active_url)
        return self.active_url, port

    async def stop_tunnel(self) -> Optional[int]:
        """Stop the currently active tunnel process."""
        port = self.active_port
        if self.process:
            pid = self.process.pid
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
                    self.process.terminate()
            except Exception as e:
                logger.warning("Error stopping tunnel process: %s", e)

            self.process = None

        self.active_port = None
        self.active_url = None
        logger.info("Tunnel stopped")
        return port

    def get_status(self) -> Optional[dict]:
        """Return details about the currently active tunnel."""
        if not self.active_url or not self.active_port:
            return None
        return {
            "url": self.active_url,
            "port": self.active_port,
        }
