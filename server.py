"""
server.py — FastAPI backend server for the Antigravity Mission Control Telegram Mini App.
Runs locally on port 9090 and provides real-time REST API for state, previews, and controls.
"""

import asyncio
import io
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import Config

logger = logging.getLogger("mission-control-server")

WEB_DIR = Path(__file__).parent / "web"
PROJECTS_ROOT = Path(Config.PROJECTS_ROOT)

app = FastAPI(title="Antigravity Mission Control")

# Enable CORS for Telegram WebApp
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Reference to bot context managers (injected on startup)
bot_context = {
    "bridge": None,
    "tunnel_mgr": None,
    "dev_mgr": None,
    "plan_mgr": None,
}


def set_bot_context(bridge, tunnel_mgr, dev_mgr, plan_mgr):
    """Inject active bot managers into the web server context."""
    bot_context["bridge"] = bridge
    bot_context["tunnel_mgr"] = tunnel_mgr
    bot_context["dev_mgr"] = dev_mgr
    bot_context["plan_mgr"] = plan_mgr


# ── Static WebApp Routes ──────────────────────────────────────────────

@app.get("/")
async def get_index():
    index_file = WEB_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="index.html not found")


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


# ── API: Status & State ───────────────────────────────────────────────

@app.get("/api/status")
async def get_status():
    bridge = bot_context.get("bridge")
    tunnel_mgr = bot_context.get("tunnel_mgr")
    dev_mgr = bot_context.get("dev_mgr")

    proj_dir = bridge.project_dir if bridge else ""
    model = bridge.model_name if bridge else ""
    mode = bridge.mode if bridge else "act"

    tunnel_info = tunnel_mgr.get_status() if tunnel_mgr else None
    dev_info = dev_mgr.get_status() if dev_mgr else {"running": False}

    from git_manager import get_git_status
    git_stat = await get_git_status(proj_dir) if proj_dir else {}

    return {
        "project": proj_dir,
        "model": model,
        "mode": mode,
        "devRunning": dev_info.get("running", False),
        "devPort": tunnel_info.get("port") if tunnel_info else 8080,
        "tunnelUrl": tunnel_info.get("url", "") if tunnel_info else "",
        "gitBranch": git_stat.get("branch", "main"),
        "gitModifiedCount": len(git_stat.get("modified", [])),
    }


# ── API: Live Screenshot Preview ──────────────────────────────────────

@app.get("/api/preview/image")
async def get_preview_image():
    bridge = bot_context.get("bridge")
    tunnel_mgr = bot_context.get("tunnel_mgr")

    from preview_manager import capture_screenshot, detect_open_port
    proj_dir = bridge.project_dir if bridge else None
    port = (tunnel_mgr.active_port if tunnel_mgr else None) or detect_open_port(project_path=proj_dir) or 8080

    target_url = f"http://localhost:{port}"
    try:
        shot_bytes = await capture_screenshot(target_url, is_mobile=True)
        return Response(content=shot_bytes, media_type="image/png")
    except Exception as e:
        logger.error("Preview capture failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── API: Tunnels & Dev Server ─────────────────────────────────────────

@app.post("/api/tunnel/toggle")
async def toggle_tunnel():
    tunnel_mgr = bot_context.get("tunnel_mgr")
    bridge = bot_context.get("bridge")
    if not tunnel_mgr:
        raise HTTPException(status_code=500, detail="Tunnel manager unavailable")

    if tunnel_mgr.active_url:
        await tunnel_mgr.stop_tunnel()
        return {"active": False, "url": ""}
    else:
        dev_mgr = bot_context.get("dev_mgr")
        url, port = await tunnel_mgr.start_tunnel(
            project_path=bridge.project_dir if bridge else None,
            dev_mgr=dev_mgr,
        )
        return {"active": True, "url": url, "port": port}


@app.post("/api/dev/restart")
async def restart_dev():
    dev_mgr = bot_context.get("dev_mgr")
    bridge = bot_context.get("bridge")
    if not dev_mgr or not bridge:
        raise HTTPException(status_code=500, detail="Dev manager unavailable")

    success, text = await dev_mgr.restart(bridge.project_dir)
    return {"success": success, "message": text}


@app.get("/api/dev/logs")
async def get_dev_logs():
    dev_mgr = bot_context.get("dev_mgr")
    if not dev_mgr:
        return {"logs": "Dev manager not initialized."}
    logs = dev_mgr.get_logs(60)
    return {"logs": "\n".join(logs)}


# ── API: Git & Diffs ──────────────────────────────────────────────────

@app.get("/api/git/diff")
async def get_diff():
    bridge = bot_context.get("bridge")
    if not bridge:
        return {"diff": ""}
    from git_manager import get_git_diff
    diff = await get_git_diff(bridge.project_dir)
    return {"diff": diff}


class PushRequest(BaseModel):
    message: Optional[str] = "update from mobile"


@app.post("/api/git/push")
async def git_push_api(req: PushRequest):
    bridge = bot_context.get("bridge")
    if not bridge:
        raise HTTPException(status_code=500, detail="Agent bridge not ready")

    from git_manager import git_push
    ok, out = await git_push(bridge.project_dir)
    if not ok:
        raise HTTPException(status_code=500, detail=out)
    return {"success": True, "output": out}


# ── API: Projects ─────────────────────────────────────────────────────

@app.get("/api/projects")
async def list_projects():
    bridge = bot_context.get("bridge")
    current_dir = bridge.project_dir.lower() if bridge else ""

    projects = []
    if PROJECTS_ROOT.is_dir():
        for d in sorted(PROJECTS_ROOT.iterdir()):
            if d.is_dir() and not d.name.startswith(".") and d.name not in ("node_modules", "src"):
                is_active = (str(d).lower() == current_dir or str(d / d.name.lower()).lower() == current_dir)
                projects.append({
                    "name": d.name,
                    "path": str(d),
                    "active": is_active,
                })
    return {"projects": projects}


class SwitchProjectRequest(BaseModel):
    name: str


@app.post("/api/projects/switch")
async def switch_project_api(req: SwitchProjectRequest):
    bridge = bot_context.get("bridge")
    if not bridge:
        raise HTTPException(status_code=500, detail="Bridge not ready")

    target = PROJECTS_ROOT / req.name
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="Project not found")

    result = await bridge.switch_project(str(target))
    return {"success": True, "message": result}


class CreateProjectRequest(BaseModel):
    name: str
    template: Optional[str] = "html"


@app.post("/api/projects/create")
async def create_project_api(req: CreateProjectRequest):
    bridge = bot_context.get("bridge")
    if not bridge:
        raise HTTPException(status_code=500, detail="Bridge not ready")

    import re
    clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "-", req.name.strip()).strip("-")
    if not clean_name:
        raise HTTPException(status_code=400, detail="Invalid project name")

    parent_dir = Path(bridge.project_dir).parent
    target_dir = parent_dir / clean_name

    if target_dir.exists():
        raise HTTPException(status_code=400, detail=f"Project '{clean_name}' already exists.")

    target_dir.mkdir(parents=True, exist_ok=True)

    if req.template == "html":
        (target_dir / "index.html").write_text(
            f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{clean_name}</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body style="background:#0b0d13; color:#fff; font-family:sans-serif; display:flex; align-items:center; justify-content:center; height:100vh; margin:0;">
    <div style="text-align:center;">
        <h1>🚀 {clean_name}</h1>
        <p>Created remotely from Antigravity Mobile Mission Control</p>
    </div>
    <script src="app.js"></script>
</body>
</html>""",
            encoding="utf-8",
        )
        (target_dir / "styles.css").write_text("body { margin: 0; padding: 0; }\n", encoding="utf-8")
        (target_dir / "app.js").write_text(f"console.log('{clean_name} initialized');\n", encoding="utf-8")
    else:
        (target_dir / "README.md").write_text(
            f"# {clean_name}\n\nCreated via Antigravity Mobile Mission Control.\n",
            encoding="utf-8",
        )

    switch_res = await bridge.switch_project(str(target_dir))

    return {
        "success": True,
        "name": clean_name,
        "path": str(target_dir),
        "message": switch_res,
    }


# ── API: Plans ────────────────────────────────────────────────────────

@app.get("/api/plan/active")
async def get_active_plan():
    plan_mgr = bot_context.get("plan_mgr")
    if not plan_mgr:
        raise HTTPException(status_code=404, detail="No active plan")

    content = plan_mgr.get_active_plan()
    if not content:
        raise HTTPException(status_code=404, detail="No active plan found")

    # Simple markdown parser for checklists
    import re
    tasks = []
    lines = content.split("\n")
    title = "Active Implementation Plan"

    for line in lines:
        if line.startswith("# ") and title == "Active Implementation Plan":
            title = line.replace("# ", "").replace("📋 Implementation Plan: ", "").strip()
        
        m = re.search(r"\[([ xX])\]\s*(.*)", line)
        if m:
            is_done = m.group(1).lower() == "x"
            raw_text = m.group(2)
            
            # Extract file tag if present
            file_match = re.search(r"`([^`]+)`", raw_text)
            file_tag = file_match.group(1) if file_match else ""
            clean_text = re.sub(r"`[^`]+`", "", raw_text).strip()
            
            tasks.append({
                "done": is_done,
                "text": clean_text or raw_text,
                "file": file_tag,
            })

    return {
        "title": title,
        "tasks": tasks,
        "rawContent": content,
    }


@app.post("/api/plan/approve")
async def approve_plan_api():
    bridge = bot_context.get("bridge")
    plan_mgr = bot_context.get("plan_mgr")
    if not bridge:
        raise HTTPException(status_code=500, detail="Bridge not ready")

    bridge.set_mode("act")
    exec_prompt = (
        "The user has APPROVED the Implementation Plan via the Mission Control Dashboard.\n"
        "Proceed to execute the plan: modify/create the required files, verify the changes, and provide a clear completion report."
    )
    res = await bridge.chat(exec_prompt)

    # Automatically save completed tasks Walkthrough artifact
    try:
        from audit_logger import extract_files_from_text, log_interaction
        files_touched = extract_files_from_text(res, bridge.project_dir)

        if plan_mgr:
            plan_mgr.save_walkthrough(
                title="Executed Implementation Plan",
                execution_response=res,
                files_modified=files_touched,
            )

        log_interaction(
            prompt="[ACTION: Approved Implementation Plan]",
            response=res,
            project_dir=bridge.project_dir,
            model_name=bridge.model_name,
            user_id="mini_app_user",
            files_changed=files_touched,
            mode="act",
        )
    except Exception as e:
        logger.warning("Walkthrough generation failed: %s", e)

    return {"success": True, "output": res}


@app.get("/api/plan/walkthrough")
async def get_active_walkthrough():
    plan_mgr = bot_context.get("plan_mgr")
    if not plan_mgr:
        raise HTTPException(status_code=404, detail="No plan manager")

    content = plan_mgr.get_active_walkthrough()
    if not content:
        raise HTTPException(status_code=404, detail="No completed walkthrough found")

    from audit_logger import extract_files_from_text
    files_touched = extract_files_from_text(content)

    return {
        "title": "Completed Tasks & Walkthrough",
        "rawContent": content,
        "files": files_touched,
    }


# ── API: In-App AI Chat ───────────────────────────────────────────────

class ChatMessageRequest(BaseModel):
    message: str


@app.post("/api/chat/send")
async def send_chat_message(req: ChatMessageRequest):
    bridge = bot_context.get("bridge")
    plan_mgr = bot_context.get("plan_mgr")
    if not bridge:
        raise HTTPException(status_code=500, detail="Agent bridge not ready")

    user_text = req.message.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    from audit_logger import log_interaction
    try:
        if user_text.startswith("/status"):
            tunnel_mgr = bot_context.get("tunnel_mgr")
            dev_mgr = bot_context.get("dev_mgr")
            dev_stat = dev_mgr.get_status() if dev_mgr else {}
            reply = (
                f"📊 **Workspace Status:**\n\n"
                f"• **Workspace:** `{bridge.project_dir}`\n"
                f"• **Active Model:** `{bridge.model_name}`\n"
                f"• **Safety Mode:** `{bridge.mode.upper()}`\n"
                f"• **Dev Server:** `{'🟢 Running (port ' + str(dev_stat.get('port', 8080)) + ')' if dev_stat.get('running') else '⚪ Stopped'}`\n"
                f"• **Tunnel:** `{'🟢 Active' if tunnel_mgr and tunnel_mgr.active_url else '⚪ Offline'}`"
            )
        elif user_text.startswith("/reset"):
            await bridge.reset()
            reply = f"🔄 **Conversation Reset:** Clean slate initialized for `{bridge.project_dir}`. All token context has been reset."
        elif user_text.startswith("/mode"):
            parts = user_text.split()
            if len(parts) > 1 and parts[1].lower() in ("plan", "act"):
                new_mode = parts[1].lower()
                bridge.set_mode(new_mode)
                reply = f"🛡️ **Safety Mode Updated:** Set to `{new_mode.upper()}`. {'(Brainstorming only, files protected)' if new_mode == 'plan' else '(Direct code modifications permitted)'}"
            else:
                reply = f"ℹ️ Current mode is `{bridge.mode.upper()}`. Use `/mode plan` or `/mode act` to switch."
        elif user_text.startswith("/help"):
            reply = (
                "💡 **Available Commands:**\n\n"
                "• `/plan <feature>` — Brainstorm architecture and generate an implementation plan\n"
                "• `/status` — Check active workspace, model, and server status\n"
                "• `/reset` — Reset conversation context & token accumulation\n"
                "• `/mode <plan|act>` — Toggle safety planning vs direct action mode"
            )
        elif user_text.startswith("/plan"):
            topic = user_text[5:].strip() or "Feature Implementation"
            bridge.set_mode("plan")
            plan_prompt = (
                f"[MODE: DRAFT IMPLEMENTATION PLAN — STRICT BRAINSTORMING ONLY]\n"
                f"The user wants to formulate a safe Implementation Plan for:\n"
                f"\"{topic}\"\n\n"
                f"Guidelines for drafting this plan:\n"
                f"1. 🎯 **Goal Description**: Clear architecture & overview.\n"
                f"2. 📋 **Proposed File Changes**: Mark files as `[NEW]`, `[MODIFY]`, or `[DELETE]`.\n"
                f"3. 📝 **Milestone Checklist**: List all actionable steps formatted strictly as markdown checkboxes:\n"
                f"   - [ ] Step 1 description (`file: path/to/file.ext`)\n"
                f"   - [ ] Step 2 description (`file: path/to/file.ext`)\n"
                f"4. 🧪 **Verification Plan**: Commands to verify (lint, test, preview).\n\n"
                f"CRITICAL SAFETY RULE: DO NOT create, modify, or delete any actual project files yet! "
                f"Only brainstorm and output the plan document for user review and approval."
            )
            reply = await bridge.chat(topic, override_prompt=plan_prompt)

            if plan_mgr:
                plan_mgr.save_plan(topic, reply)
        else:
            reply = await bridge.chat(user_text)

        try:
            log_interaction(
                prompt=user_text,
                response=reply,
                project_dir=bridge.project_dir,
                model_name=bridge.model_name,
                user_id="mini_app_user",
                mode=bridge.mode,
            )
        except Exception:
            pass

        return {
            "reply": reply,
            "mode": bridge.mode,
            "project": bridge.project_dir,
            "model": bridge.model_name,
            "isPlan": user_text.startswith("/plan"),
        }
    except Exception as e:
        logger.error("Chat error in Mini App: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chat/history")
async def get_chat_history():
    from audit_logger import get_latest_audit_entries
    raw = get_latest_audit_entries(20)
    return {"history": raw}


# ── API: Change History & Audit Timeline ──────────────────────────────

@app.get("/api/history")
async def get_history_timeline():
    bridge = bot_context.get("bridge")
    from audit_logger import get_structured_history
    proj_dir = bridge.project_dir if bridge else None
    history = get_structured_history(project_dir=proj_dir, limit=50)
    return {"history": history}
