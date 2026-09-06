"""
agy-telegram-bot — Control your Antigravity AI coding agent from Telegram.

Commands:
    /start              Welcome & guide
    /help               Command listing
    /status             Agent, workspace, and model status
    /project <path>     Switch workspace directory
    /reset              Clear conversation memory & restart agent
    /model <name>       Switch AI model (flash / pro)
    /tunnel [port|stop] Expose localhost dev server to the internet
    /preview [path]     Screenshot localhost (desktop/mobile) and send as photo
    /dev [start|stop|restart|logs] Manage background dev server
    /git [diff|push|pull|log] Quick Git operations & status
"""

import asyncio
import html as html_mod
import io
import logging
import platform
import sys
import tempfile
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Optional

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    MenuButtonWebApp,
    ReplyKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import uvicorn
from agent_bridge import AgentBridge
from audit_logger import get_latest_audit_entries, log_interaction
from config import Config
from dev_manager import DevServerManager
from git_manager import get_git_diff, get_git_log, get_git_status, git_pull, git_push
from message_formatter import format_for_telegram, split_message
from plan_manager import PlanManager
from preview_manager import capture_screenshot, detect_open_port, find_project_port
from server import app as fastapi_app, set_bot_context
from tunnel_manager import TunnelManager

# ── Logging ───────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("agy-telegram-bot")


# ── Security decorator ────────────────────────────────────────────────

def authorized_only(func):
    """Only allow the configured AUTHORIZED_USER_ID through."""

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id != Config.AUTHORIZED_USER_ID:
            logger.warning(
                "Unauthorized access attempt from user_id=%s username=%s",
                user.id if user else "?",
                user.username if user else "?",
            )
            if update.effective_message:
                await update.effective_message.reply_text(
                    "⛔ This bot is private. Access denied."
                )
            return
        return await func(update, context)

    return wrapper


# ── Command: /start & /help ───────────────────────────────────────────

@authorized_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome message with quick-start guide."""
    bridge: AgentBridge = context.bot_data["bridge"]
    welcome = (
        "🚀 <b>Antigravity Remote Agent — Online</b>\n\n"
        "I'm your private AI coding partner on your laptop. Talk to me anytime "
        "to brainstorm, build features, inspect bugs, or preview your app.\n\n"
        "<b>📱 Mobile Power-Commands:</b>\n"
        "• 🌐 <code>/tunnel</code> — Expose localhost & get live URL on your phone\n"
        "• 📸 <code>/preview</code> — Screenshot localhost & send photo in chat\n"
        "• ⚡ <code>/dev</code> — Start/stop/restart project dev server\n"
        "• 🐙 <code>/git</code> — Status, diffs, push & pull shortcuts\n"
        "• 🧠 <code>/model</code> — Switch AI model (Flash / Pro)\n"
        "• 📂 <code>/project</code> — Switch active workspace\n"
        "• 🔄 <code>/reset</code> — Clear memory and start fresh\n\n"
        f"📂 <b>Active project:</b>\n<code>{html_mod.escape(bridge.project_dir)}</code>\n"
        f"🧠 <b>Active model:</b> <code>{html_mod.escape(bridge.model_name)}</code>"
    )
    await update.message.reply_text(welcome, parse_mode=ParseMode.HTML)


@authorized_only
async def cmd_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Launch the Telegram Mini App (Mission Control)."""
    tma_tunnel_mgr: TunnelManager = context.bot_data.get("tma_tunnel_mgr")
    bridge: AgentBridge = context.bot_data["bridge"]

    status_msg = await update.message.reply_text("🎛️ Preparing Mission Control Mini App...")

    try:
        if not tma_tunnel_mgr.active_url:
            tma_url, _ = await tma_tunnel_mgr.start_tunnel(9090)
        else:
            tma_url = tma_tunnel_mgr.active_url

        # Set / update the bottom chat menu button
        try:
            await context.bot.set_chat_menu_button(
                chat_id=update.effective_chat.id,
                menu_button=MenuButtonWebApp(
                    text="🎛️ IDE",
                    web_app=WebAppInfo(url=tma_url),
                ),
            )
        except Exception as e:
            logger.debug("Could not set chat menu button: %s", e)

        keyboard = [
            [
                InlineKeyboardButton("🚀 Launch Mission Control", web_app=WebAppInfo(url=tma_url)),
            ],
            [
                InlineKeyboardButton("🌐 Open in Browser", url=tma_url),
                InlineKeyboardButton("📸 Screenshot", callback_data="preview_quick"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await status_msg.edit_text(
            "🎛️ <b>Antigravity Mission Control (Mini App) Ready!</b>\n\n"
            f"• <b>Workspace:</b> <code>{html_mod.escape(bridge.project_dir)}</code>\n"
            f"• <b>Active Model:</b> <code>{html_mod.escape(bridge.model_name)}</code>\n\n"
            "✨ <i>I've also pinned the <b>[🎛️ IDE]</b> button right next to your chat box!</i>\n"
            "<i>Tap below or use the pinned menu button anytime:</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.error("Error launching TMA: %s", e, exc_info=True)
        await status_msg.edit_text(f"❌ Failed to launch Mini App: {e}")


@authorized_only
async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show interactive visual dashboard menu with Mini App launcher."""
    bridge: AgentBridge = context.bot_data["bridge"]
    tunnel_mgr: TunnelManager = context.bot_data["tunnel_mgr"]
    dev_mgr: DevServerManager = context.bot_data["dev_mgr"]
    tma_tunnel_mgr: TunnelManager = context.bot_data.get("tma_tunnel_mgr")

    tunnel_info = tunnel_mgr.get_status()
    dev_info = dev_mgr.get_status()

    tunnel_badge = f"🟢 <a href=\"{tunnel_info['url']}\">Online</a>" if tunnel_info else "⚪ Offline"
    dev_badge = f"🟢 PID {dev_info['pid']}" if dev_info["running"] else "⚪ Stopped"
    mode_str = "🧠 Planning" if bridge.mode == "plan" else "⚡ Direct Act"

    menu_text = (
        "🎛️ <b>Mission Control Dashboard</b>\n\n"
        f"• <b>Workspace:</b> <code>{html_mod.escape(bridge.project_dir)}</code>\n"
        f"• <b>Mode:</b> <code>{mode_str}</code>\n"
        f"• <b>Model:</b> <code>{html_mod.escape(bridge.model_name)}</code>\n"
        f"• <b>Dev Server:</b> {dev_badge}\n"
        f"• <b>Live Tunnel:</b> {tunnel_badge}\n\n"
        "<i>Tap an action below to control your laptop:</i>"
    )

    tma_url = tma_tunnel_mgr.active_url if tma_tunnel_mgr else None

    keyboard = []
    if tma_url:
        keyboard.append([
            InlineKeyboardButton("🚀 Launch Mission Control (Mini App)", web_app=WebAppInfo(url=tma_url)),
        ])
    else:
        keyboard.append([
            InlineKeyboardButton("🚀 Launch Mission Control (Mini App)", callback_data="launch_tma"),
        ])

    keyboard.extend([
        [
            InlineKeyboardButton("🌐 Live Tunnel", callback_data="tunnel_toggle"),
            InlineKeyboardButton("📸 Screenshot", callback_data="preview_quick"),
        ],
        [
            InlineKeyboardButton("🧠 Planning Mode", callback_data="mode_set_plan"),
            InlineKeyboardButton("⚡ Direct Action", callback_data="mode_set_act"),
        ],
        [
            InlineKeyboardButton("⚡ Dev Server", callback_data="dev_status"),
            InlineKeyboardButton("🐙 Git Status", callback_data="git_status"),
        ],
        [
            InlineKeyboardButton("🧠 Switch Model", callback_data="menu_models"),
            InlineKeyboardButton("📊 Full Status", callback_data="menu_status"),
        ],
        [
            InlineKeyboardButton("🔄 Reset Memory", callback_data="menu_reset"),
            InlineKeyboardButton("📖 Help Guide", callback_data="menu_help"),
        ],
    ])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        menu_text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=reply_markup,
    )


@authorized_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show available commands."""
    help_text = (
        "📖 <b>Command Reference</b>\n\n"
        "<b>Workspace & AI</b>\n"
        "• <code>/status</code> — Agent health, uptime, workspace info\n"
        "• <code>/project &lt;path&gt;</code> — Switch to another codebase\n"
        "• <code>/model [flash|pro]</code> — Switch between fast/powerful models\n"
        "• <code>/reset</code> — Clear conversation history\n\n"
        "<b>Live Preview & Web</b>\n"
        "• <code>/tunnel</code> — Start/show Cloudflare tunnel to localhost\n"
        "• <code>/tunnel stop</code> — Stop active tunnel\n"
        "• <code>/preview [/route] [mobile]</code> — Take desktop/mobile screenshot\n\n"
        "<b>Dev Server & Git</b>\n"
        "• <code>/dev [start|stop|restart|logs]</code> — Control dev server\n"
        "• <code>/git [diff|push|pull|log]</code> — Git controls & shortcuts\n\n"
        "💡 <i>Or just text/voice message me naturally to brainstorm or code!</i>"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)


# ── Command: /status ──────────────────────────────────────────────────

@authorized_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current agent, dev server, tunnel, and system status."""
    bridge: AgentBridge = context.bot_data["bridge"]
    tunnel_mgr: TunnelManager = context.bot_data["tunnel_mgr"]
    dev_mgr: DevServerManager = context.bot_data["dev_mgr"]

    info = bridge.status()
    tunnel_info = tunnel_mgr.get_status()
    dev_info = dev_mgr.get_status()
    boot_time = context.bot_data.get("boot_time", "unknown")

    tunnel_str = (
        f"🔗 <a href=\"{tunnel_info['url']}\">{tunnel_info['url']}</a> (port {tunnel_info['port']})"
        if tunnel_info
        else "⚪ Inactive"
    )

    dev_str = (
        f"🟢 Running (`{dev_info['command']}`, PID {dev_info['pid']}, up {dev_info['uptime']})"
        if dev_info["running"]
        else "⚪ Stopped"
    )

    status_text = (
        "📊 <b>System & Agent Status</b>\n\n"
        f"• <b>Agent:</b> {'✅ Ready' if info['running'] else '❌ Offline'}\n"
        f"• <b>Model:</b> <code>{html_mod.escape(info['model'])}</code>\n"
        f"• <b>Project:</b> <code>{html_mod.escape(info['project'])}</code>\n"
        f"• <b>Dev Server:</b> {dev_str}\n"
        f"• <b>Tunnel:</b> {tunnel_str}\n"
        f"• <b>Bot uptime since:</b> {boot_time}\n"
        f"• <b>Platform:</b> {platform.system()} {platform.release()}"
    )

    keyboard = [
        [
            InlineKeyboardButton("🌐 Tunnel", callback_data="tunnel_toggle"),
            InlineKeyboardButton("📸 Screenshot", callback_data="preview_quick"),
        ],
        [
            InlineKeyboardButton("⚡ Dev Server", callback_data="dev_status"),
            InlineKeyboardButton("🐙 Git Status", callback_data="git_status"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        status_text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=reply_markup,
    )


# ── Command: /project ─────────────────────────────────────────────────

PROJECTS_ROOT = Path(Config.PROJECTS_ROOT)


@authorized_only
async def cmd_projects(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show a grid of 1-tap buttons for all projects in the workspace root."""
    bridge: AgentBridge = context.bot_data["bridge"]
    keyboard = []
    row = []

    if PROJECTS_ROOT.is_dir():
        for d in sorted(PROJECTS_ROOT.iterdir()):
            if d.is_dir() and not d.name.startswith(".") and d.name not in ("node_modules", "src"):
                is_active = (str(d).lower() == bridge.project_dir.lower() or str(d / d.name.lower()).lower() == bridge.project_dir.lower())
                icon = "⭐ " if is_active else "📁 "
                cb_data = f"switch_proj_{d.name}"
                row.append(InlineKeyboardButton(f"{icon}{d.name}", callback_data=cb_data))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
        if row:
            keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"📂 <b>Your Projects</b>\n\n"
        f"• <b>Active:</b> <code>{html_mod.escape(bridge.project_dir)}</code>\n\n"
        f"<i>Tap any project below to switch instantly:</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )


@authorized_only
async def cmd_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Switch the agent's working project directory (accepts full path or short name)."""
    bridge: AgentBridge = context.bot_data["bridge"]

    if not context.args:
        await cmd_projects(update, context)
        return

    name_or_path = " ".join(context.args).strip()
    target_path = Path(name_or_path)

    # If it's a short name like "Ahun-Watches", look inside PROJECTS_ROOT
    if not target_path.is_dir() and PROJECTS_ROOT.is_dir():
        cand = PROJECTS_ROOT / name_or_path
        if cand.is_dir():
            target_path = cand
        else:
            # Case-insensitive match
            for d in PROJECTS_ROOT.iterdir():
                if d.is_dir() and d.name.lower() == name_or_path.lower():
                    target_path = d
                    break

    if not target_path.is_dir():
        await update.message.reply_text(
            f"❌ Could not find directory: <code>{html_mod.escape(name_or_path)}</code>\n"
            f"Use <code>/projects</code> to see all available projects.",
            parse_mode=ParseMode.HTML,
        )
        return

    msg = await update.message.reply_text(
        f"🔄 Switching workspace to <code>{html_mod.escape(str(target_path))}</code>...",
        parse_mode=ParseMode.HTML,
    )
    result = await bridge.switch_project(str(target_path))
    await msg.edit_text(result, parse_mode=ParseMode.HTML)


# ── Command: /reset ───────────────────────────────────────────────────

@authorized_only
async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset the agent — clears conversation memory."""
    bridge: AgentBridge = context.bot_data["bridge"]
    msg = await update.message.reply_text("🔄 Resetting agent memory...")
    await bridge.reset()
    await msg.edit_text(
        "✅ <b>Agent reset.</b> Conversation memory cleared.\n"
        f"📂 Workspace: <code>{html_mod.escape(bridge.project_dir)}</code>\n"
        f"🧠 Model: <code>{html_mod.escape(bridge.model_name)}</code>",
        parse_mode=ParseMode.HTML,
    )


# ── Command: /model ───────────────────────────────────────────────────

@authorized_only
async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show or switch the active LLM model."""
    bridge: AgentBridge = context.bot_data["bridge"]

    if not context.args:
        keyboard = [
            [
                InlineKeyboardButton("⚡ Gemini 3.5 Flash Lite (15 RPM • 500/day)", callback_data="set_model_gemini-3.5-flash-lite"),
            ],
            [
                InlineKeyboardButton("🚀 Gemini 2.5 Flash (15 RPM • High Speed)", callback_data="set_model_gemini-2.5-flash"),
            ],
            [
                InlineKeyboardButton("🌟 Gemini Flash Latest (Stable)", callback_data="set_model_gemini-flash-latest"),
            ],
            [
                InlineKeyboardButton("🧠 Gemini 2.5 Pro (Deep Architecture)", callback_data="set_model_gemini-2.5-pro"),
            ],
            [
                InlineKeyboardButton("🔬 Gemini 3.7 Flash (Preview • 5 RPM)", callback_data="set_model_gemini-3.7-flash"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"🧠 <b>Active Model:</b> <code>{html_mod.escape(bridge.model_name)}</code>\n\n"
            f"<b>Recommended:</b> <code>gemini-3.5-flash-lite</code> for daily coding (high rate limits).\n\n"
            f"Select a model below or type: <code>/model &lt;name&gt;</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
        return

    choice = context.args[0].lower()
    model_map = {
        "lite": "gemini-3.5-flash-lite",
        "3.5": "gemini-3.5-flash-lite",
        "flash": "gemini-2.5-flash",
        "2.5": "gemini-2.5-flash",
        "latest": "gemini-flash-latest",
        "pro": "gemini-2.5-pro",
        "3.7": "gemini-3.7-flash",
    }
    target_model = model_map.get(choice, context.args[0])

    msg = await update.message.reply_text(f"🔄 Switching model to <code>{html_mod.escape(target_model)}</code>...", parse_mode=ParseMode.HTML)
    result = await bridge.switch_model(target_model)
    await msg.edit_text(result, parse_mode=ParseMode.HTML)


# ── Command: /tunnel ──────────────────────────────────────────────────

@authorized_only
async def cmd_tunnel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Expose localhost to the internet via Cloudflare quick tunnel."""
    tunnel_mgr: TunnelManager = context.bot_data["tunnel_mgr"]
    bridge: AgentBridge = context.bot_data["bridge"]

    # Check for "stop" argument
    if context.args and context.args[0].lower() == "stop":
        stopped_port = await tunnel_mgr.stop_tunnel()
        if stopped_port:
            await update.message.reply_text(f"⏹️ Tunnel on port <b>{stopped_port}</b> stopped.", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("⚪ No active tunnel was running.")
        return

    # Check for specific port number
    custom_port: Optional[int] = None
    if context.args and context.args[0].isdigit():
        custom_port = int(context.args[0])

    status_msg = await update.message.reply_text("🌐 Starting Cloudflare tunnel to localhost...")

    try:
        dev_mgr: DevServerManager = context.bot_data["dev_mgr"]
        url, port = await tunnel_mgr.start_tunnel(custom_port, project_path=bridge.project_dir, dev_mgr=dev_mgr)
        keyboard = [
            [
                InlineKeyboardButton("📸 Take Screenshot", callback_data="preview_quick"),
                InlineKeyboardButton("🔴 Stop Tunnel", callback_data="tunnel_stop"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await status_msg.edit_text(
            f"🌐 <b>Live Tunnel Online!</b>\n\n"
            f"🔗 <b>Public URL:</b>\n<a href=\"{url}\">{url}</a>\n\n"
            f"• <b>Local port:</b> <code>{port}</code>\n"
            f"• Open the URL above on your phone browser to preview your site live!",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False,
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.error("Tunnel error: %s", e, exc_info=True)
        await status_msg.edit_text(f"❌ Failed to start tunnel: {e}")


# ── Command: /preview ─────────────────────────────────────────────────

@authorized_only
async def cmd_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Capture a screenshot of localhost and send it as a photo.
    Usage:
        /preview
        /preview /dashboard
        /preview mobile
        /preview /settings mobile
    """
    tunnel_mgr: TunnelManager = context.bot_data["tunnel_mgr"]
    bridge: AgentBridge = context.bot_data["bridge"]

    # Detect port with project awareness (prioritizes project's config like vite.config, .env, or package.json)
    port = tunnel_mgr.active_port or detect_open_port(project_path=bridge.project_dir) or 3000
    route = ""
    is_mobile = False

    if context.args:
        for arg in context.args:
            if arg.lower() in ("mobile", "phone", "m"):
                is_mobile = True
            elif arg.isdigit():
                port = int(arg)
            elif arg.startswith("/"):
                route = arg

    target_url = f"http://localhost:{port}{route}"
    status_msg = await update.message.reply_text(
        f"📸 Capturing {'mobile' if is_mobile else 'desktop'} screenshot of <code>{html_mod.escape(target_url)}</code>...",
        parse_mode=ParseMode.HTML,
    )

    try:
        screenshot_bytes = await capture_screenshot(target_url, is_mobile=is_mobile)

        caption = (
            f"📸 <b>Preview:</b> <code>{html_mod.escape(target_url)}</code>\n"
            f"📱 Mode: {'Mobile (390×844)' if is_mobile else 'Desktop (1280×800)'}"
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "📱 Mobile View" if not is_mobile else "💻 Desktop View",
                    callback_data=f"preview_toggle_{port}_{route}_{'desktop' if is_mobile else 'mobile'}",
                ),
                InlineKeyboardButton("🔄 Refresh", callback_data=f"preview_refresh_{port}_{route}_{'mobile' if is_mobile else 'desktop'}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=io.BytesIO(screenshot_bytes),
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
        await status_msg.delete()
    except Exception as e:
        logger.error("Preview error: %s", e, exc_info=True)
        await status_msg.edit_text(
            f"❌ Could not capture preview of <code>{html_mod.escape(target_url)}</code>\n\n"
            f"<b>Error:</b> {html_mod.escape(str(e))}\n\n"
            f"Make sure your dev server is running on port {port} (try <code>/dev start</code>).",
            parse_mode=ParseMode.HTML,
        )


# ── Command: /dev ─────────────────────────────────────────────────────

@authorized_only
async def cmd_dev(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Manage the project development server.
    Usage:
        /dev                Show status & quick actions
        /dev start          Start dev server
        /dev stop           Stop dev server
        /dev restart        Restart dev server
        /dev logs           View recent logs
    """
    dev_mgr: DevServerManager = context.bot_data["dev_mgr"]
    bridge: AgentBridge = context.bot_data["bridge"]

    subcmd = context.args[0].lower() if context.args else "status"

    if subcmd == "start":
        custom_cmd = " ".join(context.args[1:]) if len(context.args) > 1 else None
        msg = await update.message.reply_text("⚡ Starting dev server...")
        success, text = await dev_mgr.start(bridge.project_dir, custom_cmd)
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)

    elif subcmd == "stop":
        success, text = await dev_mgr.stop()
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    elif subcmd == "restart":
        msg = await update.message.reply_text("🔄 Restarting dev server...")
        success, text = await dev_mgr.restart(bridge.project_dir)
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)

    elif subcmd == "logs":
        logs = dev_mgr.get_logs(30)
        if not logs:
            await update.message.reply_text("📋 No dev server logs recorded yet.")
            return
        log_text = "\n".join(logs)
        if len(log_text) > 3800:
            log_text = log_text[-3800:]
        await update.message.reply_text(
            f"📋 <b>Dev Server Logs (Last {len(logs)} lines):</b>\n\n<pre>{html_mod.escape(log_text)}</pre>",
            parse_mode=ParseMode.HTML,
        )

    else:
        # Default / status view
        status = dev_mgr.get_status()
        running = status["running"]

        status_text = (
            f"⚡ <b>Dev Server Status</b>\n\n"
            f"• <b>Status:</b> {'🟢 Running' if running else '⚪ Stopped'}\n"
            f"• <b>Command:</b> <code>{html_mod.escape(str(status['command']))}</code>\n"
            f"• <b>PID:</b> <code>{status['pid'] or 'N/A'}</code>\n"
            f"• <b>Uptime:</b> {status['uptime']}\n"
            f"• <b>Workspace:</b> <code>{html_mod.escape(str(bridge.project_dir))}</code>"
        )

        keyboard = [
            [
                InlineKeyboardButton("▶️ Start", callback_data="dev_action_start") if not running else InlineKeyboardButton("⏹️ Stop", callback_data="dev_action_stop"),
                InlineKeyboardButton("🔄 Restart", callback_data="dev_action_restart"),
            ],
            [
                InlineKeyboardButton("📋 View Logs", callback_data="dev_action_logs"),
                InlineKeyboardButton("🌐 Tunnel", callback_data="tunnel_toggle"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(status_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)


# ── Command: /git ─────────────────────────────────────────────────────

@authorized_only
async def cmd_git(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Git shortcuts:
        /git                Status summary & buttons
        /git diff           Diff summary
        /git push           Push to remote
        /git pull           Pull latest changes
        /git log            Recent commits
    """
    bridge: AgentBridge = context.bot_data["bridge"]
    subcmd = context.args[0].lower() if context.args else "status"

    if subcmd == "diff":
        msg = await update.message.reply_text("🔍 Checking git diff...")
        diff = await get_git_diff(bridge.project_dir)
        await msg.edit_text(
            f"📋 <b>Git Diff Summary:</b>\n\n<pre>{html_mod.escape(diff[:3800])}</pre>",
            parse_mode=ParseMode.HTML,
        )

    elif subcmd == "push":
        msg = await update.message.reply_text("📤 Running git push...")
        ok, out = await git_push(bridge.project_dir)
        icon = "✅" if ok else "❌"
        await msg.edit_text(
            f"{icon} <b>Git Push Result:</b>\n\n<pre>{html_mod.escape(out[:3800])}</pre>",
            parse_mode=ParseMode.HTML,
        )

    elif subcmd == "pull":
        msg = await update.message.reply_text("📥 Running git pull --rebase...")
        ok, out = await git_pull(bridge.project_dir)
        icon = "✅" if ok else "❌"
        await msg.edit_text(
            f"{icon} <b>Git Pull Result:</b>\n\n<pre>{html_mod.escape(out[:3800])}</pre>",
            parse_mode=ParseMode.HTML,
        )

    elif subcmd == "log":
        log_out = await get_git_log(bridge.project_dir, count=7)
        await update.message.reply_text(
            f"📜 <b>Recent Commits:</b>\n\n<pre>{html_mod.escape(log_out)}</pre>",
            parse_mode=ParseMode.HTML,
        )

    else:
        # Default status view
        status = await get_git_status(bridge.project_dir)
        if not status.get("is_git"):
            await update.message.reply_text("❌ Current directory is not a Git repository.")
            return

        branch = status["branch"]
        modified = status["modified"]
        untracked = status["untracked"]
        recent = status["recent_log"]

        mod_str = f"• <b>Changed ({len(modified)}):</b>\n  <code>" + "\n  ".join(html_mod.escape(m) for m in modified[:8]) + "</code>\n" if modified else "• <b>Working tree clean</b>\n"
        if len(modified) > 8:
            mod_str += f"  <i>...and {len(modified) - 8} more</i>\n"

        untracked_str = f"• <b>Untracked ({len(untracked)}):</b>\n  <code>" + "\n  ".join(html_mod.escape(u) for u in untracked[:5]) + "</code>\n" if untracked else ""
        recent_str = "\n".join(f"  • <code>{html_mod.escape(r)}</code>" for r in recent) if recent else "  (None)"

        status_text = (
            f"🐙 <b>Git Status</b> (<code>{html_mod.escape(branch)}</code>)\n\n"
            f"{mod_str}"
            f"{untracked_str}\n"
            f"📜 <b>Recent Commits:</b>\n{recent_str}"
        )

        keyboard = [
            [
                InlineKeyboardButton("📋 View Diff", callback_data="git_action_diff"),
                InlineKeyboardButton("📜 Recent Log", callback_data="git_action_log"),
            ],
            [
                InlineKeyboardButton("📤 Push", callback_data="git_action_push"),
                InlineKeyboardButton("📥 Pull", callback_data="git_action_pull"),
                InlineKeyboardButton("🔄 Refresh", callback_data="git_status"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            status_text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )


# ── Message Handler (Agent Brainstorm & Execution Loop) ───────────────

@authorized_only
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forward natural language message to the Antigravity agent."""
    bridge: AgentBridge = context.bot_data["bridge"]
    user_text = update.message.text

    if not user_text or not user_text.strip():
        return

    # Send "thinking" indicator
    thinking_msg = await update.message.reply_text("⏳ Thinking...")

    # Keep showing typing action while agent reasons & writes
    async def typing_loop():
        try:
            while True:
                await context.bot.send_chat_action(
                    chat_id=update.effective_chat.id,
                    action=ChatAction.TYPING,
                )
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    typing_task = asyncio.create_task(typing_loop())

    try:
        # Get response from the Antigravity agent
        raw_response = await bridge.chat(user_text)

        # 📋 Automatically save to laptop Markdown audit trail
        try:
            log_interaction(
                prompt=user_text,
                response=raw_response,
                project_dir=bridge.project_dir,
                model_name=bridge.model_name,
                user_id=update.effective_user.id,
            )
        except Exception as e:
            logger.debug("Audit logging failed: %s", e)

        # Format for Telegram
        formatted = format_for_telegram(raw_response)
        chunks = split_message(formatted)

        # Check if response suggests action buttons (diff, test, dev, tunnel)
        quick_keyboard = [
            [
                InlineKeyboardButton("📸 Screenshot", callback_data="preview_quick"),
                InlineKeyboardButton("🌐 Tunnel", callback_data="tunnel_toggle"),
                InlineKeyboardButton("🐙 Git Diff", callback_data="git_action_diff"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(quick_keyboard)

        # Edit the "thinking" message with the first chunk
        try:
            await thinking_msg.edit_text(
                chunks[0],
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=reply_markup if len(chunks) == 1 else None,
            )
        except Exception:
            await thinking_msg.edit_text(chunks[0])

        # Send remaining chunks as new messages
        for i, chunk in enumerate(chunks[1:]):
            is_last = (i == len(chunks[1:]) - 1)
            try:
                await update.message.reply_text(
                    chunk,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    reply_markup=reply_markup if is_last else None,
                )
            except Exception:
                await update.message.reply_text(chunk)

    except Exception as e:
        logger.error("Error handling message: %s", e, exc_info=True)
        await thinking_msg.edit_text(f"❌ Error: {e}")

    finally:
        typing_task.cancel()


# ── Voice Note Handler ────────────────────────────────────────────────

@authorized_only
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice notes, transcribe, and forward to the agent."""
    if not Config.VOICE_ENABLED:
        await update.message.reply_text(
            "🎙️ Voice notes are currently disabled.\n"
            "Set <code>VOICE_ENABLED=true</code> in your .env file to enable.",
            parse_mode=ParseMode.HTML,
        )
        return

    processing_msg = await update.message.reply_text("🎙️ Processing voice note...")

    try:
        voice = update.message.voice or update.message.audio
        if not voice:
            await processing_msg.edit_text("❌ Could not read voice message.")
            return

        voice_file = await context.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
            await voice_file.download_to_drive(tmp_path)

        try:
            from google import genai
            client = genai.Client(api_key=Config.GEMINI_API_KEY) if Config.GEMINI_API_KEY else genai.Client()
            uploaded = client.files.upload(file=tmp_path)
            result = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[
                    uploaded,
                    "Transcribe this audio message exactly as spoken. Return ONLY the transcription text, nothing else.",
                ],
            )
            transcription = result.text.strip()
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        if not transcription:
            await processing_msg.edit_text("❌ Could not transcribe audio.")
            return

        await processing_msg.edit_text(
            f"🎙️ <i>Transcribed:</i> {html_mod.escape(transcription)}",
            parse_mode=ParseMode.HTML,
        )

        update.message.text = transcription
        await handle_message.__wrapped__(update, context)

    except Exception as e:
        logger.error("Voice note error: %s", e, exc_info=True)
        await processing_msg.edit_text(f"❌ Voice note error: {e}")


# ── Callback Query Handler ────────────────────────────────────────────

@authorized_only
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle interactive button presses."""
    query = update.callback_query
    await query.answer()

    bridge: AgentBridge = context.bot_data["bridge"]
    tunnel_mgr: TunnelManager = context.bot_data["tunnel_mgr"]
    dev_mgr: DevServerManager = context.bot_data["dev_mgr"]
    data = query.data

    if data == "tunnel_toggle":
        if tunnel_mgr.active_url:
            await tunnel_mgr.stop_tunnel()
            await query.message.reply_text("⏹️ Tunnel stopped.")
        else:
            try:
                url, port = await tunnel_mgr.start_tunnel(project_path=bridge.project_dir, dev_mgr=dev_mgr)
                await query.message.reply_text(
                    f"🌐 <b>Tunnel Online:</b>\n<a href=\"{url}\">{url}</a> (port {port})",
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                await query.message.reply_text(f"❌ Tunnel error: {e}")

    elif data == "tunnel_stop":
        await tunnel_mgr.stop_tunnel()
        await query.message.reply_text("⏹️ Tunnel stopped.")

    elif data == "preview_quick":
        port = tunnel_mgr.active_port or (dev_mgr.get_port() if dev_mgr.is_running() else None) or find_project_port(bridge.project_dir) or 8081
        target_url = f"http://localhost:{port}"
        try:
            screenshot = await capture_screenshot(target_url, is_mobile=True)
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=io.BytesIO(screenshot),
                caption=f"📸 <b>Preview (Mobile):</b> <code>{target_url}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Preview error: {e}")

    elif data.startswith("preview_toggle_") or data.startswith("preview_refresh_"):
        parts = data.split("_")
        action = parts[1]
        port = int(parts[2])
        route = parts[3]
        mode = parts[4]
        is_mobile = (mode == "mobile")
        target_url = f"http://localhost:{port}{route}"

        try:
            screenshot = await capture_screenshot(target_url, is_mobile=is_mobile)
            caption = (
                f"📸 <b>Preview:</b> <code>{html_mod.escape(target_url)}</code>\n"
                f"📱 Mode: {'Mobile (390×844)' if is_mobile else 'Desktop (1280×800)'}"
            )
            keyboard = [
                [
                    InlineKeyboardButton(
                        "📱 Mobile View" if not is_mobile else "💻 Desktop View",
                        callback_data=f"preview_toggle_{port}_{route}_{'desktop' if is_mobile else 'mobile'}",
                    ),
                    InlineKeyboardButton("🔄 Refresh", callback_data=f"preview_refresh_{port}_{route}_{'mobile' if is_mobile else 'desktop'}"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=io.BytesIO(screenshot),
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Preview error: {e}")

    elif data.startswith("switch_proj_"):
        proj_name = data.replace("switch_proj_", "")
        target_path = PROJECTS_ROOT / proj_name
        if target_path.is_dir():
            msg = await query.message.reply_text(
                f"🔄 Switching workspace to <code>{html_mod.escape(str(target_path))}</code>...",
                parse_mode=ParseMode.HTML,
            )
            result = await bridge.switch_project(str(target_path))
            await msg.edit_text(result, parse_mode=ParseMode.HTML)
        else:
            await query.message.reply_text(f"❌ Project not found: {proj_name}")

    elif data.startswith("set_model_"):
        model_name = data.replace("set_model_", "")
        res = await bridge.switch_model(model_name)
        await query.message.reply_text(res, parse_mode=ParseMode.HTML)

    elif data == "dev_status":
        status = dev_mgr.get_status()
        is_run = status["running"]
        keyboard = [
            [
                InlineKeyboardButton("▶️ Start Server", callback_data="dev_action_start")
                if not is_run
                else InlineKeyboardButton("⏹️ Stop Server", callback_data="dev_action_stop"),
                InlineKeyboardButton("🔄 Restart", callback_data="dev_action_restart"),
            ],
            [
                InlineKeyboardButton("📋 View Logs", callback_data="dev_action_logs"),
                InlineKeyboardButton("🌐 Tunnel", callback_data="tunnel_toggle"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            f"⚡ <b>Dev Server Control:</b>\n\n"
            f"• <b>Status:</b> {'🟢 Running' if is_run else '⚪ Stopped'}\n"
            f"• <b>Workspace:</b> <code>{html_mod.escape(str(bridge.project_dir))}</code>\n"
            f"• <b>Command:</b> <code>{status['command']}</code> (PID: {status['pid']})\n\n"
            f"Tap <b>▶️ Start Server</b> below to launch:",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )

    elif data == "dev_action_start":
        ok, text = await dev_mgr.start(bridge.project_dir)
        keyboard = [
            [
                InlineKeyboardButton("⏹️ Stop Server", callback_data="dev_action_stop"),
                InlineKeyboardButton("🔄 Restart", callback_data="dev_action_restart"),
            ],
            [
                InlineKeyboardButton("🌐 Live Tunnel", callback_data="tunnel_toggle"),
                InlineKeyboardButton("📸 Screenshot", callback_data="preview_quick"),
            ],
        ]
        await query.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard) if ok else None,
        )

    elif data == "dev_action_stop":
        _, text = await dev_mgr.stop()
        keyboard = [
            [
                InlineKeyboardButton("▶️ Start Server", callback_data="dev_action_start"),
                InlineKeyboardButton("🔄 Restart", callback_data="dev_action_restart"),
            ]
        ]
        await query.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data == "dev_action_restart":
        ok, text = await dev_mgr.restart(bridge.project_dir)
        keyboard = [
            [
                InlineKeyboardButton("🌐 Live Tunnel", callback_data="tunnel_toggle"),
                InlineKeyboardButton("📸 Screenshot", callback_data="preview_quick"),
            ]
        ]
        await query.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard) if ok else None,
        )

    elif data == "dev_action_logs":
        logs = dev_mgr.get_logs(30)
        log_text = "\n".join(logs) if logs else "No logs recorded."
        await query.message.reply_text(
            f"📋 <b>Dev Server Logs:</b>\n\n<pre>{html_mod.escape(log_text[-3800:])}</pre>",
            parse_mode=ParseMode.HTML,
        )

    elif data == "git_status":
        status = await get_git_status(bridge.project_dir)
        branch = status.get("branch", "unknown")
        mod_count = len(status.get("modified", []))
        await query.message.reply_text(
            f"🐙 <b>Git:</b> Branch <code>{branch}</code> | {mod_count} changed files",
            parse_mode=ParseMode.HTML,
        )

    elif data == "git_action_diff":
        diff = await get_git_diff(bridge.project_dir)
        await query.message.reply_text(
            f"📋 <b>Git Diff Summary:</b>\n\n<pre>{html_mod.escape(diff[:3800])}</pre>",
            parse_mode=ParseMode.HTML,
        )

    elif data == "git_action_push":
        ok, out = await git_push(bridge.project_dir)
        icon = "✅" if ok else "❌"
        await query.message.reply_text(
            f"{icon} <b>Push result:</b>\n<pre>{html_mod.escape(out[:3800])}</pre>",
            parse_mode=ParseMode.HTML,
        )

    elif data == "git_action_pull":
        ok, out = await git_pull(bridge.project_dir)
        icon = "✅" if ok else "❌"
        await query.message.reply_text(
            f"{icon} <b>Pull result:</b>\n<pre>{html_mod.escape(out[:3800])}</pre>",
            parse_mode=ParseMode.HTML,
        )

    elif data == "menu_models":
        keyboard = [
            [
                InlineKeyboardButton("⚡ Gemini 3.5 Flash Lite (15 RPM • 500/day)", callback_data="set_model_gemini-3.5-flash-lite"),
            ],
            [
                InlineKeyboardButton("🚀 Gemini 2.5 Flash (15 RPM • High Speed)", callback_data="set_model_gemini-2.5-flash"),
            ],
            [
                InlineKeyboardButton("🌟 Gemini Flash Latest (Stable)", callback_data="set_model_gemini-flash-latest"),
            ],
            [
                InlineKeyboardButton("🧠 Gemini 2.5 Pro (Deep Architecture)", callback_data="set_model_gemini-2.5-pro"),
            ],
            [
                InlineKeyboardButton("🔬 Gemini 3.7 Flash (Preview • 5 RPM)", callback_data="set_model_gemini-3.7-flash"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            f"🧠 <b>Active Model:</b> <code>{html_mod.escape(bridge.model_name)}</code>\n\n"
            f"Select a model below:",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )

    elif data == "launch_tma":
        tma_tunnel_mgr = context.bot_data.get("tma_tunnel_mgr")
        bridge = context.bot_data.get("bridge")
        msg = await query.message.reply_text("🎛️ Connecting Mission Control Mini App...")
        try:
            if not tma_tunnel_mgr.active_url:
                tma_url, _ = await tma_tunnel_mgr.start_tunnel(9090)
            else:
                tma_url = tma_tunnel_mgr.active_url

            keyboard = [
                [
                    InlineKeyboardButton("🚀 Launch Mission Control", web_app=WebAppInfo(url=tma_url)),
                ],
                [
                    InlineKeyboardButton("🌐 Open in Browser", url=tma_url),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await msg.edit_text(
                "🎛️ <b>Mission Control (Telegram Mini App) Ready!</b>\n\n"
                "Tap below to open your pocket IDE dashboard:",
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
        except Exception as e:
            await msg.edit_text(f"❌ Error launching TMA: {e}")

    elif data == "mode_set_plan":
        res = bridge.set_mode("plan")
        await query.message.reply_text(res, parse_mode=ParseMode.HTML)

    elif data == "mode_set_act":
        res = bridge.set_mode("act")
        await query.message.reply_text(res, parse_mode=ParseMode.HTML)

    elif data == "plan_approve":
        # Switch to act mode and execute the active plan
        bridge.set_mode("act")
        exec_msg = await query.message.reply_text("⚡ <b>Plan Approved!</b> Executing changes across your codebase now...", parse_mode=ParseMode.HTML)

        try:
            exec_prompt = (
                "The user has officially APPROVED the Implementation Plan.\n"
                "Proceed to execute all proposed changes step-by-step:\n"
                "1. Modify/create the required source code files.\n"
                "2. Verify code syntax and logic.\n"
                "3. Provide a clear completion summary of files modified and verification results."
            )
            raw_response = await bridge.chat(exec_prompt)

            # Log execution to audit trail
            try:
                log_interaction(
                    prompt="[ACTION: Approved Implementation Plan]",
                    response=raw_response,
                    project_dir=bridge.project_dir,
                    model_name=bridge.model_name,
                    user_id=query.from_user.id,
                )
            except Exception:
                pass

            formatted = format_for_telegram(raw_response)
            chunks = split_message(formatted)

            action_keyboard = [
                [
                    InlineKeyboardButton("📸 Screenshot", callback_data="preview_quick"),
                    InlineKeyboardButton("🐙 Git Diff", callback_data="git_action_diff"),
                    InlineKeyboardButton("🌐 Tunnel", callback_data="tunnel_toggle"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(action_keyboard)

            await exec_msg.edit_text(
                "✅ <b>Execution Complete!</b>\n\n" + chunks[0],
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=reply_markup if len(chunks) == 1 else None,
            )

            for i, chunk in enumerate(chunks[1:]):
                is_last = (i == len(chunks[1:]) - 1)
                try:
                    await query.message.reply_text(
                        chunk,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                        reply_markup=reply_markup if is_last else None,
                    )
                except Exception:
                    await query.message.reply_text(chunk)

        except Exception as e:
            logger.error("Error executing approved plan: %s", e, exc_info=True)
            await exec_msg.edit_text(f"❌ Execution error: {e}")

    elif data == "menu_status":
        info = bridge.status()
        tunnel_info = tunnel_mgr.get_status()
        dev_info = dev_mgr.get_status()
        boot_time = context.bot_data.get("boot_time", "unknown")
        tunnel_str = f"🔗 <a href=\"{tunnel_info['url']}\">{tunnel_info['url']}</a> (port {tunnel_info['port']})" if tunnel_info else "⚪ Inactive"
        dev_str = f"🟢 Running (PID {dev_info['pid']}, up {dev_info['uptime']})" if dev_info["running"] else "⚪ Stopped"
        mode_str = "🧠 Planning / Brainstorming" if bridge.mode == "plan" else "⚡ Direct Action"

        status_text = (
            "📊 <b>System & Agent Status</b>\n\n"
            f"• <b>Agent:</b> {'✅ Ready' if info['running'] else '❌ Offline'}\n"
            f"• <b>Mode:</b> <code>{mode_str}</code>\n"
            f"• <b>Model:</b> <code>{html_mod.escape(info['model'])}</code>\n"
            f"• <b>Project:</b> <code>{html_mod.escape(info['project'])}</code>\n"
            f"• <b>Dev Server:</b> {dev_str}\n"
            f"• <b>Tunnel:</b> {tunnel_str}\n"
            f"• <b>Bot uptime since:</b> {boot_time}\n"
            f"• <b>Platform:</b> {platform.system()} {platform.release()}"
        )
        await query.message.reply_text(status_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    elif data == "menu_reset":
        msg = await query.message.reply_text("🔄 Resetting agent memory...")
        await bridge.reset()
        await msg.edit_text(
            "✅ <b>Agent reset.</b> Memory cleared.\n"
            f"📂 Workspace: <code>{html_mod.escape(bridge.project_dir)}</code>",
            parse_mode=ParseMode.HTML,
        )

# ── Command: /plan & /mode ───────────────────────────────────────────

@authorized_only
async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show or switch between Planning and Direct Execution modes."""
    bridge: AgentBridge = context.bot_data["bridge"]
    curr_mode = bridge.mode

    keyboard = [
        [
            InlineKeyboardButton("🧠 Planning & Brainstorm Mode" + (" (Active)" if curr_mode == "plan" else ""), callback_data="mode_set_plan"),
        ],
        [
            InlineKeyboardButton("⚡ Direct Action Mode" + (" (Active)" if curr_mode == "act" else ""), callback_data="mode_set_act"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"🎯 <b>Agent Working Mode</b>\n\n"
        f"• <b>Current:</b> {'🧠 Planning / Brainstorming' if curr_mode == 'plan' else '⚡ Direct Execution'}\n\n"
        f"• <b>🧠 Planning Mode:</b> Brainstorm ideas, explore architecture, and draft Implementation Plans <i>without modifying code</i> until approved.\n"
        f"• <b>⚡ Direct Mode:</b> Agent edits files and runs commands immediately.",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )


@authorized_only
async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Activate Planning/Brainstorming mode. If a topic is provided, research & formulate an Implementation Plan.
    """
    bridge: AgentBridge = context.bot_data["bridge"]
    plan_mgr: PlanManager = context.bot_data["plan_mgr"]

    # Switch to plan mode
    bridge.set_mode("plan")

    if not context.args:
        keyboard = [
            [
                InlineKeyboardButton("⚡ Switch to Direct Action", callback_data="mode_set_act"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🧠 <b>Planning & Brainstorming Mode Active!</b>\n\n"
            "The agent is now in <b>safe mode</b> — it will research files and brainstorm architectures with you <b>without modifying code</b> until you approve.\n\n"
            "💡 <b>To create an Implementation Plan:</b>\n"
            "Send: <code>/plan &lt;your feature or bug to solve&gt;</code>\n"
            "Or simply text me your ideas to brainstorm!",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
        return

    topic = " ".join(context.args).strip()
    status_msg = await update.message.reply_text(f"🧠 Formulating Implementation Plan for: <b>{html_mod.escape(topic)}</b>...", parse_mode=ParseMode.HTML)

    prompt = (
        f"Please create a comprehensive Implementation Plan for: '{topic}'.\n"
        f"1. Explore the codebase using view_file or search to understand current architecture.\n"
        f"2. Structure your plan with:\n"
        f"   - 🎯 Objective & Architecture\n"
        f"   - 📂 Files to Create / Modify\n"
        f"   - ⚠️ Potential Risks & Trade-offs\n"
        f"   - 🧪 Verification & Testing Plan\n"
        f"Do NOT execute edits yet. Formulate the plan for user review."
    )

    try:
        raw_plan = await bridge.chat(prompt)

        # Save to project .agent/plans/implementation_plan.md
        saved_path = plan_mgr.save_plan(title=topic, content=raw_plan)

        formatted = format_for_telegram(raw_plan)
        chunks = split_message(formatted)

        plan_keyboard = [
            [
                InlineKeyboardButton("✅ Approve & Execute Plan", callback_data="plan_approve"),
            ],
            [
                InlineKeyboardButton("⚡ Direct Mode", callback_data="mode_set_act"),
                InlineKeyboardButton("📸 Screenshot", callback_data="preview_quick"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(plan_keyboard)

        # Send first chunk
        try:
            await status_msg.edit_text(
                f"📋 <b>Implementation Plan Created:</b>\n<i>Saved to: {html_mod.escape(str(saved_path))}</i>\n\n" + chunks[0],
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=reply_markup if len(chunks) == 1 else None,
            )
        except Exception:
            await status_msg.edit_text(chunks[0])

        for i, chunk in enumerate(chunks[1:]):
            is_last = (i == len(chunks[1:]) - 1)
            try:
                await update.message.reply_text(
                    chunk,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    reply_markup=reply_markup if is_last else None,
                )
            except Exception:
                await update.message.reply_text(chunk)

    except Exception as e:
        logger.error("Plan generation error: %s", e, exc_info=True)
        await status_msg.edit_text(f"❌ Error creating plan: {e}")


@authorized_only
async def cmd_audit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the latest mobile audit trail on your laptop."""
    content = get_latest_audit_entries()
    if len(content) > 3500:
        content = content[-3500:]

    await update.message.reply_text(
        f"📋 <b>Laptop Audit Trail (Recent Activity):</b>\n\n<pre>{html_mod.escape(content)}</pre>",
        parse_mode=ParseMode.HTML,
    )


# ── Application Lifecycle ─────────────────────────────────────────────

async def start_fastapi_server() -> None:
    """Run the FastAPI backend for the Telegram Mini App on port 9090."""
    config = uvicorn.Config(
        app=fastapi_app,
        host="127.0.0.1",
        port=9090,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    logger.info("🌐 FastAPI Mission Control backend listening on http://127.0.0.1:9090")
    await server.serve()


async def post_init(application: Application) -> None:
    """Initialize agent, tunnel manager, dev server manager, TMA server, and register native bot commands."""
    # Register native Telegram command menu (the "/" button next to the input box on mobile)
    commands = [
        BotCommand("app", "🎛️ Launch Mission Control Mini App"),
        BotCommand("menu", "🎛️ Open interactive visual dashboard"),
        BotCommand("plan", "🧠 Brainstorm & create Implementation Plan"),
        BotCommand("mode", "🎯 Switch Planning / Direct Action mode"),
        BotCommand("projects", "📂 Quick switch between your projects"),
        BotCommand("tunnel", "🌐 Expose localhost & get live URL"),
        BotCommand("preview", "📸 Screenshot localhost (desktop/mobile)"),
        BotCommand("dev", "⚡ Start/stop/restart dev server & view logs"),
        BotCommand("git", "🐙 Git status, diff, push, pull, log"),
        BotCommand("model", "🧠 Switch AI model (Flash / Pro)"),
        BotCommand("audit", "📋 View laptop audit trail & logs"),
        BotCommand("project", "📂 Switch active workspace directory"),
        BotCommand("status", "📊 Full system & agent health status"),
        BotCommand("reset", "🔄 Clear conversation memory & restart"),
        BotCommand("help", "📖 View command reference & guide"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("✅ Native Telegram bot commands registered successfully")
    except Exception as e:
        logger.warning("Could not set bot commands: %s", e)

    bridge = AgentBridge()
    await bridge.start()

    tunnel_mgr = TunnelManager()
    tma_tunnel_mgr = TunnelManager()
    dev_mgr = DevServerManager()
    plan_mgr = PlanManager(bridge.project_dir)

    # Inject bot context into FastAPI app
    set_bot_context(bridge, tunnel_mgr, dev_mgr, plan_mgr)

    # Start FastAPI server in background
    asyncio.create_task(start_fastapi_server())

    application.bot_data["bridge"] = bridge
    application.bot_data["tunnel_mgr"] = tunnel_mgr
    application.bot_data["tma_tunnel_mgr"] = tma_tunnel_mgr
    application.bot_data["dev_mgr"] = dev_mgr
    application.bot_data["plan_mgr"] = plan_mgr
    application.bot_data["boot_time"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    # Auto-start TMA tunnel on boot with continuous self-healing watchdog
    async def init_and_watch_tma():
        import httpx
        while True:
            try:
                # Check if tunnel is dead or not initialized
                tma_url = tma_tunnel_mgr.active_url
                is_alive = False
                if tma_url and tma_tunnel_mgr.process and tma_tunnel_mgr.process.returncode is None:
                    try:
                        async with httpx.AsyncClient(timeout=6.0) as client:
                            resp = await client.get(f"{tma_url}/api/status")
                            if resp.status_code == 200:
                                is_alive = True
                    except Exception:
                        is_alive = False

                if not is_alive:
                    logger.warning("Cloudflare tunnel dropped or inactive. Re-establishing live tunnel...")
                    new_url, _ = await tma_tunnel_mgr.start_tunnel(9090)
                    await application.bot.set_chat_menu_button(
                        menu_button=MenuButtonWebApp(
                            text="🎛️ IDE",
                            web_app=WebAppInfo(url=new_url),
                        )
                    )
                    logger.info("✅ Reconnected TMA Menu Button [🎛️ IDE]: %s", new_url)
            except Exception as err:
                logger.warning("Tunnel watchdog error: %s", err)

            await asyncio.sleep(45)  # Health-check every 45s

    asyncio.create_task(init_and_watch_tma())

    logger.info("🤖 Bot initialized with full tool suite (Agent + TMA + Tunnel + Dev + Git + Preview + Plan)")


async def post_shutdown(application: Application) -> None:
    """Clean up agent, tunnels, and dev servers on exit."""
    bridge: AgentBridge | None = application.bot_data.get("bridge")
    if bridge:
        await bridge.stop()

    tunnel_mgr: TunnelManager | None = application.bot_data.get("tunnel_mgr")
    if tunnel_mgr:
        await tunnel_mgr.stop_tunnel()

    tma_tunnel_mgr: TunnelManager | None = application.bot_data.get("tma_tunnel_mgr")
    if tma_tunnel_mgr:
        await tma_tunnel_mgr.stop_tunnel()

    dev_mgr: DevServerManager | None = application.bot_data.get("dev_mgr")
    if dev_mgr:
        await dev_mgr.stop()

    logger.info("👋 Bot and all managers shut down cleanly")


# ── Main ──────────────────────────────────────────────────────────────

def main() -> None:
    """Entry point — validate config and start polling."""
    Config.validate()

    logger.info("Starting agy-telegram-bot...")
    logger.info("  Project: %s", Config.DEFAULT_PROJECT_DIR)
    logger.info("  Auth user: %s", Config.AUTHORIZED_USER_ID)
    logger.info("  Voice: %s", "enabled" if Config.VOICE_ENABLED else "disabled")

    app = (
        Application.builder()
        .token(Config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Register command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("app", cmd_app))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("mode", cmd_mode))
    app.add_handler(CommandHandler("projects", cmd_projects))
    app.add_handler(CommandHandler("project", cmd_project))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("audit", cmd_audit))
    app.add_handler(CommandHandler("tunnel", cmd_tunnel))
    app.add_handler(CommandHandler("preview", cmd_preview))
    app.add_handler(CommandHandler("dev", cmd_dev))
    app.add_handler(CommandHandler("git", cmd_git))

    # Text messages → Agent
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Voice notes → Transcribe → Agent
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Start polling
    logger.info("🟢 Bot is online with all 5 commands — send a message on Telegram!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
