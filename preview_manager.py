"""
preview_manager.py — Captures screenshots of localhost routes using Playwright
and returns raw image bytes to send as Telegram photos.
"""

import asyncio
import io
import logging
import re
import socket
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

# Common dev server ports to scan if no port is specified
COMMON_PORTS = [8080, 5173, 3000, 4000, 8000, 5000, 3001, 8081]


def find_project_port(project_path: Optional[str] = None) -> Optional[int]:
    """Inspect project config files (vite.config, package.json, next.config, .env, app.json) to detect configured or framework port."""
    if not project_path:
        return None

    try:
        from dev_manager import resolve_project_root
        path = resolve_project_root(project_path)
    except Exception:
        path = Path(project_path)

    dirs_to_check = [path]
    # Check immediate subdirectories in case of nested app (e.g. repo/frontend)
    if path.is_dir():
        for sub in path.iterdir():
            if sub.is_dir() and not sub.name.startswith("."):
                dirs_to_check.append(sub)

    import re
    # 1. First check explicit port overrides in configs
    for d in dirs_to_check:
        # Check vite.config.ts / js / mjs
        for vc in ("vite.config.ts", "vite.config.js", "vite.config.mjs"):
            f = d / vc
            if f.exists():
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                    m = re.search(r"port\s*:\s*(\d+)", content)
                    if m:
                        return int(m.group(1))
                except Exception:
                    pass

        # Check package.json scripts for --port XXXX or -p XXXX
        pkg = d / "package.json"
        if pkg.exists():
            try:
                content = pkg.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r"(?:--port|-p)\s+(\d+)", content)
                if m:
                    return int(m.group(1))
            except Exception:
                pass

        # Check .env for PORT=XXXX
        env_f = d / ".env"
        if env_f.exists():
            try:
                content = env_f.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r"^PORT\s*=\s*(\d+)", content, re.MULTILINE)
                if m:
                    return int(m.group(1))
            except Exception:
                pass

    # 2. If no explicit port found, detect framework default port
    for d in dirs_to_check:
        # Next.js -> 3000
        if (d / "next.config.ts").exists() or (d / "next.config.js").exists() or (d / "next.config.mjs").exists() or (d / ".next").exists():
            return 3000

        # Vite default -> 5173
        for vc in ("vite.config.ts", "vite.config.js", "vite.config.mjs"):
            if (d / vc).exists():
                return 5173

        # Expo / React Native -> check active Expo ports (8081-8085)
        if (d / "app.json").exists() or (d / "expo-env.d.ts").exists():
            for p in [8081, 8082, 8083, 8084, 8085]:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.2)
                    if s.connect_ex(("127.0.0.1", p)) == 0:
                        return p
            return 8081

        # Static HTML default port
        if (d / "index.html").exists():
            return 5173

    return None


def get_all_open_ports(host: str = "127.0.0.1", ports: list[int] = COMMON_PORTS) -> list[int]:
    """Return all currently open dev server ports."""
    open_ports = []
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex((host, port)) == 0:
                open_ports.append(port)
    return open_ports


def detect_open_port(
    host: str = "127.0.0.1",
    ports: list[int] = COMMON_PORTS,
    project_path: Optional[str] = None,
) -> Optional[int]:
    """
    Check open ports for the active project.
    Strictly checks the project's configured or framework port first.
    Never falls back to scanning other open ports on the machine.
    """
    proj_port = find_project_port(project_path)
    if proj_port:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex((host, proj_port)) == 0:
                return proj_port
        return None

    return None


async def capture_screenshot(
    url: str,
    is_mobile: bool = False,
    wait_time_seconds: float = 2.0,
    timeout_ms: int = 15000,
) -> bytes:
    """
    Load a URL in headless Chromium and return PNG screenshot bytes.

    Args:
        url: Full URL to capture (e.g. http://localhost:3000/dashboard)
        is_mobile: If True, uses iPhone/mobile viewport dimensions (390x844)
        wait_time_seconds: Extra delay to allow dynamic SPA hydration / CSS animations
        timeout_ms: Maximum navigation timeout
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )

        viewport = (
            {"width": 390, "height": 844} if is_mobile else {"width": 1280, "height": 800}
        )
        user_agent = (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            if is_mobile
            else None
        )

        context_kwargs = {"viewport": viewport}
        if user_agent:
            context_kwargs["user_agent"] = user_agent
            context_kwargs["is_mobile"] = True

        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        try:
            # Navigate with networkidle or load fallback
            try:
                await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            except Exception:
                await page.goto(url, wait_until="load", timeout=timeout_ms)

            # Give a brief moment for React / Vue hydration
            if wait_time_seconds > 0:
                await asyncio.sleep(wait_time_seconds)

            screenshot_bytes = await page.screenshot(type="png", full_page=False)
            return screenshot_bytes
        finally:
            await context.close()
            await browser.close()
